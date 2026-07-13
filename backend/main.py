import os
import sys
from pathlib import Path

# Загружаем .env (до импорта config и routes)
def _load_env():
    try:
        from dotenv import load_dotenv
        root = Path(__file__).resolve().parents[1]
        loaded = False
        for p in [root / ".env", Path.cwd() / ".env", Path(".env")]:
            if p.resolve().exists():
                load_dotenv(p.resolve())
                loaded = True
                break
    except ImportError:
        pass

_load_env()

if sys.platform == "win32":
    import asyncio

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.middleware.sessions import SessionMiddleware

from backend.db.database import init_db
from backend.core.broadcast import normalize_telegram_html
from backend.core.app_paths import ensure_data_dirs, get_frontend_dir, resolve_plugin_folder
from backend.core.plugin_manager import get_plugin_manager
from backend.routes import auth, bots, commands, bot_runner, scenario, templates, analytics, miniapps, config, plugins, projects, deployment, monitor
from backend.core.monitor import start_monitor_services, stop_monitor_services, MonitorAPIMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_data_dirs()
    await init_db()
    get_plugin_manager().reload()
    start_monitor_services()
    gid = os.environ.get("GOOGLE_CLIENT_ID", "")
    if gid:
        print("Google OAuth: настроен")
    else:
        print("Google OAuth: не настроен (GOOGLE_CLIENT_ID пуст). Создайте .env в корне проекта.")
    yield
    stop_monitor_services()


app = FastAPI(lifespan=lifespan)


class NoCacheHtmlMiddleware(BaseHTTPMiddleware):
    """Desktop shell: always serve fresh HTML/JS modules (avoid stale placeholder pages)."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        path = request.url.path.lower()
        if path.endswith(".html") or path.endswith(".js") or path.endswith(".css"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
        return response


app.add_middleware(NoCacheHtmlMiddleware)

# Сессии для OAuth (Google)
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("SESSION_SECRET", "change-me-in-production-session-secret"),
)

# Разрешаем фронту обращаться к API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(MonitorAPIMiddleware)

# API-роуты
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(bots.router, prefix="/api/bots", tags=["bots"])
app.include_router(commands.router, prefix="/api/commands", tags=["commands"])
app.include_router(bot_runner.router)
app.include_router(scenario.router)
app.include_router(templates.router)
app.include_router(analytics.router)
app.include_router(miniapps.router)
app.include_router(config.router)
app.include_router(config.health_router)
app.include_router(plugins.router)
app.include_router(projects.router)
app.include_router(deployment.router)
app.include_router(monitor.router)


class BroadcastNormalizeBody(BaseModel):
    html_content: str = ""


@app.post("/api/broadcast/normalize")
async def normalize_broadcast_html_global(body: BroadcastNormalizeBody):
    """Normalize HTML for Telegram preview/import (no bot required)."""
    return {"normalized_html": normalize_telegram_html(body.html_content)}


# Исходники плагинов (code.py.jinja2) — user plugins override bundled
from fastapi import HTTPException
from fastapi.responses import FileResponse


@app.get("/api/plugin-files/{plugin_id}/{filename:path}")
async def serve_plugin_file(plugin_id: str, filename: str):
    if Path(plugin_id).name != plugin_id or ".." in plugin_id or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid path")
    folder = resolve_plugin_folder(plugin_id)
    if folder is None:
        raise HTTPException(status_code=404, detail="Plugin not found")
    target = (folder / filename).resolve()
    try:
        target.relative_to(folder.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(target)


# Статика для frontend
FRONTEND_DIR = str(get_frontend_dir())
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
