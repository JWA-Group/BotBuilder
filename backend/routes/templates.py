import os
import json
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from backend.db.database import get_db
from backend.models.bot import Bot
from backend.models.template import Template
from backend.schemas.template import TemplateCreate, TemplateOut
from backend.core.auth_deps import get_current_user_id_required
from backend.core.scenario_deps import normalize_scenario_document
from backend.core.bot_access import require_bot_access
from backend.core.plugin_manager import get_plugin_manager
from backend.core import templates as template_bundles

router = APIRouter(prefix="/api/templates", tags=["templates"])

from backend.core.app_paths import PROJECTS_DIR


class TemplateExportBody(BaseModel):
    name: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    scenario: dict = Field(default_factory=dict)
    preview_image_base64: str = ""
    platform: str = "telegram"


class TemplateImportBody(BaseModel):
    template_id: str
    bot_id: int
    source: str = "local"


@router.get("/local")
async def list_local_template_bundles():
    """Scan /templates/local and return all user-exported template packages."""
    template_bundles.ensure_templates_dirs()
    return {"templates": template_bundles.list_local_templates(get_plugin_manager())}


@router.get("/marketplace")
async def list_marketplace_templates():
    """Curated marketplace cards (mock metadata + installable catalog bundles)."""
    mgr = get_plugin_manager()
    return {
        "templates": template_bundles.list_marketplace_templates(mgr),
        "catalog": template_bundles.list_catalog_templates(mgr),
    }


@router.get("/bundle/{template_id}")
async def get_template_bundle_detail(template_id: str, source: str = "local"):
    """Full template detail for preview modal."""
    try:
        return template_bundles.get_template_detail(template_id, source, get_plugin_manager())
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Шаблон не найден")


@router.get("/preview/{template_id}")
async def get_template_preview_image(template_id: str):
    """Serve stored preview PNG for a local/catalog template."""
    data_url = template_bundles.get_preview_image_base64(template_id)
    if not data_url:
        raise HTTPException(status_code=404, detail="Preview not found")
    if data_url.startswith("data:"):
        header, _, payload = data_url.partition(",")
        mime = "image/png"
        if ";" in header:
            mime = header.split(":")[1].split(";")[0] if ":" in header else mime
        try:
            raw = payload.encode("utf-8")
            if "base64" in header:
                import base64

                raw = base64.b64decode(payload)
            return Response(content=raw, media_type=mime)
        except Exception:
            raise HTTPException(status_code=404, detail="Invalid preview data")
    raise HTTPException(status_code=404, detail="Preview not found")


@router.post("/export")
async def export_template_bundle(body: TemplateExportBody):
    """Package scenario + metadata + preview into /templates/local."""
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="Укажите название шаблона")
    try:
        result = template_bundles.export_template_bundle(
            name=body.name,
            description=body.description,
            tags=body.tags,
            scenario=body.scenario,
            preview_image_base64=body.preview_image_base64,
            platform=body.platform,
        )
        return {"status": "ok", "template": result}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Не удалось сохранить шаблон: {exc}")


@router.post("/import")
async def import_template_bundle(
    body: TemplateImportBody,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    """Unpack template bundle and apply to bot workspace (phantom check included)."""
    await require_bot_access(db, body.bot_id, user_id)
    source = body.source if body.source in ("local", "catalog", "marketplace") else "local"
    if source == "marketplace":
        source = "catalog"
    try:
        result = template_bundles.import_template_to_bot(
            bot_id=body.bot_id,
            template_id=body.template_id,
            source=source,
            plugin_manager=get_plugin_manager(),
        )
        return result
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Файл шаблона не найден")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Ошибка импорта: {exc}")


@router.delete("/local/{template_id}")
async def delete_local_template_bundle(template_id: str):
    if not template_bundles.delete_local_template(template_id):
        raise HTTPException(status_code=404, detail="Шаблон не найден")
    return {"status": "ok"}


@router.get("/download/{template_id}")
async def download_template_bundle(template_id: str, source: str = "local"):
    """Скачать файл шаблона (.bbpack.json)."""
    src = source if source in ("local", "catalog") else "local"
    try:
        path = template_bundles.resolve_bundle_path(template_id, src)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Шаблон не найден")
    filename = os.path.basename(path)
    return FileResponse(path, media_type="application/json", filename=filename)


@router.post("/upload")
async def upload_template_bundle_file(request: Request):
    """Импортировать файл шаблона (.bbpack.json) в локальную библиотеку."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Ожидается JSON-файл шаблона")
    try:
        result = template_bundles.save_uploaded_bundle(body if isinstance(body, dict) else {})
        return {"status": "ok", "template": result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Не удалось импортировать: {exc}")


@router.post("", response_model=TemplateOut)
async def create_template(
    body: TemplateCreate,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    """Создать шаблон из сценария бота. Бот должен принадлежать пользователю."""
    result = await db.execute(select(Bot).where(Bot.id == body.bot_id, Bot.user_id == user_id))
    bot = result.scalar_one_or_none()
    if not bot:
        raise HTTPException(status_code=403, detail="Бот не найден или нет доступа")

    path = os.path.join(PROJECTS_DIR, f"bot_{body.bot_id}", "scenario.json")
    scenario_data = None
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            try:
                raw = json.load(f)
                scenario_data = json.dumps(
                    normalize_scenario_document(raw if isinstance(raw, dict) else {}),
                    ensure_ascii=False,
                    indent=2,
                )
            except json.JSONDecodeError:
                scenario_data = f.read()

    template = Template(
        user_id=user_id,
        bot_id=body.bot_id,
        name=body.name,
        is_private=body.is_private,
        scenario_data=scenario_data,
    )
    db.add(template)
    try:
        await db.commit()
        await db.refresh(template)
        return template
    except Exception as e:
        await db.rollback()
        err_msg = str(e).lower()
        if "no such table" in err_msg or "templates" in err_msg:
            raise HTTPException(
                status_code=500,
                detail="Таблица templates не создана. Выполните в корне проекта: python -m backend.init_db",
            )
        raise HTTPException(status_code=500, detail=f"Ошибка БД: {str(e)}")


@router.get("/my", response_model=list[TemplateOut])
async def list_my_templates(
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    """Список шаблонов текущего пользователя."""
    result = await db.execute(select(Template).where(Template.user_id == user_id).order_by(Template.created_at.desc()))
    return result.scalars().all()


@router.get("/{template_id}")
async def get_template_for_edit(
    template_id: int,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    """Получить шаблон для редактирования (blocks, connections, tags из scenario_data)."""
    result = await db.execute(select(Template).where(Template.id == template_id, Template.user_id == user_id))
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Шаблон не найден")
    data = {"id": template.id, "name": template.name, "bot_id": template.bot_id, "is_private": template.is_private}
    if template.scenario_data:
        try:
            scenario = normalize_scenario_document(json.loads(template.scenario_data))
            data["blocks"] = scenario.get("blocks", [])
            data["connections"] = scenario.get("connections", [])
            data["tags"] = scenario.get("tags", [])
            data["required_plugins"] = scenario.get("required_plugins", [])
            if scenario.get("template_name"):
                data["template_name"] = scenario["template_name"]
        except (json.JSONDecodeError, TypeError):
            data["blocks"] = []
            data["connections"] = []
            data["tags"] = []
            data["required_plugins"] = []
    else:
        data["blocks"] = []
        data["connections"] = []
        data["tags"] = []
        data["required_plugins"] = []
    return data


@router.put("/{template_id}")
async def update_template(
    template_id: int,
    request: Request,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    """Обновить сценарий шаблона (blocks, connections, tags)."""
    result = await db.execute(select(Template).where(Template.id == template_id, Template.user_id == user_id))
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Шаблон не найден")
    body = await request.json()
    scenario_data = json.dumps(
        normalize_scenario_document(body if isinstance(body, dict) else {}),
        ensure_ascii=False,
        indent=2,
    )
    template.scenario_data = scenario_data
    await db.commit()
    await db.refresh(template)
    return {"status": "ok"}


@router.delete("/{template_id}")
async def delete_template(
    template_id: int,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    """Удалить шаблон. Только владелец."""
    result = await db.execute(select(Template).where(Template.id == template_id, Template.user_id == user_id))
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Шаблон не найден")
    await db.delete(template)
    await db.commit()
    return {"status": "ok"}
