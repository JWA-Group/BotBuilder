"""Template bundle storage, export/import, and dependency checks."""

from __future__ import annotations

import base64
import json
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from backend.core.plugin_manager import PluginManager, get_plugin_manager
from backend.core.scenario_deps import PhantomNodeError, find_phantom_types, normalize_scenario_document
from backend.utils.generate_main import generate_main_from_scenario, get_bot_platform
from backend.core import app_paths

FORMAT_VERSION = 1
BUNDLE_EXT = ".bbpack.json"

ensure_data_dirs = app_paths.ensure_data_dirs
TEMPLATES_DIR = str(app_paths.get_templates_dir())
LOCAL_TEMPLATES_DIR = str(app_paths.get_local_templates_dir())
CATALOG_TEMPLATES_DIR = str(app_paths.get_catalog_templates_dir())
PROJECTS_DIR = str(app_paths.get_projects_dir())

_SAFE_ID = re.compile(r"[^a-zA-Z0-9._-]+")

MARKETPLACE_MOCK: list[dict[str, Any]] = [
    {
        "id": "market-ai-assistant",
        "source": "marketplace",
        "name": "AI Assistant Pro",
        "description": "Многошаговый бот с меню, сбором данных и интеграцией Perplexity для ответов на вопросы пользователей.",
        "tags": ["AI", "FAQ"],
        "required_plugins": ["start", "message", "menu", "data", "condition"],
        "platform": "telegram",
        "author": "BotBuilder Team",
        "rating": 4.8,
        "installs": 1240,
        "setup_steps": [
            "Выберите бота и нажмите «Установить шаблон»",
            "Укажите API-ключ Perplexity в блоке ИИ",
            "Сохраните сценарий и запустите бота",
        ],
        "preview_image_base64": "",
    },
    {
        "id": "market-ecom-store",
        "source": "marketplace",
        "name": "E-commerce Storefront",
        "description": "Каталог товаров с inline-кнопками, корзиной и уведомлением менеджера о заказе.",
        "tags": ["E-commerce", "Sales"],
        "required_plugins": ["start", "message", "menu", "data"],
        "platform": "telegram",
        "author": "Commerce Labs",
        "rating": 4.6,
        "installs": 890,
        "setup_steps": [
            "Импортируйте шаблон в существующего бота",
            "Заполните тексты товаров в блоках сообщений",
            "Настройте webhook или long polling",
        ],
        "preview_image_base64": "",
    },
    {
        "id": "market-faq-desk",
        "source": "marketplace",
        "name": "FAQ Help Desk",
        "description": "Быстрый FAQ-бот: приветствие, частые вопросы, эскалация к оператору по команде /help.",
        "tags": ["FAQ", "Support"],
        "required_plugins": ["start", "message", "command", "menu"],
        "platform": "telegram",
        "author": "SupportKit",
        "rating": 4.9,
        "installs": 2100,
        "setup_steps": [
            "Установите шаблон на бота",
            "Отредактируйте тексты ответов в редакторе",
            "Опубликуйте бота в Telegram",
        ],
        "preview_image_base64": "",
    },
]


def ensure_templates_dirs() -> None:
    ensure_data_dirs()
    os.makedirs(LOCAL_TEMPLATES_DIR, exist_ok=True)
    # Catalog is read-only when shipped under APP_ROOT; only create if missing in data fallback
    if not os.path.isdir(CATALOG_TEMPLATES_DIR):
        try:
            os.makedirs(CATALOG_TEMPLATES_DIR, exist_ok=True)
        except OSError:
            pass


def slugify_template_id(name: str) -> str:
    base = _SAFE_ID.sub("-", (name or "template").strip().lower()).strip("-") or "template"
    return base[:48]


def bundle_path(directory: str, template_id: str) -> str:
    safe = _SAFE_ID.sub("-", template_id).strip("-") or "template"
    return os.path.join(directory, f"{safe}{BUNDLE_EXT}")


def _read_bundle_file(path: str) -> dict[str, Any] | None:
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            return None
        return raw
    except (json.JSONDecodeError, OSError):
        return None


def _preview_url_for_file(path: str, template_id: str) -> str:
    bundle = _read_bundle_file(path)
    if bundle and bundle.get("preview_image_base64"):
        return f"/api/templates/preview/{template_id}"
    return ""


def _summary_from_bundle(
    bundle: dict[str, Any],
    *,
    template_id: str,
    source: str,
    file_path: str | None = None,
    plugin_manager: PluginManager | None = None,
    include_scenario: bool = False,
) -> dict[str, Any]:
    mgr = plugin_manager or get_plugin_manager()
    manifest = bundle.get("manifest") if isinstance(bundle.get("manifest"), dict) else {}
    scenario_raw = bundle.get("scenario") if isinstance(bundle.get("scenario"), dict) else {}
    scenario = normalize_scenario_document(scenario_raw)
    required = manifest.get("required_plugins") or scenario.get("required_plugins") or []
    if not isinstance(required, list):
        required = []
    required = sorted({str(x) for x in required if x})
    missing = find_phantom_types(scenario, mgr)

    created = manifest.get("created_at") or ""
    if not created and file_path:
        try:
            created = datetime.fromtimestamp(os.path.getmtime(file_path), tz=timezone.utc).isoformat()
        except OSError:
            created = ""

    summary: dict[str, Any] = {
        "id": template_id,
        "source": source,
        "name": str(manifest.get("name") or template_id),
        "description": str(manifest.get("description") or ""),
        "tags": manifest.get("tags") if isinstance(manifest.get("tags"), list) else [],
        "required_plugins": required,
        "missing_plugins": missing,
        "has_missing_plugins": bool(missing),
        "platform": str(manifest.get("platform") or "telegram"),
        "author": str(manifest.get("author") or "Local"),
        "created_at": created,
        "setup_steps": manifest.get("setup_steps") if isinstance(manifest.get("setup_steps"), list) else [],
        "preview_url": _preview_url_for_file(file_path, template_id) if file_path else "",
        "block_count": len(scenario.get("blocks") or []),
        "connection_count": len(scenario.get("connections") or []),
    }
    if include_scenario:
        summary["scenario"] = scenario
    return summary


def list_local_templates(plugin_manager: PluginManager | None = None) -> list[dict[str, Any]]:
    ensure_templates_dirs()
    mgr = plugin_manager or get_plugin_manager()
    items: list[dict[str, Any]] = []
    for fname in sorted(os.listdir(LOCAL_TEMPLATES_DIR)):
        if not fname.endswith(BUNDLE_EXT):
            continue
        path = os.path.join(LOCAL_TEMPLATES_DIR, fname)
        bundle = _read_bundle_file(path)
        if not bundle:
            continue
        template_id = fname[: -len(BUNDLE_EXT)]
        items.append(
            _summary_from_bundle(
                bundle,
                template_id=template_id,
                source="local",
                file_path=path,
                plugin_manager=mgr,
                include_scenario=True,
            )
        )
    items.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return items


def list_catalog_templates(plugin_manager: PluginManager | None = None) -> list[dict[str, Any]]:
    ensure_templates_dirs()
    mgr = plugin_manager or get_plugin_manager()
    items: list[dict[str, Any]] = []
    if not os.path.isdir(CATALOG_TEMPLATES_DIR):
        return items
    for fname in sorted(os.listdir(CATALOG_TEMPLATES_DIR)):
        if not fname.endswith(BUNDLE_EXT):
            continue
        path = os.path.join(CATALOG_TEMPLATES_DIR, fname)
        bundle = _read_bundle_file(path)
        if not bundle:
            continue
        template_id = fname[: -len(BUNDLE_EXT)]
        items.append(
            _summary_from_bundle(
                bundle,
                template_id=template_id,
                source="catalog",
                file_path=path,
                plugin_manager=mgr,
                include_scenario=True,
            )
        )
    return items


def list_marketplace_templates(plugin_manager: PluginManager | None = None) -> list[dict[str, Any]]:
    mgr = plugin_manager or get_plugin_manager()
    catalog_by_id = {item["id"]: item for item in list_catalog_templates(mgr)}
    items: list[dict[str, Any]] = []
    for mock in MARKETPLACE_MOCK:
        entry = dict(mock)
        catalog = catalog_by_id.get(entry["id"])
        if catalog:
            entry.update(
                {
                    k: catalog[k]
                    for k in (
                        "preview_url",
                        "block_count",
                        "connection_count",
                        "missing_plugins",
                        "has_missing_plugins",
                        "scenario",
                    )
                    if k in catalog
                }
            )
            entry["installable"] = True
        else:
            required = entry.get("required_plugins") or []
            scenario = normalize_scenario_document({"blocks": [{"type": t} for t in required], "connections": []})
            missing = find_phantom_types(scenario, mgr)
            entry["missing_plugins"] = missing
            entry["has_missing_plugins"] = bool(missing)
            entry["installable"] = False
            entry["preview_url"] = ""
            entry["block_count"] = len(required)
            entry["connection_count"] = 0
        items.append(entry)
    return items


def load_template_bundle(template_id: str, source: str = "local") -> dict[str, Any]:
    ensure_templates_dirs()
    safe_id = _SAFE_ID.sub("-", template_id).strip("-")
    if not safe_id:
        raise FileNotFoundError("Invalid template id")

    directories = {
        "local": LOCAL_TEMPLATES_DIR,
        "catalog": CATALOG_TEMPLATES_DIR,
    }
    directory = directories.get(source)
    if not directory:
        raise FileNotFoundError(f"Unknown template source: {source}")

    path = bundle_path(directory, safe_id)
    bundle = _read_bundle_file(path)
    if not bundle:
        raise FileNotFoundError(f"Template not found: {safe_id}")
    return bundle


def get_template_detail(template_id: str, source: str = "local", plugin_manager: PluginManager | None = None) -> dict[str, Any]:
    mgr = plugin_manager or get_plugin_manager()
    if source == "marketplace":
        for item in list_marketplace_templates(mgr):
            if item["id"] == template_id:
                detail = dict(item)
                try:
                    bundle = load_template_bundle(template_id, "catalog")
                    scenario = normalize_scenario_document(bundle.get("scenario") or {})
                    detail["scenario"] = scenario
                    detail["preview_image_base64"] = bundle.get("preview_image_base64") or ""
                except FileNotFoundError:
                    detail["scenario"] = normalize_scenario_document(
                        {
                            "blocks": [{"id": "start", "type": "start", "x": 50, "y": 100, "data": {}}],
                            "connections": [],
                        }
                    )
                return detail
        raise FileNotFoundError(template_id)

    bundle = load_template_bundle(template_id, source)
    path = bundle_path(
        LOCAL_TEMPLATES_DIR if source == "local" else CATALOG_TEMPLATES_DIR,
        _SAFE_ID.sub("-", template_id).strip("-"),
    )
    summary = _summary_from_bundle(
        bundle,
        template_id=template_id,
        source=source,
        file_path=path if os.path.isfile(path) else None,
        plugin_manager=mgr,
    )
    scenario = normalize_scenario_document(bundle.get("scenario") or {})
    summary["scenario"] = scenario
    summary["preview_image_base64"] = bundle.get("preview_image_base64") or ""
    return summary


def get_preview_image_base64(template_id: str) -> str:
    for source in ("local", "catalog"):
        try:
            bundle = load_template_bundle(template_id, source)
            return str(bundle.get("preview_image_base64") or "")
        except FileNotFoundError:
            continue
    return ""


def export_template_bundle(
    *,
    name: str,
    description: str = "",
    tags: list[str] | None = None,
    scenario: dict[str, Any],
    preview_image_base64: str = "",
    platform: str = "telegram",
    author: str = "You",
    setup_steps: list[str] | None = None,
) -> dict[str, Any]:
    ensure_templates_dirs()
    normalized = normalize_scenario_document(scenario)
    template_id = slugify_template_id(name)
    base_path = bundle_path(LOCAL_TEMPLATES_DIR, template_id)
    if os.path.exists(base_path):
        template_id = f"{template_id}-{uuid.uuid4().hex[:8]}"
        base_path = bundle_path(LOCAL_TEMPLATES_DIR, template_id)

    manifest = {
        "id": template_id,
        "name": name.strip() or template_id,
        "description": (description or "").strip(),
        "tags": [str(t).strip() for t in (tags or []) if str(t).strip()],
        "required_plugins": normalized.get("required_plugins") or [],
        "platform": platform or "telegram",
        "author": author,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "setup_steps": setup_steps
        or [
            "Откройте редактор сценария выбранного бота",
            "Проверьте тексты блоков и подключите недостающие плагины",
            "Сохраните и запустите бота",
        ],
    }

    bundle = {
        "format_version": FORMAT_VERSION,
        "manifest": manifest,
        "scenario": normalized,
        "preview_image_base64": preview_image_base64 or "",
    }

    with open(base_path, "w", encoding="utf-8") as f:
        json.dump(bundle, f, ensure_ascii=False, indent=2)

    summary = _summary_from_bundle(
        bundle,
        template_id=template_id,
        source="local",
        file_path=base_path,
    )
    summary["path"] = base_path
    return summary


def import_template_to_bot(
    *,
    bot_id: int,
    template_id: str,
    source: str = "local",
    plugin_manager: PluginManager | None = None,
) -> dict[str, Any]:
    mgr = plugin_manager or get_plugin_manager()
    bundle = load_template_bundle(template_id, source if source in ("local", "catalog") else "catalog")
    scenario = normalize_scenario_document(bundle.get("scenario") or {})
    missing = find_phantom_types(scenario, mgr)

    project_dir = os.path.join(PROJECTS_DIR, f"bot_{bot_id}")
    os.makedirs(project_dir, exist_ok=True)
    scenario_path = os.path.join(project_dir, "scenario.json")
    with open(scenario_path, "w", encoding="utf-8") as f:
        json.dump(scenario, f, ensure_ascii=False, indent=2)

    compile_warning = None
    try:
        generate_main_from_scenario(bot_id, platform=get_bot_platform(bot_id))
    except PhantomNodeError as exc:
        compile_warning = str(exc)
    except ValueError as exc:
        if "Compilation locked" in str(exc):
            compile_warning = str(exc)
        else:
            raise

    manifest = bundle.get("manifest") if isinstance(bundle.get("manifest"), dict) else {}
    return {
        "status": "ok",
        "bot_id": bot_id,
        "template_id": template_id,
        "template_name": manifest.get("name") or template_id,
        "required_plugins": scenario.get("required_plugins") or [],
        "missing_plugins": missing,
        "phantom_nodes_detected": bool(missing),
        "compilation_warning": compile_warning,
        "message": "Шаблон применён к проекту бота",
    }


def delete_local_template(template_id: str) -> bool:
    ensure_templates_dirs()
    safe_id = _SAFE_ID.sub("-", template_id).strip("-")
    path = bundle_path(LOCAL_TEMPLATES_DIR, safe_id)
    if not os.path.isfile(path):
        return False
    os.remove(path)
    return True


def resolve_bundle_path(template_id: str, source: str = "local") -> str:
    ensure_templates_dirs()
    safe_id = _SAFE_ID.sub("-", template_id).strip("-")
    if not safe_id:
        raise FileNotFoundError("Invalid template id")
    directories = {"local": LOCAL_TEMPLATES_DIR, "catalog": CATALOG_TEMPLATES_DIR}
    directory = directories.get(source)
    if not directory:
        raise FileNotFoundError(f"Unknown template source: {source}")
    path = bundle_path(directory, safe_id)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Template not found: {safe_id}")
    return path


def save_uploaded_bundle(raw: dict[str, Any]) -> dict[str, Any]:
    """Import .bbpack.json file into /templates/local."""
    ensure_templates_dirs()
    if not isinstance(raw, dict):
        raise ValueError("Некорректный формат файла шаблона")
    manifest = raw.get("manifest") if isinstance(raw.get("manifest"), dict) else {}
    name = str(manifest.get("name") or raw.get("template_name") or "imported-template")
    scenario = normalize_scenario_document(raw.get("scenario") or raw)
    preview = str(raw.get("preview_image_base64") or "")
    tags = manifest.get("tags") if isinstance(manifest.get("tags"), list) else []
    description = str(manifest.get("description") or "")
    platform = str(manifest.get("platform") or "telegram")
    return export_template_bundle(
        name=name,
        description=description,
        tags=tags,
        scenario=scenario,
        preview_image_base64=preview,
        platform=platform,
        author=str(manifest.get("author") or "Импорт"),
        setup_steps=manifest.get("setup_steps") if isinstance(manifest.get("setup_steps"), list) else None,
    )
