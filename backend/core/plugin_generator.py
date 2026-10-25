"""Persist AI-generated BotBuilder plugins into the user plugins directory."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from backend.core.app_paths import USER_PLUGINS_DIR, ensure_data_dirs
from backend.core.plugin_manager import get_plugin_manager

PLUGIN_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
FIELD_TYPE_MAP = {
    "string": "text",
    "str": "text",
    "text": "text",
    "textarea": "textarea",
    "number": "number",
    "int": "number",
    "float": "number",
    "bool": "checkbox",
    "boolean": "checkbox",
    "checkbox": "checkbox",
    "select": "select",
}


class PluginGeneratorError(ValueError):
    """Invalid generated plugin payload."""


def _slugify(name: str) -> str:
    raw = (name or "").strip().lower()
    raw = re.sub(r"[\s]+", "_", raw)
    raw = re.sub(r"[^a-z0-9_-]", "", raw)
    if raw.endswith("_node"):
        raw = raw[: -len("_node")]
    if not raw:
        raw = "custom_plugin"
    if not PLUGIN_ID_RE.match(raw):
        raw = "p_" + re.sub(r"[^a-z0-9_]", "", raw)[:50]
        if not PLUGIN_ID_RE.match(raw):
            raw = "custom_plugin"
    return raw


def _normalize_fields(fields: Any) -> list[dict[str, Any]]:
    if not isinstance(fields, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in fields:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        ftype = FIELD_TYPE_MAP.get(str(item.get("type") or "text").strip().lower(), "text")
        field: dict[str, Any] = {
            "key": key,
            "type": ftype,
            "label": str(item.get("label") or key).strip() or key,
        }
        if item.get("hint"):
            field["hint"] = str(item["hint"])
        if item.get("placeholder"):
            field["placeholder"] = str(item["placeholder"])
        if ftype == "textarea":
            field["rows"] = int(item.get("rows") or 3)
        if ftype == "select" and isinstance(item.get("options"), list):
            field["options"] = item["options"]
        out.append(field)
    return out


def _normalize_ui_json(
    ui_json: dict[str, Any],
    fallback_type: str,
    *,
    ai_notes: str = "",
) -> dict[str, Any]:
    if not isinstance(ui_json, dict):
        raise PluginGeneratorError("ui_json must be an object")

    block_type = _slugify(str(ui_json.get("type") or fallback_type))
    name = str(ui_json.get("name") or block_type).strip() or block_type
    fields = _normalize_fields(ui_json.get("fields"))
    defaults = ui_json.get("defaults") if isinstance(ui_json.get("defaults"), dict) else {}
    norm_defaults: dict[str, Any] = {}
    for field in fields:
        key = field["key"]
        if key in defaults:
            norm_defaults[key] = defaults[key]
        elif field["type"] == "checkbox":
            norm_defaults[key] = False
        elif field["type"] == "number":
            norm_defaults[key] = 0
        else:
            norm_defaults[key] = ""

    outputs = ui_json.get("outputs", 1)
    if isinstance(outputs, list):
        outputs = max(1, len(outputs)) if outputs else 1
    try:
        outputs = max(1, int(outputs))
    except (TypeError, ValueError):
        outputs = 1

    palette = ui_json.get("palette", True)
    if isinstance(palette, str):
        palette = True

    caps_raw = ui_json.get("ai_capabilities")
    if not isinstance(caps_raw, dict):
        caps_raw = {}
    can = caps_raw.get("can") if isinstance(caps_raw.get("can"), list) else []
    cannot = caps_raw.get("cannot") if isinstance(caps_raw.get("cannot"), list) else []
    notes = (ai_notes or "").strip()
    summary = str(notes or caps_raw.get("summary") or f"AI-плагин: {name}")[:300]
    when = str(caps_raw.get("when_to_use") or notes or "Когда нужен этот кастомный блок")[:300]
    ports = caps_raw.get("ports") if isinstance(caps_raw.get("ports"), list) else None
    ai_capabilities = {
        "summary": summary,
        "can": [str(x)[:120] for x in can][:12],
        "cannot": [str(x)[:120] for x in cannot][:12],
        "when_to_use": when,
        "data_shape_hint": str(
            caps_raw.get("data_shape_hint")
            or (", ".join(f["key"] for f in fields) if fields else "{}")
        )[:400],
        "ports": [str(p) for p in (ports or ["0"])][:16],
    }
    if notes:
        ai_capabilities["notes"] = notes[:500]

    return {
        "type": block_type,
        "name": name[:80],
        "icon": str(ui_json.get("icon") or "🧩")[:8],
        "color": str(ui_json.get("color") or "#2563eb"),
        "description": str(
            ui_json.get("description") or notes or f"AI-generated: {name}"
        )[:500],
        "palette": bool(palette),
        "connectable": bool(ui_json.get("connectable", True)),
        "outputs": outputs,
        "executable": bool(ui_json.get("executable", True)),
        "defaults": norm_defaults,
        "fields": fields,
        "ai_capabilities": ai_capabilities,
    }


def _default_handler_template(expected: str) -> str:
    """Safe fallback: never silent OK — report missing implementation clearly."""
    return (
        f"async def {expected}(bot, chat_id, user_id, block_id, ctx, data, disable):\n"
        f"    data = data or {{}}\n"
        f"    typ = str((BLOCKS_BY_ID.get(block_id) or {{}}).get('type') or block_id or 'unknown')\n"
        f"    msg = (\n"
        f"        'Ошибка сценария: обработчик модуля [' + typ + '] не найден '\n"
        f"        'или не реализован. Пересохраните сценарий / перегенерируйте плагин.'\n"
        f"    )\n"
        f"    log.error('Missing plugin handler for block %s type=%s', block_id, typ)\n"
        f"    try:\n"
        f"        await bot.send_message(chat_id, msg, disable_web_page_preview=disable)\n"
        f"    except Exception:\n"
        f"        pass\n"
        f"    return 'default'\n"
    )


def _unique_plugin_id(base: str) -> str:
    mgr = get_plugin_manager()
    existing_types = {p.block_type for p in mgr.list_plugins()}
    existing_folders = set()
    ensure_data_dirs()
    if USER_PLUGINS_DIR.is_dir():
        existing_folders = {p.name for p in USER_PLUGINS_DIR.iterdir() if p.is_dir()}

    candidate = base
    n = 2
    while (
        candidate in existing_types
        or candidate in existing_folders
        or (USER_PLUGINS_DIR / candidate).exists()
    ):
        candidate = f"{base}_v{n}"
        n += 1
        if n > 50:
            raise PluginGeneratorError("Could not allocate unique plugin id")
    return candidate


def save_generated_plugin(
    plugin_name: str,
    ui_json: dict[str, Any],
    jinja_code: str,
    user_plugins_dir: Path | None = None,
    *,
    ai_notes: str = "",
) -> Path:
    ensure_data_dirs()
    root = Path(user_plugins_dir) if user_plugins_dir else USER_PLUGINS_DIR
    root.mkdir(parents=True, exist_ok=True)

    base = _slugify(plugin_name)
    ui = _normalize_ui_json(ui_json or {}, base, ai_notes=ai_notes)
    # Prefer folder id that matches type when possible
    folder_id = _unique_plugin_id(_slugify(ui["type"] or base))
    ui["type"] = folder_id.replace("-", "_")

    code = (jinja_code or "").strip()
    if not code:
        raise PluginGeneratorError("jinja_code is empty")
    # Ensure handler name matches registry expectation
    safe = ui["type"].replace("-", "_")
    expected = f"_type_handler_{safe}"
    if expected not in code and "_type_handler_" not in code:
        code = _default_handler_template(expected)

    folder = root / folder_id
    folder.mkdir(parents=True, exist_ok=False)
    (folder / "ui.json").write_text(
        json.dumps(ui, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (folder / "code.py.jinja2").write_text(code + "\n", encoding="utf-8")

    try:
        get_plugin_manager().reload_user_plugins()
    except Exception:
        try:
            get_plugin_manager().reload()
        except Exception:
            pass

    return folder
