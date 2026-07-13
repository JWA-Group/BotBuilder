from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from ..db.database import get_db
from ..models.bot import Bot
from ..models.user import User
from ..models.template import Template
from ..schemas.bot import BotCreate, BotOut
from ..services.bot_service import create_bot_project
from ..utils.vk_default_scenario import vk_default_scenario
from ..core.auth_deps import get_current_user_id_required, DEFAULT_USER_ID
from ..core.bot_access import is_desktop_app, require_bot_access
from fastapi.responses import JSONResponse
import os
import json
from backend.utils.generate_main import generate_main_py, generate_main_from_scenario, get_bot_platform
from backend.core.scenario_deps import PhantomNodeError, normalize_scenario_document

router = APIRouter()
from backend.core.app_paths import PROJECTS_DIR

@router.post("/create", response_model=BotOut)
async def create_bot(bot: BotCreate, db: AsyncSession = Depends(get_db)):
    from backend.core.auth_deps import DEFAULT_USER_ID

    if not bot.user_id:
        bot.user_id = DEFAULT_USER_ID
    result = await db.execute(select(User).where(User.id == bot.user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Локальный пользователь не найден. Перезапустите приложение.")

    new_bot = Bot(
        name=bot.name,
        api_token=bot.api_token,
        user_id=bot.user_id,
        platform=bot.platform,
    )
    db.add(new_bot)
    await db.commit()
    await db.refresh(new_bot)

    create_bot_project(new_bot.id, bot.name, bot.api_token, platform=bot.platform)
    try:
        from backend.core.monitor import log_api

        log_api(f"Создан бот #{new_bot.id} «{new_bot.name}» ({new_bot.platform})")
    except Exception:
        pass
    return new_bot

@router.get("/my", response_model=list[BotOut])
async def get_user_bots(user_id: int, db: AsyncSession = Depends(get_db)):
    if is_desktop_app():
        result = await db.execute(select(Bot))
    else:
        result = await db.execute(select(Bot).where(Bot.user_id == user_id))
    return result.scalars().all()

@router.get("/config/{bot_id}")
async def get_bot_config(bot_id: int):
    config_path = os.path.join(PROJECTS_DIR, f"bot_{bot_id}", "config.json")
    if not os.path.exists(config_path):
        raise HTTPException(status_code=404, detail="config.json не найден")
    with open(config_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return JSONResponse(content=data)

@router.post("/config/{bot_id}")
async def update_bot_config(bot_id: int, updated_config: dict):
    config_path = os.path.join(PROJECTS_DIR, f"bot_{bot_id}", "config.json")
    if not os.path.exists(config_path):
        raise HTTPException(status_code=404, detail="config.json не найден")
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(updated_config, f, indent=2, ensure_ascii=False)
    return {"status": "ok"}

@router.get("/handlers/{bot_id}")
async def get_bot_handlers(bot_id: int, user_id: int = Depends(get_current_user_id_required), db: AsyncSession = Depends(get_db)):
    await require_bot_access(db, bot_id, user_id)
    path = os.path.join(PROJECTS_DIR, f"bot_{bot_id}", "handlers.json")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="handlers.json не найден")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


@router.get("/keyboard/{bot_id}")
async def get_keyboard(bot_id: int):
    path = os.path.join(PROJECTS_DIR, f"bot_{bot_id}", "keyboard.json")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="keyboard.json не найден")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

@router.post("/keyboard/{bot_id}")
async def update_keyboard(bot_id: int, data: dict):
    path = os.path.join(PROJECTS_DIR, f"bot_{bot_id}", "keyboard.json")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="keyboard.json не найден")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return {"status": "ok"}


@router.post("/apply-template/{bot_id}")
async def apply_template_to_bot(
    bot_id: int,
    request: Request,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    """Применить сценарий шаблона к боту. Бот и шаблон должны принадлежать пользователю."""
    await require_bot_access(db, bot_id, user_id)
    body = await request.json()
    template_id = body.get("template_id")
    if not template_id:
        raise HTTPException(status_code=400, detail="Укажите template_id")
    t_result = await db.execute(select(Template).where(Template.id == template_id, Template.user_id == user_id))
    template = t_result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Шаблон не найден")
    scenario_data = template.scenario_data
    if not scenario_data:
        normalized = normalize_scenario_document({})
        scenario_data = json.dumps(normalized, ensure_ascii=False, indent=2)
    elif isinstance(scenario_data, str):
        try:
            normalized = normalize_scenario_document(json.loads(scenario_data))
            scenario_data = json.dumps(normalized, ensure_ascii=False, indent=2)
        except json.JSONDecodeError:
            pass
    else:
        normalized = normalize_scenario_document(scenario_data if isinstance(scenario_data, dict) else {})
        scenario_data = json.dumps(normalized, ensure_ascii=False, indent=2)
    path = os.path.join(PROJECTS_DIR, f"bot_{bot_id}", "scenario.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(scenario_data)
    compile_warning = None
    try:
        generate_main_from_scenario(bot_id, platform=get_bot_platform(bot_id))
    except PhantomNodeError as exc:
        compile_warning = str(exc)
    except ValueError as exc:
        if "Compilation locked" in str(exc):
            compile_warning = str(exc)
    return {
        "status": "ok",
        "message": "Шаблон применён к боту",
        "compilation_warning": compile_warning,
    }


@router.post("/reset-vk-template/{bot_id}")
async def reset_vk_template(
    bot_id: int,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    """Подставить стандартный VK-сценарий (приветствие + меню) и пересобрать main.py."""
    bot = await require_bot_access(db, bot_id, user_id)
    if (bot.platform or "telegram") != "vk":
        raise HTTPException(status_code=400, detail="Шаблон только для ботов ВКонтакте")
    path = os.path.join(PROJECTS_DIR, f"bot_{bot_id}", "scenario.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(vk_default_scenario(), f, ensure_ascii=False, indent=2)
    generate_main_from_scenario(bot_id, platform="vk")
    return {"status": "ok", "message": "Шаблон VK применён. Остановите и снова запустите бота."}


@router.delete("/{bot_id}")
async def delete_bot(bot_id: int, user_id: int, db: AsyncSession = Depends(get_db)):
    bot = await require_bot_access(db, bot_id, user_id)
    await db.delete(bot)
    await db.commit()

    project_path = os.path.join(PROJECTS_DIR, f"bot_{bot_id}")
    if os.path.exists(project_path):
        import shutil
        shutil.rmtree(project_path)

    return {"status": "deleted"}

@router.get("/inline/{bot_id}")
async def get_inline_keyboard(bot_id: int):
    path = os.path.join(PROJECTS_DIR, f"bot_{bot_id}", "keyboard.json")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="keyboard.json не найден")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    return {"inline": data.get("inline", [])}


@router.post("/inline/{bot_id}")
async def update_inline_keyboard(bot_id: int, inline_data: dict):
    path = os.path.join(PROJECTS_DIR, f"bot_{bot_id}", "keyboard.json")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="keyboard.json не найден")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    data["inline"] = inline_data.get("inline", [])

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    return {"status": "ok"}

MAX_FILE_SIZE = 32 * 1024 * 1024  # 32 MB
MAX_FILES = 10
ALLOWED_IMAGE = {"image/jpeg", "image/png", "image/gif", "image/webp"}
ALLOWED_VIDEO = {"video/mp4", "video/quicktime", "video/x-msvideo"}
ALLOWED_AUDIO = {"audio/mpeg", "audio/ogg", "audio/wav", "audio/mp4", "audio/x-m4a"}
ALLOWED_DOCS = {"application/pdf", "application/msword", "application/vnd.openxmlformats-officedocument.*"}


@router.post("/upload/{bot_id}")
async def upload_media(
    bot_id: int,
    file: UploadFile = File(...),
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    """Загрузка медиа-файла для бота. Сохраняется в projects/bot_{id}/media/"""
    await require_bot_access(db, bot_id, user_id)
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail=f"Файл более {MAX_FILE_SIZE // (1024*1024)} МБ")
    media_dir = os.path.join(PROJECTS_DIR, f"bot_{bot_id}", "media")
    os.makedirs(media_dir, exist_ok=True)
    safe_name = "".join(c for c in (file.filename or "file") if c.isalnum() or c in "._-") or "file"
    base, ext = os.path.splitext(safe_name)
    if not ext:
        ext = ".bin"
    path = os.path.join(media_dir, f"{base}_{len(content)}{ext}")
    n = 0
    while os.path.exists(path):
        n += 1
        path = os.path.join(media_dir, f"{base}_{len(content)}_{n}{ext}")
    with open(path, "wb") as f:
        f.write(content)
    rel = f"media/{os.path.basename(path)}"
    return {"path": rel, "filename": os.path.basename(path)}


@router.get("/fsm/{bot_id}")
async def get_fsm(bot_id: int):
    path = os.path.join(PROJECTS_DIR, f"bot_{bot_id}", "fsm.json")
    if not os.path.exists(path):
        return {"states": []}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


@router.post("/fsm/{bot_id}")
async def save_fsm(bot_id: int, fsm_data: dict):
    path = os.path.join(PROJECTS_DIR, f"bot_{bot_id}", "fsm.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(fsm_data, f, ensure_ascii=False, indent=2)
    return {"status": "ok"}
