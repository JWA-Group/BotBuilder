from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
import asyncio
import os
import json

from pydantic import BaseModel, Field

from backend.db.database import get_db
from backend.utils.generate_main import generate_main_from_scenario, get_bot_platform
from backend.core.auth_deps import get_current_user_id_required
from backend.core.bot_access import require_bot_access
from backend.core.scenario_deps import PhantomNodeError, normalize_scenario_document
from backend.core.history import (
    MAX_VERSIONS,
    RETENTION_SECONDS,
    archive_scenario,
    ensure_baseline_version,
    list_versions,
    load_version,
    restore_version,
)
from backend.services.ai_scenario_perplexity import (
    call_perplexity_scenario,
    extract_field_and_command_hints,
)

router = APIRouter(prefix="/api/scenario")

from backend.core.app_paths import PROJECTS_DIR


async def _check_bot_owner(db: AsyncSession, bot_id: str, user_id: int) -> int:
    bot = await require_bot_access(db, bot_id, user_id)
    return bot.id


@router.get("/load/{bot_id}")
async def load_scenario(
    bot_id: str,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    await _check_bot_owner(db, bot_id, user_id)
    path = os.path.join(PROJECTS_DIR, f"bot_{bot_id}", "scenario.json")
    if not os.path.exists(path):
        return normalize_scenario_document({})
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return normalize_scenario_document(data if isinstance(data, dict) else {})


@router.post("/save/{bot_id}")
async def save_scenario(
    bot_id: str,
    request: Request,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    await _check_bot_owner(db, bot_id, user_id)
    raw = await request.json()
    data = normalize_scenario_document(raw if isinstance(raw, dict) else {})
    path = os.path.join(PROJECTS_DIR, f"bot_{bot_id}", "scenario.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    bid = int(bot_id)
    save_kind = (request.query_params.get("kind") or "user").strip().lower()
    if save_kind not in ("user", "auto"):
        save_kind = "user"
    try:
        archive_scenario(bid, data, kind=save_kind, projects_dir=PROJECTS_DIR)
    except Exception:
        pass

    compile_error = None
    try:
        generate_main_from_scenario(bid, platform=get_bot_platform(bid))
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
            headers={"X-Scenario-Saved": "1"},
        )

    hot_reload: dict | None = None
    try:
        platform = get_bot_platform(bid)
        from core.runner import bot_runner

        if bot_runner.is_running(bid):
            from backend.core.monitor import log_hub

            result = await asyncio.to_thread(
                bot_runner.restart_bot,
                bid,
                platform=platform,
            )
            hot_reload = result
            if result.get("restarted"):
                pid = result.get("pid")
                log_hub.emit(
                    f"[SYSTEM] Hot Reload triggered for Bot #{bid}. "
                    f"Recompiled and successfully restarted (pid={pid}).",
                    layer="API",
                    bot_id=bid,
                )
            elif result.get("error"):
                log_hub.emit(
                    f"[SYSTEM] Hot Reload failed for Bot #{bid}: {result['error']}",
                    layer="ERROR",
                    bot_id=bid,
                )
    except Exception as exc:
        try:
            from backend.core.monitor import log_hub

            log_hub.emit(
                f"[SYSTEM] Hot Reload failed for Bot #{bid}: {exc}",
                layer="ERROR",
                bot_id=bid,
            )
        except Exception:
            pass
        hot_reload = {"restarted": False, "error": str(exc)}

    return {
        "status": "ok",
        "required_plugins": data.get("required_plugins", []),
        "hot_reload": hot_reload,
    }


@router.get("/history/{bot_id}")
async def scenario_history_list(
    bot_id: str,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    bid = await _check_bot_owner(db, bot_id, user_id)
    try:
        ensure_baseline_version(bid, projects_dir=PROJECTS_DIR)
        versions = list_versions(bid, projects_dir=PROJECTS_DIR)
        return {
            "versions": versions,
            "max_versions": MAX_VERSIONS,
            "retention_hours": RETENTION_SECONDS // 3600,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/history/{bot_id}/snapshot")
async def scenario_history_snapshot(
    bot_id: str,
    request: Request,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    bid = await _check_bot_owner(db, bot_id, user_id)
    raw = await request.json()
    data = normalize_scenario_document(raw if isinstance(raw, dict) else {})
    try:
        ts = archive_scenario(bid, data, kind="auto", projects_dir=PROJECTS_DIR)
        return {"status": "ok", "timestamp": ts}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/history/{bot_id}/{timestamp}")
async def scenario_history_version(
    bot_id: str,
    timestamp: int,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    bid = await _check_bot_owner(db, bot_id, user_id)
    try:
        return load_version(bid, timestamp, projects_dir=PROJECTS_DIR)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/history/{bot_id}/{timestamp}/restore")
async def scenario_history_restore(
    bot_id: str,
    timestamp: int,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    bid = await _check_bot_owner(db, bot_id, user_id)
    try:
        data, new_ts = restore_version(bid, timestamp, projects_dir=PROJECTS_DIR)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    compile_error = None
    try:
        generate_main_from_scenario(bid, platform=get_bot_platform(bid))
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
        platform = get_bot_platform(bid)
        from core.runner import bot_runner

        if bot_runner.is_running(bid):
            from backend.core.monitor import log_hub

            result = await asyncio.to_thread(
                bot_runner.restart_bot,
                bid,
                platform=platform,
            )
            hot_reload = result
            if result.get("restarted"):
                pid = result.get("pid")
                log_hub.emit(
                    f"[SYSTEM] Restored history v{timestamp} for Bot #{bid}. "
                    f"Hot Reload (pid={pid}).",
                    layer="API",
                    bot_id=bid,
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


class AiScenarioContext(BaseModel):
    """Текущий проект: чтобы модель не дублировала поля и учитывала command."""

    known_field_names: list[str] = Field(default_factory=list)
    existing_commands: list[str] = Field(default_factory=list)


class AiScenarioBody(BaseModel):
    description: str = Field(..., min_length=5, max_length=6000)
    context: AiScenarioContext | None = None


def _merge_unique(a: list[str], b: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in a + b:
        s = str(x).strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


@router.post("/ai-generate/{bot_id}")
async def ai_generate_scenario(
    bot_id: str,
    body: AiScenarioBody,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    """Один запрос к Perplexity: краткое ТЗ + нормализованный scenario (блоки и связи)."""
    bid = await _check_bot_owner(db, bot_id, user_id)
    merged_fields: list[str] = []
    merged_cmds: list[str] = []
    if body.context:
        merged_fields = [str(x).strip() for x in body.context.known_field_names if str(x).strip()]
        merged_cmds = [str(x).strip() for x in body.context.existing_commands if str(x).strip()]
    path = os.path.join(PROJECTS_DIR, f"bot_{bid}", "scenario.json")
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                disk = json.load(f)
            df, dc = extract_field_and_command_hints(disk if isinstance(disk, dict) else {})
            merged_fields = _merge_unique(merged_fields, df)
            merged_cmds = _merge_unique(merged_cmds, dc)
        except (OSError, json.JSONDecodeError):
            pass
    try:
        brief, scenario = call_perplexity_scenario(
            body.description,
            known_field_names=merged_fields or None,
            existing_commands=merged_cmds or None,
        )
    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail="Модель вернула невалидный JSON") from None
    except ValueError as e:
        msg = str(e)
        if "PERPLEXITY_API_KEY" in msg:
            raise HTTPException(status_code=503, detail=msg) from None
        raise HTTPException(status_code=502, detail=msg) from None
    return {"optimized_brief": brief, "scenario": scenario}
