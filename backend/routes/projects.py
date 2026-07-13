"""Project-level operations: database manager and legacy import alias."""

from __future__ import annotations

import asyncio
import os

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.broadcast import BroadcastError, fetch_broadcast_filters, get_broadcast_job, normalize_telegram_html, start_broadcast
from backend.core.database import (
    DatabaseManagerError,
    delete_row,
    fetch_table_data,
    import_database,
    list_tables,
    update_row,
)
from backend.core import analytics as analytics_core
from backend.core.auth_deps import get_current_user_id_required
from backend.core.bot_access import require_bot_access
from backend.core.history import (
    MAX_VERSIONS,
    RETENTION_SECONDS,
    archive_scenario,
    ensure_baseline_version,
    list_versions,
    load_version,
    restore_version,
)
from backend.core.scenario_deps import PhantomNodeError, normalize_scenario_document
from backend.db.database import get_db
from backend.utils.generate_main import generate_main_from_scenario, get_bot_platform

router = APIRouter(prefix="/api/projects", tags=["projects"])

from backend.core.app_paths import PROJECTS_DIR


class ImportPayload(BaseModel):
    file_path: str = Field(..., min_length=1, description="Absolute path to .db/.sqlite/.json export")


class RowMutationPayload(BaseModel):
    table: str
    primary_key: dict = Field(default_factory=dict)
    values: dict | None = None


class DeleteRowPayload(BaseModel):
    table: str
    primary_key: dict = Field(default_factory=dict)


class BroadcastSendPayload(BaseModel):
    html_content: str = ""
    target_role: str = Field(default="all", description='Filter id: "all", "role:admin", "field:tag:vip"')
    image_paths: list[str] = Field(default_factory=list)
    file_paths: list[str] = Field(default_factory=list)
    image_position: str = Field(default="before", description='"before" — фото над текстом (подпись); "after" — текст, затем фото')


class BroadcastNormalizePayload(BaseModel):
    html_content: str = ""


@router.get("/{bot_id}/db/tables")
async def get_db_tables(
    bot_id: int,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    await require_bot_access(db, bot_id, user_id)
    try:
        return list_tables(bot_id)
    except DatabaseManagerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{bot_id}/db/data")
async def get_db_table_data(
    bot_id: int,
    table: str = Query(..., min_length=1),
    limit: int = Query(1000, ge=1, le=10000),
    offset: int = Query(0, ge=0),
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    await require_bot_access(db, bot_id, user_id)
    try:
        return fetch_table_data(bot_id, table, limit=limit, offset=offset)
    except DatabaseManagerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/{bot_id}/db/row")
async def put_db_row(
    bot_id: int,
    payload: RowMutationPayload,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    await require_bot_access(db, bot_id, user_id)
    try:
        return update_row(
            bot_id,
            table=payload.table,
            primary_key=payload.primary_key,
            values=payload.values or {},
        )
    except DatabaseManagerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{bot_id}/db/row")
async def remove_db_row(
    bot_id: int,
    payload: DeleteRowPayload,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    await require_bot_access(db, bot_id, user_id)
    try:
        return delete_row(bot_id, table=payload.table, primary_key=payload.primary_key)
    except DatabaseManagerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{bot_id}/db/import")
async def import_db_file(
    bot_id: int,
    payload: ImportPayload,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    await require_bot_access(db, bot_id, user_id)
    try:
        return import_database(bot_id, payload.file_path.strip())
    except DatabaseManagerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Ошибка чтения файла: {exc}") from exc


@router.post("/{bot_id}/import-data")
async def import_bot_data_legacy(
    bot_id: int,
    payload: ImportPayload,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    """Legacy alias — use POST /db/import instead."""
    return await import_db_file(bot_id, payload, user_id, db)


@router.get("/{bot_id}/broadcast/roles")
async def get_broadcast_roles(
    bot_id: int,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    await require_bot_access(db, bot_id, user_id)
    try:
        return fetch_broadcast_filters(bot_id)
    except BroadcastError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{bot_id}/broadcast/normalize")
async def normalize_broadcast_html(
    bot_id: int,
    payload: BroadcastNormalizePayload,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    await require_bot_access(db, bot_id, user_id)
    normalized = normalize_telegram_html(payload.html_content)
    return {"normalized_html": normalized}


@router.post("/{bot_id}/broadcast/send")
async def send_broadcast(
    bot_id: int,
    payload: BroadcastSendPayload,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    await require_bot_access(db, bot_id, user_id)
    try:
        return start_broadcast(
            bot_id,
            html_content=payload.html_content,
            target_role=payload.target_role,
            image_paths=payload.image_paths,
            file_paths=payload.file_paths,
            image_position=payload.image_position,
        )
    except BroadcastError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{bot_id}/broadcast/status/{job_id}")
async def get_broadcast_status(
    bot_id: int,
    job_id: str,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    await require_bot_access(db, bot_id, user_id)
    job = get_broadcast_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Задача рассылки не найдена")
    return job


@router.get("/{bot_id}/analytics/overview")
async def project_analytics_overview(
    bot_id: int,
    range: str = Query("30d", description="today | 7d | 30d | custom"),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    """KPI overview with period-over-period deltas."""
    await require_bot_access(db, bot_id, user_id)
    try:
        return analytics_core.overview(
            bot_id, range_key=range, date_from=date_from, date_to=date_to
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/{bot_id}/analytics/activity")
async def project_analytics_activity(
    bot_id: int,
    range: str = Query("30d"),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    """Daily time-series: new_users + messages_count."""
    await require_bot_access(db, bot_id, user_id)
    try:
        return analytics_core.activity_series(
            bot_id, range_key=range, date_from=date_from, date_to=date_to
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/{bot_id}/history")
async def project_history_list(
    bot_id: int,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    """Sorted rollback points for the scenario Time Machine."""
    await require_bot_access(db, bot_id, user_id)
    try:
        ensure_baseline_version(bot_id, projects_dir=PROJECTS_DIR)
        versions = list_versions(bot_id, projects_dir=PROJECTS_DIR)
        return {
            "versions": versions,
            "max_versions": MAX_VERSIONS,
            "retention_hours": RETENTION_SECONDS // 3600,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/{bot_id}/history/snapshot")
async def project_history_snapshot(
    bot_id: int,
    request: Request,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    """Archive current editor state as an autosave without overwriting live scenario.json."""
    await require_bot_access(db, bot_id, user_id)
    raw = await request.json()
    data = normalize_scenario_document(raw if isinstance(raw, dict) else {})
    try:
        ts = archive_scenario(bot_id, data, kind="auto", projects_dir=PROJECTS_DIR)
        return {"status": "ok", "timestamp": ts}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/{bot_id}/history/{timestamp}")
async def project_history_version(
    bot_id: int,
    timestamp: int,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    """Raw scenario JSON for a specific historical snapshot."""
    await require_bot_access(db, bot_id, user_id)
    try:
        return load_version(bot_id, timestamp, projects_dir=PROJECTS_DIR)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{bot_id}/history/{timestamp}/restore")
async def project_history_restore(
    bot_id: int,
    timestamp: int,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    """Overwrite live scenario.json with a historical version, recompile, and hot-reload."""
    await require_bot_access(db, bot_id, user_id)
    try:
        data, new_ts = restore_version(bot_id, timestamp, projects_dir=PROJECTS_DIR)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    compile_error = None
    try:
        generate_main_from_scenario(bot_id, platform=get_bot_platform(bot_id))
    except PhantomNodeError as exc:
        compile_error = str(exc)
    except (ValueError, TypeError) as exc:
        if isinstance(exc, ValueError) and "Compilation locked" in str(exc):
            compile_error = str(exc)
        elif not isinstance(exc, TypeError):
            compile_error = str(exc)
    except Exception as exc:
        compile_error = str(exc)

    if compile_error:
        raise HTTPException(
            status_code=422,
            detail=compile_error,
            headers={"X-Scenario-Restored": "1"},
        )

    hot_reload: dict | None = None
    try:
        platform = get_bot_platform(bot_id)
        from core.runner import bot_runner

        if bot_runner.is_running(bot_id):
            from backend.core.monitor import log_hub

            result = await asyncio.to_thread(
                bot_runner.restart_bot,
                bot_id,
                platform=platform,
            )
            hot_reload = result
            if result.get("restarted"):
                pid = result.get("pid")
                log_hub.emit(
                    f"[SYSTEM] Restored history v{timestamp} for Bot #{bot_id}. "
                    f"Hot Reload (pid={pid}).",
                    layer="API",
                    bot_id=bot_id,
                )
    except Exception as exc:
        hot_reload = {"restarted": False, "error": str(exc)}

    return {
        "status": "ok",
        "timestamp": new_ts,
        "restored_from": timestamp,
        "scenario": data,
        "hot_reload": hot_reload,
    }


@router.get("/{bot_id}/analytics/funnel")
async def project_analytics_funnel(
    bot_id: int,
    range: str = Query("30d"),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    """Canvas block funnel with absolute counts and relative drop-off %."""
    await require_bot_access(db, bot_id, user_id)
    try:
        return analytics_core.funnel(
            bot_id, range_key=range, date_from=date_from, date_to=date_to
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
