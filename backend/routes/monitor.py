"""System Monitor API: resources, processes, batched log stream."""

from __future__ import annotations

from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException
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
)

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
async def monitor_logs_history(limit: int = 300):
    monitor_touch()
    limit = max(1, min(limit, 2000))
    return {"logs": log_hub.history(limit)}


@router.delete("/logs")
async def monitor_logs_clear():
    """Persistently clear the monitor log buffer (survives page reload)."""
    monitor_touch()
    cleared = log_hub.clear()
    return {"ok": True, "cleared": cleared}


async def _log_sse_generator() -> AsyncGenerator[str, None]:
    """SSE worker: flush accumulated logs as JSON arrays every 500ms."""
    monitor_stream_connected()
    try:
        async for chunk in log_hub.iter_batched_sse(replay=80):
            yield chunk
    finally:
        monitor_stream_disconnected()


@router.get("/logs/stream")
async def monitor_logs_stream():
    """Server-Sent Events stream of batched log packets (List[Dict] every 500ms)."""
    return StreamingResponse(
        _log_sse_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
