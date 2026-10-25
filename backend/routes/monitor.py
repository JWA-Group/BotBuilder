"""System Monitor API: resources, processes, batched log stream (optional bot_id filter)."""

from __future__ import annotations

from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.core.monitor import (
    get_resource_metrics,
    kill_process_by_pid,
    list_running_processes,
    log_hub,
    monitor_stream_connected,
    monitor_stream_disconnected,
    monitor_touch,
    restart_bot_process,
    _collect_bot_pids,
    _memory_mb_for_pid,
    _read_bot_name,
)
from core.runner import bot_runner

router = APIRouter(prefix="/api/monitor", tags=["monitor"])


class ProcessActionBody(BaseModel):
    action: str = Field(..., description='"kill" or "restart"')


@router.get("/resources")
async def monitor_resources():
    monitor_touch()
    try:
        return get_resource_metrics()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/processes")
async def monitor_processes():
    monitor_touch()
    try:
        return {"processes": list_running_processes()}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/bot/{bot_id}/snapshot")
async def monitor_bot_snapshot(bot_id: int):
    """Per-bot process + host resource slice for Run & Logs studio."""
    monitor_touch()
    try:
        resources = get_resource_metrics()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    procs = list_running_processes()
    match = next((p for p in procs if int(p.get("bot_id") or -1) == int(bot_id)), None)
    running = match is not None
    pid = None
    if running:
        pid = match.get("pid")
    else:
        # Fallback to runner map / pid file
        try:
            proc = bot_runner.running_bots.get(bot_id)
            if proc and proc.poll() is None:
                pid = proc.pid
                running = True
        except Exception:
            pass
        if not running:
            pids = _collect_bot_pids()
            if bot_id in pids:
                pid = pids[bot_id]
                running = True

    return {
        "bot_id": bot_id,
        "name": _read_bot_name(bot_id),
        "running": running,
        "pid": pid,
        "cpu_percent": (match or {}).get("cpu_percent", 0.0),
        "memory_mb": (match or {}).get("memory_mb")
        or (_memory_mb_for_pid(pid) if pid else 0.0),
        "uptime_sec": (match or {}).get("uptime_sec", 0),
        "host": {
            "cpu_percent": resources.get("cpu_percent"),
            "memory_percent": resources.get("memory_percent"),
            "memory_used_mb": resources.get("memory_used_mb"),
            "memory_total_mb": resources.get("memory_total_mb"),
        },
    }


@router.post("/process/{pid}/action")
async def monitor_process_action(pid: int, body: ProcessActionBody):
    action = (body.action or "").strip().lower()
    if action not in ("kill", "restart"):
        raise HTTPException(status_code=400, detail='action must be "kill" or "restart"')
    if pid <= 0:
        raise HTTPException(status_code=400, detail="Invalid PID")

    try:
        if action == "kill":
            result = kill_process_by_pid(pid)
        else:
            result = await restart_bot_process(pid)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("error", "Action failed"))
    return result


@router.get("/logs/history")
async def monitor_logs_history(
    limit: int = 300,
    bot_id: int | None = Query(None, description="Restrict to a single bot"),
):
    monitor_touch()
    limit = max(1, min(limit, 2000))
    return {"logs": log_hub.history(limit, bot_id=bot_id), "bot_id": bot_id}


@router.delete("/logs")
async def monitor_logs_clear(
    bot_id: int | None = Query(None, description="Clear only this bot's log packets"),
):
    """Clear monitor log buffer (optionally scoped to bot_id)."""
    monitor_touch()
    cleared = log_hub.clear(bot_id=bot_id)
    return {"ok": True, "cleared": cleared, "bot_id": bot_id}


async def _log_sse_generator(bot_id: int | None = None) -> AsyncGenerator[str, None]:
    """SSE worker: flush accumulated logs as JSON arrays every 500ms."""
    monitor_stream_connected()
    try:
        async for chunk in log_hub.iter_batched_sse(replay=80, bot_id=bot_id):
            yield chunk
    finally:
        monitor_stream_disconnected()


def _sse_response(bot_id: int | None = None) -> StreamingResponse:
    return StreamingResponse(
        _log_sse_generator(bot_id=bot_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/logs/stream")
async def monitor_logs_stream(
    bot_id: int | None = Query(
        None,
        description="When set, stream only packets for this bot_id (strict isolation)",
    ),
):
    """Server-Sent Events stream of batched log packets (List[Dict] every 500ms)."""
    return _sse_response(bot_id=bot_id)


@router.get("/stream")
async def monitor_stream_alias(
    bot_id: int | None = Query(
        None,
        description="When set, stream only packets for this bot_id (strict isolation)",
    ),
):
    """Alias for /logs/stream — preferred by workspace Run & Logs studio."""
    return _sse_response(bot_id=bot_id)
