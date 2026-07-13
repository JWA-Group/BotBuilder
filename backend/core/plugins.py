"""Создание пользовательских плагинов, валидация и сохранение на диск."""



from __future__ import annotations



import json

import re

from typing import Any



from pydantic import BaseModel, Field, field_validator



from backend.core.app_paths import USER_PLUGINS_DIR, ensure_data_dirs, resolve_plugin_folder
from backend.core.plugin_manager import get_plugin_manager



PLUGIN_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")

RESERVED_PLUGIN_IDS = frozenset(

    {

        "start",

        "start_node",

        "command_node",

        "send_message",

        "message",

        "menu_node",

        "menu",

        "data_node",

        "data",

        "condition_node",

        "condition",

        "weather_node",

        "weather",

        "note_node",

        "note",

        "__pycache__",

    }

)

FIELD_KEY_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")

ALLOWED_FIELD_TYPES = frozenset({"text", "textarea", "select", "checkbox", "number"})





class PluginFieldSchema(BaseModel):

    key: str

    type: str

    label: str

    hint: str = ""

    placeholder: str = ""

    options: list[dict[str, str]] | None = None



    @field_validator("key")

    @classmethod

    def validate_key(cls, value: str) -> str:

        key = (value or "").strip()

        if not FIELD_KEY_RE.match(key):

            raise ValueError(

                "Ключ поля должен начинаться с буквы или _ и содержать только буквы, цифры и _"

            )

        return key



    @field_validator("type")

    @classmethod

    def validate_type(cls, value: str) -> str:

        field_type = (value or "").strip().lower()

        if field_type not in ALLOWED_FIELD_TYPES:

            raise ValueError(f"Неподдерживаемый тип поля: {field_type!r}")

        return field_type



    @field_validator("label")

    @classmethod

    def validate_label(cls, value: str) -> str:

        label = (value or "").strip()

        if not label:

            raise ValueError("Подпись поля обязательна")

        return label





class CreateCustomPluginPayload(BaseModel):

    plugin_id: str

    name: str

    color: str = "#2563eb"

    icon: str = "🧩"

    fields: list[PluginFieldSchema] = Field(default_factory=list)

    template_code: str = ""



    @field_validator("plugin_id")

    @classmethod

    def sanitize_plugin_id(cls, value: str) -> str:

        raw = (value or "").strip().lower()

        raw = re.sub(r"[\s]+", "_", raw)

        raw = re.sub(r"[^a-z0-9_-]", "", raw)

        if raw.endswith("_node"):

            raw = raw[: -len("_node")]

        if not raw:

            raise ValueError("ID плагина обязателен")

        if not PLUGIN_ID_RE.match(raw):

            raise ValueError(

                "ID плагина должен начинаться с буквы и содержать только строчные латинские буквы, цифры, _ или -"

            )

        if raw in RESERVED_PLUGIN_IDS:

            raise ValueError(f"ID плагина {raw!r} зарезервирован")

        return raw



    @field_validator("name")

    @classmethod

    def validate_name(cls, value: str) -> str:

        name = (value or "").strip()

        if not name:

            raise ValueError("Название компонента обязательно")

        if len(name) > 80:

            raise ValueError("Название не должно превышать 80 символов")

        return name



    @field_validator("color")

    @classmethod

    def validate_color(cls, value: str) -> str:

        color = (value or "").strip()

        if not HEX_COLOR_RE.match(color):

            raise ValueError("Цвет должен быть в формате hex, например #2563eb")

        return color.lower()



    @field_validator("icon")

    @classmethod

    def validate_icon(cls, value: str) -> str:

        icon = (value or "🧩").strip()

        return icon[:8] if icon else "🧩"



    @field_validator("fields")

    @classmethod

    def validate_unique_field_keys(cls, fields: list[PluginFieldSchema]) -> list[PluginFieldSchema]:

        seen: set[str] = set()

        for field in fields:

            if field.key in seen:

                raise ValueError(f"Дублирующийся ключ поля: {field.key!r}")

            seen.add(field.key)

        return fields





def _default_for_field(field: PluginFieldSchema) -> Any:

    if field.type == "checkbox":

        return False

    if field.type == "number":

        return 0

    if field.type == "select":

        if field.options:

            return field.options[0].get("value", "")

        return ""

    return ""





def _field_to_ui(field: PluginFieldSchema) -> dict[str, Any]:

    item: dict[str, Any] = {

        "key": field.key,

        "type": field.type,

        "label": field.label,

    }

    if field.hint:

        item["hint"] = field.hint

    if field.placeholder:

        item["placeholder"] = field.placeholder

    if field.type == "textarea":

        item["rows"] = 3

    if field.type == "select" and field.options:

        item["options"] = [

            {"value": str(opt.get("value", "")), "label": str(opt.get("label", opt.get("value", "")))}

            for opt in field.options

        ]

    return item





def build_ui_json(payload: CreateCustomPluginPayload) -> dict[str, Any]:

    defaults: dict[str, Any] = {}

    ui_fields: list[dict[str, Any]] = []

    for field in payload.fields:

        defaults[field.key] = _default_for_field(field)

        ui_fields.append(_field_to_ui(field))



    block_type = payload.plugin_id.replace("-", "_")

    return {

        "type": block_type,

        "name": payload.name,

        "icon": payload.icon,

        "color": payload.color,

        "description": f"Пользовательский компонент: {payload.name}",

        "palette": True,

        "connectable": True,

        "outputs": 1,

        "executable": True,

        "custom": True,

        "defaults": defaults,

        "fields": ui_fields,

    }





def _handler_name(block_type: str) -> str:

    return f"_type_handler_{block_type.replace('-', '_')}"





def generate_starter_template(payload: CreateCustomPluginPayload) -> str:

    block_type = payload.plugin_id.replace("-", "_")

    handler = _handler_name(block_type)

    lines = [

        f"# Обработчик пользовательского блока: {block_type}",

        f"async def {handler}(bot, chat_id, user_id, block_id, ctx, data, disable):",

        '    message = (data.get("message") or "Блок выполнен.").strip()',

        "    await bot.send_message(chat_id, message, disable_web_page_preview=disable)",

        "    next_id = get_next_block(block_id, 0)",

        "    if next_id:",

        "        await execute_block(bot, chat_id, user_id, next_id, ctx)",

    ]

    if payload.fields:

        first_key = payload.fields[0].key

        lines[2] = f'    message = (data.get("{first_key}") or "Блок выполнен.").strip()'

    return "\n".join(lines)





def _validate_template_code(payload: CreateCustomPluginPayload, code: str) -> None:

    block_type = payload.plugin_id.replace("-", "_")

    handler = _handler_name(block_type)

    if handler not in code:

        raise ValueError(

            f"В template_code должна быть async-функция {handler}(bot, chat_id, user_id, block_id, ctx, data, disable)"

        )



    ui = build_ui_json(payload)

    manager = get_plugin_manager()

    try:

        template = manager._jinja().from_string(code)

        rendered = template.render(

            plugin=ui,

            block={"type": block_type, "data": ui.get("defaults") or {}},

            data=ui.get("defaults") or {},

            scenario={"blocks": [], "connections": []},

        ).strip()

    except Exception as exc:

        raise ValueError(f"Синтаксическая ошибка шаблона: {exc}") from exc

    if not rendered:

        raise ValueError("Шаблон после рендера дал пустой код обработчика")





def create_custom_plugin(payload: CreateCustomPluginPayload) -> dict[str, Any]:

    ensure_data_dirs()
    if resolve_plugin_folder(payload.plugin_id) is not None:
        raise ValueError(f"Плагин с таким ID уже существует: {payload.plugin_id}")

    folder = USER_PLUGINS_DIR / payload.plugin_id

    if folder.exists():

        raise ValueError(f"Плагин с таким ID уже существует: {payload.plugin_id}")



    code = (payload.template_code or "").strip()

    if not code:

        code = generate_starter_template(payload)

    _validate_template_code(payload, code)



    folder.mkdir(parents=True, exist_ok=False)

    ui = build_ui_json(payload)



    ui_path = folder / "ui.json"

    code_path = folder / "code.py.jinja2"

    with open(ui_path, "w", encoding="utf-8") as f:

        json.dump(ui, f, ensure_ascii=False, indent=2)

        f.write("\n")

    with open(code_path, "w", encoding="utf-8") as f:

        f.write(code.rstrip() + "\n")



    manager = get_plugin_manager()

    manager.reload()

    plugin = manager.get_by_type(ui["type"])

    if not plugin:

        raise RuntimeError("Файлы записаны, но плагин не загрузился")



    return {

        "ok": True,

        "pluginId": payload.plugin_id,

        "type": ui["type"],

        "name": ui["name"],

        "path": str(folder),

        "pluginsReloaded": True,

    }


