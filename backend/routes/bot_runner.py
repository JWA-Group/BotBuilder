import asyncio
import os
import json
import subprocess
from pathlib import Path
from fastapi import APIRouter, HTTPException, Request
from backend.utils.generate_main import generate_main_from_scenario, get_bot_platform
from backend.core.scenario_deps import PhantomNodeError
from core.runner import bot_runner

router = APIRouter(prefix="/api/bots", tags=["BotRunner"])

from backend.core.app_paths import PROJECTS_DIR

running_bots = bot_runner.running_bots


def _bot_dir(bot_id: int) -> str:
    return os.path.join(PROJECTS_DIR, f"bot_{bot_id}")


def _read_launcher_log(bot_id: int, lines: int = 10) -> str:
    path = os.path.join(_bot_dir(bot_id), "launcher.log")
    if not os.path.exists(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return "".join(f.readlines()[-lines:]).strip()
    except OSError:
        return ""


def _read_log_tail(bot_id: int, lines: int = 20) -> str:
    log_path = os.path.join(_bot_dir(bot_id), "bot.log")
    if not os.path.exists(log_path):
        return ""
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            return "".join(f.readlines()[-lines:]).strip()
    except OSError:
        return ""


def _get_running_pid(bot_id: int) -> int | None:
    return bot_runner.get_running_pid(bot_id)


def _terminate_bot(bot_id: int):
    """Остановить процесс бота (память + run.pid)."""
    bot_runner.terminate(bot_id)


def _log_indicates_ready(bot_id: int) -> bool:
    tail = _read_log_tail(bot_id, 40)
    return "Start polling" in tail or "Run polling" in tail or "polling" in tail.lower()


async def _wait_process_started(bot_id: int, process: subprocess.Popen) -> bool:
    """Ждём готовности: процесс жив и в логе есть признак успешного старта."""
    for _ in range(120):
        if process.poll() is not None:
            return False
        if _log_indicates_ready(bot_id):
            await asyncio.sleep(0.5)
            if process.poll() is None:
                return True
            return False
        await asyncio.sleep(0.25)
    return False


def _format_start_error(stderr_tail: str) -> str:
    hint = "Проверьте токен Telegram-бота."
    if "api.telegram.org" in stderr_tail or "TelegramNetworkError" in stderr_tail:
        hint = (
            "Нет доступа к api.telegram.org. Включите VPN/прокси (Clash, v2ray) "
            "или проверьте, что Python видит системный прокси."
        )
    return hint


@router.get("/status/{bot_id}")
async def get_bot_status(bot_id: int):
    pid = _get_running_pid(bot_id)
    running = pid is not None
    return {"status": "running" if running else "stopped", "running": running, "pid": pid}


@router.post("/start/{bot_id}")
async def start_bot(bot_id: int):
    existing = _get_running_pid(bot_id)
    if existing:
        return {"status": "already running", "pid": existing}

    # Старый «зависший» процесс мешает новому запуску
    _terminate_bot(bot_id)
    await asyncio.sleep(0.3)

    bot_dir = _bot_dir(bot_id)
    path = os.path.join(bot_dir, "main.py")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="main.py не найден")

    try:
        generate_main_from_scenario(bot_id, platform=get_bot_platform(bot_id))
    except PhantomNodeError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except ValueError as e:
        if "Compilation locked" in str(e):
            raise HTTPException(status_code=422, detail=str(e)) from e
        raise HTTPException(status_code=500, detail=f"Ошибка генерации main.py: {e}") from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка генерации main.py: {e}") from e

    platform = "telegram"
    os.makedirs(bot_dir, exist_ok=True)
    launcher_log = os.path.join(bot_dir, "launcher.log")
    stderr_log = os.path.join(bot_dir, "stderr.log")

    try:
        process = bot_runner.start(
            bot_id,
            stderr_log=Path(stderr_log),
            launcher_log=Path(launcher_log),
            platform=platform,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    started_ok = await _wait_process_started(bot_id, process)
    if not started_ok:
        tail = _read_log_tail(bot_id) or _read_launcher_log(bot_id)
        stderr_tail = ""
        if os.path.exists(stderr_log):
            try:
                with open(stderr_log, encoding="utf-8", errors="replace") as ef:
                    stderr_tail = ef.read()[-800:]
            except OSError:
                pass
        hint = _format_start_error(stderr_tail)
        detail = f"Не удалось запустить бота. {hint}"
        if tail:
            detail += f"\n\nЛог:\n{tail[-1200:]}"
        if stderr_tail:
            detail += f"\n\nstderr:\n{stderr_tail}"
        raise HTTPException(status_code=500, detail=detail)

    running_bots[bot_id] = process
    bot_runner.write_pid(bot_id, process.pid)
    try:
        from backend.core.monitor import log_hub

        log_hub.emit(f"Bot #{bot_id} started (pid={process.pid})", layer="API", bot_id=bot_id)
    except Exception:
        pass
    return {"status": "started", "pid": process.pid, "platform": platform}


@router.post("/stop/{bot_id}")
async def stop_bot(bot_id: int):
    if not _get_running_pid(bot_id) and bot_id not in running_bots:
        return {"status": "not running"}
    _terminate_bot(bot_id)
    try:
        from backend.core.monitor import log_hub

        log_hub.emit(f"Bot #{bot_id} stopped", layer="API", bot_id=bot_id)
    except Exception:
        pass
    return {"status": "stopped"}


@router.get("/log/{bot_id}")
async def get_bot_log(bot_id: int, lines: int = 50):
    tail = _read_log_tail(bot_id, lines=min(lines, 200))
    return {"log": tail or "(лог пуст)", "running": _get_running_pid(bot_id) is not None}


@router.post("/handlers/{bot_id}")
async def save_handlers(bot_id: int, request: Request):
    data = await request.json()
    path = os.path.join(_bot_dir(bot_id), "handlers.json")

    if not os.path.exists(_bot_dir(bot_id)):
        raise HTTPException(status_code=404, detail="Папка проекта не найдена")

    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при сохранении: {e}")

    return {"status": "ok"}


@router.get("/handlers/{bot_id}")
async def get_handlers(bot_id: int):
    path = os.path.join(_bot_dir(bot_id), "handlers.json")

    if not os.path.exists(path):
        return {"commands": []}

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при чтении: {e}")
