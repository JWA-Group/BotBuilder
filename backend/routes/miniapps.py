from fastapi import APIRouter, Request, HTTPException, Depends, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
import os
import json
import sqlite3
import uuid
import re

from backend.db.database import get_db
from backend.models.bot import Bot
from backend.core.auth_deps import get_current_user_id_required
from backend.core.bot_access import require_bot_access

router = APIRouter(prefix="/api/miniapps", tags=["miniapps"])

from backend.core.app_paths import PROJECTS_DIR
UPLOADS_SUBDIR = "uploads"
ALLOWED_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}


async def _check_bot_owner(db: AsyncSession, bot_id: str, user_id: int) -> int:
    bot = await require_bot_access(db, bot_id, user_id)
    return bot.id


def _default_config() -> dict:
    """Конфиг по умолчанию для мини-приложения."""
    return {
        "title": "Личный кабинет",
        "fields": [
            {"id": "tg_user_id", "label": "ID пользователя", "enabled": True},
            {"id": "tg_user_name", "label": "Имя", "enabled": True},
            {"id": "tg_user_date", "label": "Дата регистрации", "enabled": True},
            {"id": "balance", "label": "Баланс", "enabled": True},
        ],
        "buttons": [
            {"text": "Открыть сайт", "url": "https://example.com"},
        ],
        "pages": [
            {
                "id": "home",
                "path": "/",
                "title": "Главная",
                "blocks": [
                    {
                        "id": "b1",
                        "type": "text",
                        "content": "Привет, {user_first_name}!",
                        "style": {"tag": "h1", "fontSize": 24, "fontWeight": "bold", "textAlign": "center", "color": "#111827"},
                    },
                    {
                        "id": "b2",
                        "type": "text",
                        "content": "Ваш баланс: {balance} ₽",
                        "style": {"tag": "p", "fontSize": 16, "color": "#6b7280"},
                    },
                    {
                        "id": "b3",
                        "type": "button",
                        "text": "Закрыть",
                        "action": {"type": "close"},
                        "style": {"variant": "primary", "size": "medium"},
                    },
                ],
            },
        ],
    }


def _load_config(bot_id: str) -> dict:
    path = os.path.join(PROJECTS_DIR, f"bot_{bot_id}", "miniapp.json")
    if not os.path.exists(path):
        return _default_config()
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return _default_config()


@router.get("/uploads/{bot_id}/{filename:path}")
async def serve_miniapp_upload(bot_id: str, filename: str):
    """Раздача загруженных файлов (публично по URL)."""
    try:
        bid = int(bot_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Некорректный bot_id")
    if ".." in filename or "/" in filename.replace("\\", "/").lstrip("/"):
        raise HTTPException(status_code=400, detail="Недопустимое имя файла")
    path = os.path.join(PROJECTS_DIR, f"bot_{bid}", UPLOADS_SUBDIR, filename)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Файл не найден")
    from fastapi.responses import FileResponse
    return FileResponse(path)


@router.get("/{bot_id}")
async def get_miniapp_config(
    bot_id: str,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    await _check_bot_owner(db, bot_id, user_id)
    return _load_config(bot_id)


@router.post("/save/{bot_id}")
async def save_miniapp_config(
    bot_id: str,
    request: Request,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    await _check_bot_owner(db, bot_id, user_id)
    data = await request.json()
    path = os.path.join(PROJECTS_DIR, f"bot_{bot_id}", "miniapp.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при сохранении конфигурации: {e}")
    return {"status": "ok"}


@router.get("/public/{bot_id}")
async def get_public_miniapp_config(bot_id: str):
    """Публичный доступ к конфигу мини-приложения (для WebApp в Telegram)."""
    return _load_config(bot_id)


@router.get("/public/{bot_id}/user/{user_id}")
async def get_public_user_data(bot_id: str, user_id: int):
    """Публичный доступ к данным пользователя конкретного бота (для WebApp)."""
    try:
        bid = int(bot_id)
        uid = int(user_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Некорректный bot_id или user_id")
    db_path = os.path.join(PROJECTS_DIR, f"bot_{bid}", "user_data.db")
    if not os.path.exists(db_path):
        return {}
    try:
        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT field, value FROM user_data WHERE user_id = ?",
            (uid,),
        ).fetchall()
        conn.close()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка чтения БД: {e}")
    return {r[0]: r[1] for r in rows}


def _get_fields_from_db(bot_id: str) -> list:
    """Список полей из user_data.db для бота."""
    db_path = os.path.join(PROJECTS_DIR, f"bot_{bot_id}", "user_data.db")
    if not os.path.exists(db_path):
        return []
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.execute("SELECT DISTINCT field FROM user_data ORDER BY field")
        out = [r[0] for r in cur.fetchall()]
        conn.close()
        return out
    except Exception:
        return []


@router.get("/{bot_id}/fields")
async def get_miniapp_fields(
    bot_id: str,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    """Список полей данных пользователя: из config.fields и из user_data.db."""
    await _check_bot_owner(db, bot_id, user_id)
    cfg = _load_config(bot_id)
    ids_from_config = []
    for f in (cfg.get("fields") or []):
        fid = f.get("id") if isinstance(f, dict) else f
        if fid:
            ids_from_config.append(str(fid))
    from_db = _get_fields_from_db(bot_id)
    seen = set(ids_from_config)
    for name in from_db:
        if name not in seen:
            seen.add(name)
            ids_from_config.append(name)
    return {"fields": ids_from_config}


@router.post("/upload/{bot_id}")
async def upload_miniapp_asset(
    bot_id: str,
    file: UploadFile = File(...),
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    """Загрузка изображения для мини-приложения. Возвращает URL для подстановки в src."""
    bid = await _check_bot_owner(db, bot_id, user_id)
    upload_dir = os.path.join(PROJECTS_DIR, f"bot_{bid}", UPLOADS_SUBDIR)
    os.makedirs(upload_dir, exist_ok=True)
    fn = (file.filename or "image").strip() or "image"
    ext = os.path.splitext(fn)[1].lower()
    if ext not in ALLOWED_IMAGE_EXT:
        ext = ".png"
    safe_name = re.sub(r"[^\w\-.]", "_", os.path.basename(fn))
    if not safe_name.endswith(ext):
        safe_name = (safe_name or "image") + ext
    unique = str(uuid.uuid4())[:8] + "_" + safe_name
    path = os.path.join(upload_dir, unique)
    try:
        content = await file.read()
        if len(content) > 10 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Файл не более 10 МБ")
        with open(path, "wb") as f:
            f.write(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка сохранения: {e}")
    url = f"/api/miniapps/uploads/{bot_id}/{unique}"
    return {"url": url}


