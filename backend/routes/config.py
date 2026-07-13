"""
Публичный базовый URL приложения. Если ngrok запущен — подставляется автоматически (без перезапуска).
"""
import os

from fastapi import APIRouter, HTTPException, Request

from backend.core.config import get_app_base_url
from core.runner import bot_runner

router = APIRouter(prefix="/api/config", tags=["config"])
health_router = APIRouter(tags=["health"])


@health_router.get("/api/health")
def health():
    import json

    from backend.core.app_paths import get_app_root

    build_stamp = None
    try:
        stamp_path = get_app_root() / "frontend" / "shared" / "build-stamp.json"
        if stamp_path.is_file():
            build_stamp = json.loads(stamp_path.read_text(encoding="utf-8"))
    except Exception:
        build_stamp = None

    return {
        "status": "ok",
        "app_root": str(get_app_root()),
        "desktop": os.environ.get("DESKTOP_APP") == "1",
        "build": build_stamp,
    }


@health_router.post("/api/shutdown")
async def shutdown_desktop(request: Request):
    """Останавливает все боты перед выходом Electron (только localhost + DESKTOP_APP)."""
    client = request.client
    if client is None or client.host not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(status_code=403, detail="Forbidden")
    if os.environ.get("DESKTOP_APP") != "1":
        raise HTTPException(status_code=403, detail="Shutdown only in desktop mode")

    stopped = bot_runner.terminate_all()
    return {"status": "ok", "bots_stopped": stopped}


@router.get("/base-url")
def get_base_url():
    """Возвращает базовый URL (из APP_BASE_URL или авто из ngrok)."""
    return {"base_url": get_app_base_url().rstrip("/")}
