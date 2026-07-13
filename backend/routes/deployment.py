"""Deployment wizard API: ZIP export and SSH auto-deploy with SSE logs."""

from __future__ import annotations

import asyncio
import json
import queue
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.auth_deps import get_current_user_id_required
from backend.core.bot_access import require_bot_access
from backend.core.deploy import (
    create_deploy_job,
    get_deploy_job,
    get_deploy_log_path,
    get_latest_deploy_log_path,
    list_deploy_logs,
    start_ssh_deploy_thread,
)
from backend.core.deploy_bundle import build_export_zip
from backend.core.scenario_deps import PhantomNodeError
from backend.db.database import get_db
from backend.utils.generate_main import generate_main_from_scenario

router = APIRouter(prefix="/api/projects", tags=["deployment"])


class SshDeployPayload(BaseModel):
    host: str = Field(..., min_length=1, description="Remote server IP or hostname")
    username: str = Field(..., min_length=1)
    password: str | None = Field(default=None, description="SSH password (optional if key provided)")
    ssh_private_key: str | None = Field(default=None, description="PEM private key contents")
    port: int = Field(default=22, ge=1, le=65535)


@router.get("/{bot_id}/export/zip")
async def export_project_zip(
    bot_id: int,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    """Compile bot and download production Docker bundle as ZIP."""
    await require_bot_access(db, bot_id, user_id)
    try:
        data = build_export_zip(bot_id, compile_first=True)
    except PhantomNodeError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Компиляция заблокирована: отсутствует плагин для блока «{exc}».",
        ) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    filename = f"bot_{bot_id}_deploy.zip"
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{bot_id}/deploy/ssh")
async def deploy_project_ssh(
    bot_id: int,
    body: SshDeployPayload,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    """Start asynchronous SSH provisioning; stream logs via SSE endpoint."""
    await require_bot_access(db, bot_id, user_id)

    if not body.password and not body.ssh_private_key:
        raise HTTPException(status_code=400, detail="Укажите password или ssh_private_key")

    try:
        generate_main_from_scenario(bot_id)
    except PhantomNodeError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Компиляция заблокирована: отсутствует плагин для блока «{exc}».",
        ) from exc

    try:
        from core.runner import bot_runner as _runner

        if _runner.get_running_pid(bot_id):
            _runner.terminate(bot_id)
    except Exception:
        pass

    job_id, broker = create_deploy_job(bot_id)
    start_ssh_deploy_thread(
        bot_id,
        host=body.host,
        username=body.username,
        password=body.password,
        ssh_private_key=body.ssh_private_key,
        port=body.port,
        broker=broker,
    )
    return {
        "job_id": job_id,
        "stream_url": f"/api/projects/{bot_id}/deploy/ssh/stream/{job_id}",
        "log_download": f"/api/projects/{bot_id}/deploy/logs/{job_id}",
        "message": "SSH-деплой запущен. Полный лог сохраняется в projects/deploy_logs/.",
    }


async def _sse_event_generator(job_id: str) -> AsyncGenerator[str, None]:
    job = get_deploy_job(job_id)
    if not job:
        yield f"data: {json.dumps({'type': 'done', 'success': False, 'error': 'Job not found'})}\n\n"
        return

    broker = job["broker"]
    loop = asyncio.get_event_loop()

    while True:
        try:
            item = await loop.run_in_executor(None, lambda: broker.queue.get(timeout=1.0))
            yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
            if item.get("type") == "done":
                break
        except queue.Empty:
            if broker.done:
                break
            yield ": keepalive\n\n"


@router.get("/{bot_id}/deploy/ssh/stream/{job_id}")
async def deploy_ssh_stream(
    bot_id: int,
    job_id: str,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    """Server-Sent Events stream of remote provisioning logs."""
    await require_bot_access(db, bot_id, user_id)
    job = get_deploy_job(job_id)
    if not job or job.get("bot_id") != bot_id:
        raise HTTPException(status_code=404, detail="Задача деплоя не найдена")

    return StreamingResponse(
        _sse_event_generator(job_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{bot_id}/deploy/logs")
async def list_project_deploy_logs(
    bot_id: int,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    await require_bot_access(db, bot_id, user_id)
    return {"logs": list_deploy_logs(bot_id)}


@router.get("/{bot_id}/deploy/logs/latest")
async def download_latest_deploy_log(
    bot_id: int,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    await require_bot_access(db, bot_id, user_id)
    path = get_latest_deploy_log_path(bot_id)
    if not path:
        raise HTTPException(status_code=404, detail="Лог деплоя не найден")
    text = path.read_text(encoding="utf-8", errors="replace")
    filename = f"deploy_bot_{bot_id}_latest.log"
    return Response(
        content=text.encode("utf-8"),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{bot_id}/deploy/logs/{job_id}")
async def download_deploy_log(
    bot_id: int,
    job_id: str,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    await require_bot_access(db, bot_id, user_id)
    path = get_deploy_log_path(job_id)
    if not path:
        raise HTTPException(status_code=404, detail="Лог деплоя не найден")
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if f"# bot_id: {bot_id}\n" not in text[:500]:
        raise HTTPException(status_code=404, detail="Лог не относится к этому боту")
    filename = f"deploy_bot_{bot_id}_{job_id[:8]}.log"
    return Response(
        content=text.encode("utf-8"),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
