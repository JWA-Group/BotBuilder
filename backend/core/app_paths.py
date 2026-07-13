"""
Central filesystem layout for BotBuilder.

Writable user data never lives inside the install / repo root when
BOTBUILDER_DATA_DIR is set (Electron always sets it to app.getPath('userData')/data).

Layout under DATA_DIR:
  projects/     — generated bots (bot_{id}/)
  plugins/      — user-created custom blocks
  databases/    — app metadata SQLite (db.sqlite3)
  templates/local/ — user-saved template packs
  logs/         — optional app logs

Read-only app assets under APP_ROOT:
  plugins/           — bundled block definitions
  templates/catalog/ — shipped catalog packs
  frontend/          — SPA static files
  python_embed/      — interpreter for customer bot processes
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _default_app_root() -> Path:
    if getattr(sys, "frozen", False):
        # PyInstaller onedir: exe sits next to _internal; app assets are sibling "app"
        # when launched by Electron. Prefer env; else parent of exe.
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def get_app_root() -> Path:
    raw = (os.environ.get("BOTBUILDER_APP_ROOT") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return _default_app_root().resolve()


def get_data_dir() -> Path:
    raw = (os.environ.get("BOTBUILDER_DATA_DIR") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    # Dev / bare uvicorn: keep data next to the repo (legacy behaviour)
    return get_app_root()


def get_projects_dir() -> Path:
    return get_data_dir() / "projects"


def get_user_plugins_dir() -> Path:
    return get_data_dir() / "plugins"


def get_bundled_plugins_dir() -> Path:
    return get_app_root() / "plugins"


def get_databases_dir() -> Path:
    return get_data_dir() / "databases"


def get_app_db_path() -> Path:
    return get_databases_dir() / "db.sqlite3"


def get_templates_dir() -> Path:
    """Parent of local/ + catalog/. Local is under data; catalog under app root."""
    return get_data_dir() / "templates"


def get_local_templates_dir() -> Path:
    return get_templates_dir() / "local"


def get_catalog_templates_dir() -> Path:
    bundled = get_app_root() / "templates" / "catalog"
    if bundled.is_dir():
        return bundled
    # Dev fallback if catalog still only under data/templates
    return get_templates_dir() / "catalog"


def get_logs_dir() -> Path:
    return get_data_dir() / "logs"


def get_frontend_dir() -> Path:
    return get_app_root() / "frontend"


def get_python_embed_dir() -> Path:
    return get_app_root() / "python_embed"


def plugin_search_dirs() -> list[Path]:
    """User plugins first (override), then bundled."""
    dirs: list[Path] = []
    user = get_user_plugins_dir()
    bundled = get_bundled_plugins_dir()
    if user.is_dir():
        dirs.append(user)
    if bundled.is_dir() and bundled.resolve() != user.resolve():
        dirs.append(bundled)
    return dirs


def resolve_plugin_folder(plugin_id: str) -> Path | None:
    safe = Path(plugin_id).name
    if safe != plugin_id or ".." in plugin_id:
        return None
    for base in plugin_search_dirs():
        folder = base / safe
        if folder.is_dir():
            return folder
    return None


def ensure_data_dirs() -> Path:
    """Create blank user-data folders if missing. Returns DATA_DIR."""
    data = get_data_dir()
    for path in (
        data,
        get_projects_dir(),
        get_user_plugins_dir(),
        get_databases_dir(),
        get_local_templates_dir(),
        get_logs_dir(),
    ):
        path.mkdir(parents=True, exist_ok=True)
    return data


# Convenience aliases (resolved at import — call ensure_data_dirs() at process start)
APP_ROOT = get_app_root()
DATA_DIR = get_data_dir()
PROJECTS_DIR = get_projects_dir()
USER_PLUGINS_DIR = get_user_plugins_dir()
BUNDLED_PLUGINS_DIR = get_bundled_plugins_dir()
PLUGINS_DIR = BUNDLED_PLUGINS_DIR  # backward-compatible name = bundled
DATABASES_DIR = get_databases_dir()
APP_DB_PATH = get_app_db_path()
LOCAL_TEMPLATES_DIR = get_local_templates_dir()
CATALOG_TEMPLATES_DIR = get_catalog_templates_dir()
FRONTEND_DIR = get_frontend_dir()
