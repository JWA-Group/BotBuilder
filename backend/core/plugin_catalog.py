"""Просмотр, обновление и удаление плагинов (встроенные — только чтение)."""

from __future__ import annotations

import json
import shutil
from typing import Any

from pydantic import BaseModel, Field, field_validator

from backend.core.app_paths import USER_PLUGINS_DIR, resolve_plugin_folder
from backend.core.plugin_manager import is_builtin_plugin
from backend.core.plugins import (
    CreateCustomPluginPayload,
    PluginFieldSchema,
    _validate_template_code,
    build_ui_json,
    generate_starter_template,
)


class UpdateCustomPluginPayload(BaseModel):
    name: str
    color: str = "#2563eb"
    icon: str = "🧩"
    fields: list[PluginFieldSchema] = Field(default_factory=list)
    template_code: str = ""

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        name = (value or "").strip()
        if not name:
            raise ValueError("Название компонента обязательно")
        if len(name) > 80:
            raise ValueError("Название не должно превышать 80 символов")
        return name


def _read_plugin_files(plugin_id: str) -> tuple[dict[str, Any], str]:
    folder = resolve_plugin_folder(plugin_id)
    if folder is None or not folder.is_dir():
        raise ValueError(f"Плагин не найден: {plugin_id}")
    ui_path = folder / "ui.json"
    if not ui_path.is_file():
        raise ValueError(f"У плагина {plugin_id!r} нет ui.json")
    with open(ui_path, "r", encoding="utf-8") as f:
        ui = json.load(f)
    code_path = folder / "code.py.jinja2"
    template_code = code_path.read_text(encoding="utf-8") if code_path.is_file() else ""
    return ui, template_code


def get_plugin_detail(plugin_id: str) -> dict[str, Any]:
    ui, template_code = _read_plugin_files(plugin_id)
    builtin = is_builtin_plugin(plugin_id)
    return {
        "pluginId": plugin_id,
        "type": ui.get("type") or plugin_id.replace("-", "_"),
        "name": ui.get("name") or plugin_id,
        "ui": ui,
        "fields": ui.get("fields") or [],
        "defaults": ui.get("defaults") or {},
        "template_code": template_code,
        "builtin": builtin,
        "editable": not builtin,
        "has_code": bool(template_code.strip()),
    }


def read_plugin_template_code(plugin_id: str) -> str:
    _, template_code = _read_plugin_files(plugin_id)
    return template_code


def update_custom_plugin(plugin_id: str, payload: UpdateCustomPluginPayload) -> dict[str, Any]:
    if is_builtin_plugin(plugin_id):
        raise ValueError("Встроенные плагины нельзя изменять")
    folder = USER_PLUGINS_DIR / plugin_id
    if not folder.is_dir():
        raise ValueError(f"Плагин не найден: {plugin_id}")

    create_payload = CreateCustomPluginPayload(
        plugin_id=plugin_id,
        name=payload.name,
        color=payload.color,
        icon=payload.icon,
        fields=payload.fields,
        template_code=payload.template_code,
    )
    code = (payload.template_code or "").strip() or generate_starter_template(create_payload)
    _validate_template_code(create_payload, code)

    ui = build_ui_json(create_payload)
    ui["custom"] = True

    ui_path = folder / "ui.json"
    code_path = folder / "code.py.jinja2"
    with open(ui_path, "w", encoding="utf-8") as f:
        json.dump(ui, f, ensure_ascii=False, indent=2)
        f.write("\n")
    with open(code_path, "w", encoding="utf-8") as f:
        f.write(code.rstrip() + "\n")

    from backend.core.plugin_manager import get_plugin_manager

    get_plugin_manager().reload()
    return {
        "ok": True,
        "pluginId": plugin_id,
        "type": ui["type"],
        "name": ui["name"],
        "pluginsReloaded": True,
    }


def delete_custom_plugin(plugin_id: str) -> dict[str, Any]:
    if is_builtin_plugin(plugin_id):
        raise ValueError("Встроенные плагины нельзя удалять")
    folder = USER_PLUGINS_DIR / plugin_id
    if not folder.is_dir():
        raise ValueError(f"Плагин не найден: {plugin_id}")
    shutil.rmtree(folder)
    from backend.core.plugin_manager import get_plugin_manager

    get_plugin_manager().reload()
    return {"ok": True, "pluginId": plugin_id, "deleted": True}
