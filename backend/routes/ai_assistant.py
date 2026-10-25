"""FastAPI routes for BotCopilot — tool-calling Auto-Pilot agent."""

from __future__ import annotations

import ast
import json
import logging
import re
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.auth_deps import get_current_user_id_required
from backend.core.bot_access import require_bot_access
from backend.db.database import get_db

from backend.core.ai_config import load_ai_config, require_ai_ready
from backend.core.ai_bot_rules import BOTBUILDER_SYSTEM_RULES
from backend.core.bot_error_registry import bot_error_registry
from backend.core.plugin_generator import PluginGeneratorError, save_generated_plugin
from backend.core.plugin_manager import get_plugin_manager
from backend.services import ai_chat_history, ai_progress
from backend.services.ai_provider import (
    NO_ACTION_REPLY,
    SUBTASK_MAX_TOKENS,
    AIProvider,
    extract_json_object,
)
from backend.services.ai_intent import (
    enhance_system_prompt,
    extract_latest_user_text,
    format_intent_guidelines,
    classify_user_intent,
    inspect_and_wire_app,
    generate_and_wire_standalone_app,
    maybe_autosave_code_blocks,
    WORKSPACE_FILE_CRITICAL_DIRECTIVE,
    MAX_AGENT_STEPS,
    MAX_PLAN_SUBTASKS,
    MAX_SUBTASK_STEPS,
    create_complete_standalone_app,
)
from backend.services.ai_tools import sanitize_scenario_connections, write_workspace_file
from backend.services.app_inspector import AppInspectorError
from backend.services.ai_scenario_ops import (
    ScenarioDocument,
    ScenarioPatch,
    apply_scenario_patch,
    autopilot_scenario_mode,
    build_plugin_catalog,
    catalog_types,
    finalize_scenario,
    format_autopilot_status,
    format_catalog_for_prompt,
    serialize_scenario_for_llm,
    truncate_reply,
)

router = APIRouter(prefix="/api/ai", tags=["ai-assistant"])
log = logging.getLogger(__name__)

# Model said "done" in text but called no tool: the user must not be misled.
_CLAIMS_DONE_RE = re.compile(
    r"\b(готово|сделано|создано|создал|обновил|изменил|исправил|подключил|done|updated|created)\b",
    re.IGNORECASE,
)
TASK_SIZE_DIRECTIVE = """TASK SIZE (decide before acting):
- SMALL (one file under ~250 lines, a text/scenario tweak, a fix): act directly with tools.
- LARGE (several files, a whole application, several independent features, or code you
  expect to exceed ~250 lines): call plan_task FIRST. Write a shared_contract with file
  layout, function signatures and data formats, then 2-10 subtasks of one file or one
  scenario change each. After plan_task returns, assemble: wire the app into the
  scenario, fix verification errors, redo failed subtasks. Report to the user only after."""

NO_ACTION_NOTE = (
    "Внимание: инструменты не вызывались, файлы и сценарий не изменены. "
    "Текст выше описывает намерение модели, а не выполненные действия."
)

MAX_CHAT_TURNS = 40

# ---------------------------------------------------------------------------
# BotBuilderMetaContext — dynamic system prompt
# ---------------------------------------------------------------------------

BOTCOPILOT_META_CONTEXT = """You are BotCopilot, an autonomous agent inside the BotBuilder IDE.
Auto-Pilot is ON by default: execute tools immediately. Never ask for confirmation cards.
Never dump full JSON scenarios or plugin source into the user-facing reply.

## Native core plugins (PREFER THESE — do NOT generate a custom plugin when they cover the task)
{plugin_catalog}

## Hard rules
1. Prefer existing plugins over create_custom_plugin. Examples:
   - Text / greetings → type "message" (sendMessage / send_message) — NEVER invent a text plugin.
   - User input → "data" with valueSource=input
   - Branching → "condition"
   - Menus / buttons → "menu" or "message" with buttons
   - Weather → existing "weather" plugin
2. Syntax: use {{{{variable_name}}}} for dynamic data interpolation in message/data fields.
3. Use update_db_schema when the bot needs named variables (forms, bookings, carts).
4. Use patch_graph to insert/update scenario nodes. Set layout_needed=true unless positions are already good.
5. Call create_custom_plugin ONLY when no catalog type can fulfill the request. Pass a clear name + description; code/ui_json optional (system can generate).
6. Reply language = user's language. Extremely short confirmation only (1–2 sentences, plain text, NO emojis). State what was created — no fluff.
7. When the canvas already has blocks and the user asks to fix/add — patch mode. Empty canvas / "from scratch" — replace mode.
8. SELF-HEAL: If the user asks why the bot failed / how to fix a crash, OR Auto-Pilot is on and RECENT RUNTIME ERRORS is non-empty — analyze the stack trace and immediately `patch_graph` (and/or node data) to fix the broken node / connections. Prefer minimal patches. Do not ask for confirmation.
9. NEVER put emojis in message texts, button labels, node names, or prompts (RULE 9).
10. Standalone apps: prefer ONE call to `create_complete_standalone_app` (writes scripts/<name>/app.py + manifest.json and wires app_bridge). Alternatives: `write_workspace_file` + `inspect_and_wire_app`, or `generate_standalone_app`. Prefer app_bridge over create_custom_plugin for external scripts.

## Workspace file writes (MANDATORY)
{workspace_file_critical}

{botbuilder_system_rules}

{intent_guidelines}

## Current canvas topology
{canvas_topology}

--- RECENT RUNTIME ERRORS ---
{runtime_errors}
"""

AI_PLUGIN_SYSTEM_PROMPT = """Создай плагин BotBuilder. Ответ строго JSON без markdown.

Формат:
{
  "ui_json": {
    "type": "snake_case_id",
    "name": "Название",
    "icon": "",
    "color": "#2563eb",
    "description": "Кратко",
    "fields": [{ "key": "inputPrompt", "label": "Подсказка", "type": "text" }],
    "defaults": { "inputPrompt": "Введите значение" },
    "palette": true,
    "outputs": 1,
    "executable": true,
    "connectable": true,
    "ai_capabilities": {
      "summary": "что делает",
      "can": ["..."],
      "cannot": ["..."],
      "when_to_use": "...",
      "data_shape_hint": "inputPrompt, ...",
      "ports": ["0"]
    }
  },
  "jinja_code": "async def _type_handler_TYPE(bot, chat_id, user_id, block_id, ctx, data, disable):\\n    ..."
}

КРИТИЧНО — без эмодзи в name/description/defaults/prompts (RULE 9). icon оставь пустым или одно ASCII-слово.

КРИТИЧНО — параметры handler (никогда не путай):
- data (dict): настройки блока из ui.json / панели свойств. Пример: prompt = (data or {}).get('inputPrompt') or ''.
  НИКОГДА не делай str(data), не отправляй data целиком пользователю, не путай data с текстом сообщения.
- ctx (dict): runtime-состояние. Текст пользователя бери ТОЛЬКО из ctx:
  user_text = (ctx.get('last_message_text') or ctx.get('text') or ctx.get('last_message') or ctx.get('user_input') or '').strip()
- bot, chat_id, user_id, block_id, disable — стандартные аргументы aiogram-рантайма BotBuilder.

Требования:
- fields[].type: text|textarea|number|checkbox|select
- ai_capabilities обязателен (summary, when_to_use, ports)
- jinja_code: async def _type_handler_<type>(bot, chat_id, user_id, block_id, ctx, data, disable)
- aiogram send_message OK; стандартная библиотека; без requests/aiohttp если можно urllib
- Функция должна return строку имени выхода (обычно 'default' или '0')
"""

AI_SCENARIO_REPLACE_PROMPT = """Сгенерируй ПОЛНЫЙ сценарий BotBuilder. Ответ строго JSON без markdown.

Формат (Pydantic ScenarioDocument):
{{
  "summary": "1 предложение",
  "blocks": [
    {{ "id": "start", "type": "start", "x": 100, "y": 100, "data": {{}} }},
    {{ "id": "msg_1", "type": "message", "x": 420, "y": 100, "data": {{ "text": "Привет" }} }}
  ],
  "connections": [
    {{
      "id": "c_start_0_msg_1",
      "from_block_id": "start",
      "from_port": "0",
      "to_block_id": "msg_1",
      "to_port": "in"
    }}
  ],
  "required_plugins": ["start", "message"]
}}

Допустимо также legacy connection: {{ "from": "start", "outputIndex": "0", "to": "msg_1" }}.

Каталог (ТОЛЬКО эти type; смотри ports/can/cannot):
{plugin_catalog}

Правила:
1. Всегда блок start id=start.
2. id уникальные snake_case. Координаты приблизительные — сервер выровняет сетку ΔX=320 ΔY=160.
3. from_port / outputIndex — строка. condition: "0"=да "1"=нет.
4. data по data_shape_hint. Не выдумывай type вне каталога.
5. Связь от start обязательна. required_plugins = все type из blocks.
6. Dynamic text: use {{{{variable_name}}}} placeholders.
7. FSM: data valueSource=input ALWAYS waits for a NEW message after button/menu transitions. Validation loops: condition port 1 → error message → back to the SAME input block id; set inputOnlyIfEmpty=false for promo/code retries.
8. NO EMOJIS in any text, button, label, or prompt (plain professional Russian/English only).
9. summary: one short plain sentence, no emojis.
"""

AI_SCENARIO_PATCH_PROMPT = """Составь ПАТЧ к текущему сценарию BotBuilder. Ответ строго JSON (ScenarioPatch).

Формат:
{{
  "summary": "что изменится",
  "add_blocks": [ {{"id","type","x","y","data"}} ],
  "update_blocks": [ {{"id","type","x","y","data"}} ],
  "remove_block_ids": [],
  "add_connections": [
    {{ "id": "c_a_0_b", "from_block_id": "a", "from_port": "0", "to_block_id": "b", "to_port": "in" }}
  ],
  "remove_connection_ids": ["c_old_id"]
}}

Каталог type + ports:
{plugin_catalog}

Правила:
1. Не удаляй start. Минимальный патч.
2. from_port/outputIndex — строка. Только type из каталога в add_blocks.
3. id новых блоков уникальны относительно текущего сценария.
4. Dynamic text: use {{{{variable_name}}}} placeholders.
5. FSM: Input nodes pause for a fresh event; loops back to Input must target that block id; inputOnlyIfEmpty=false for retry loops.
6. NO EMOJIS in texts/buttons/labels. summary: 1 short plain sentence.
"""

# OpenAI-compatible tool schemas (DeepSeek / Anthropic proxies)
BOTCOPILOT_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "update_db_schema",
            "description": (
                "Add or modify bot database / context variables. "
                "Use for forms, bookings, user profile fields. "
                "Keys become {{{{variable_name}}}} placeholders in messages."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "variables": {
                        "type": "object",
                        "additionalProperties": {"type": "string"},
                        "description": "Map variable_name → type or short description (e.g. 'string: user name').",
                    }
                },
                "required": ["variables"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "patch_graph",
            "description": (
                "Insert or update scenario graph nodes/edges using EXISTING plugin types. "
                "Prefer this over create_custom_plugin. "
                "If you omit nodes, pass instruction + mode and the system will generate the graph."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nodes_to_add": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "type": {"type": "string"},
                                "x": {"type": "number"},
                                "y": {"type": "number"},
                                "data": {"type": "object"},
                            },
                        },
                        "description": "Blocks to add (canvas shape: id, type, x, y, data).",
                    },
                    "edges_to_add": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "from": {"type": "string"},
                                "to": {"type": "string"},
                                "outputIndex": {"type": "string"},
                                "from_block_id": {"type": "string"},
                                "to_block_id": {"type": "string"},
                                "from_port": {"type": "string"},
                            },
                        },
                        "description": "Connections to add.",
                    },
                    "nodes_to_update": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "Existing blocks to update by id.",
                    },
                    "nodes_to_remove": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Block ids to remove (never remove start).",
                    },
                    "layout_needed": {
                        "type": "boolean",
                        "description": "True to auto-layout after patch (default true).",
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["patch", "replace"],
                        "description": "patch merges into canvas; replace rebuilds from nodes or instruction.",
                    },
                    "instruction": {
                        "type": "string",
                        "description": "Natural-language graph intent when nodes are omitted.",
                    },
                    "summary": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_custom_plugin",
            "description": (
                "Generate a Python BotBuilder plugin ONLY IF core plugins cannot fulfill the request. "
                "Prefer patch_graph with message/data/condition/menu/weather first. "
                "For standalone scripts under scripts/, use inspect_and_wire_app / generate_standalone_app instead."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "snake_case plugin type id",
                    },
                    "description": {
                        "type": "string",
                        "description": "What the plugin does and when to use it",
                    },
                    "code": {
                        "type": "string",
                        "description": "Optional jinja/python handler code",
                    },
                    "ui_json": {
                        "type": "object",
                        "description": "Optional ui.json object",
                    },
                },
                "required": ["name", "description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "inspect_and_wire_app",
            "description": (
                "Inspect a standalone Python app under the bot repository (scripts/<name>/), "
                "synthesize manifest.json if missing, place an app_bridge node on the canvas, "
                "map inputs to {{user.*}} variables, and wire success/error output ports."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "app_folder_path": {
                        "type": "string",
                        "description": "Path relative to bot root, e.g. scripts/my_custom_crm or my_parser",
                    },
                    "wire_default_messages": {
                        "type": "boolean",
                        "description": "Create success/error message nodes and connect ports (default true).",
                    },
                    "summary": {"type": "string"},
                },
                "required": ["app_folder_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_standalone_app",
            "description": (
                "Generate a standalone Python application under scripts/<app_name>/ together with "
                "manifest.json from a natural-language brief, then wire an app_bridge node."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "app_name": {
                        "type": "string",
                        "description": "snake_case folder name under scripts/",
                    },
                    "description": {
                        "type": "string",
                        "description": "What the app should do",
                    },
                    "python_files": {
                        "type": "object",
                        "additionalProperties": {"type": "string"},
                        "description": "Map filename → Python source (e.g. main.py).",
                    },
                    "manifest": {
                        "type": "object",
                        "description": "Optional manifest.json override",
                    },
                    "wire": {
                        "type": "boolean",
                        "description": "Wire app_bridge after generation (default true).",
                    },
                    "summary": {"type": "string"},
                },
                "required": ["app_name", "description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_workspace_file",
            "description": (
                "Write a physical text file into the bot workspace under scripts/ "
                "(or another relative path). Creates parent directories automatically. "
                "Use for parser scripts, helpers, and manifest.json files "
                "(e.g. scripts/book_parser/app.py, scripts/book_parser/manifest.json). "
                "No emojis in content."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "relative_path": {
                        "type": "string",
                        "description": (
                            "Path relative to bot root, e.g. scripts/book_parser/app.py"
                        ),
                    },
                    "content": {
                        "type": "string",
                        "description": "Full file text content to write",
                    },
                    "summary": {"type": "string"},
                },
                "required": ["relative_path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_complete_standalone_app",
            "description": (
                "ATOMIC: create a full standalone app in ONE call. Writes "
                "scripts/<app_name>/app.py and manifest.json, then wires an "
                "app_bridge node (and optional success/error messages) into the "
                "scenario. Prefer this over multiple write_workspace_file calls."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "app_name": {
                        "type": "string",
                        "description": "Folder name under scripts/, e.g. book_parser",
                    },
                    "script_code": {
                        "type": "string",
                        "description": "Full Python source for app.py (must define async def main or fetch_batch).",
                    },
                    "manifest": {
                        "type": "object",
                        "description": "manifest.json fields (entryFile, entryFunction, inputs, ...).",
                    },
                    "nodes_to_add": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "Optional canvas blocks to insert (id, type, x, y, data).",
                    },
                    "connections_to_add": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": (
                            "Optional connections {from, to, outputIndex}. Use \"app_bridge\" as "
                            "from/to to reference the created bridge node. outputIndex is numeric: "
                            "\"0\" success, \"1\" error. Edges to unknown nodes are dropped."
                        ),
                    },
                    "wire_default_messages": {
                        "type": "boolean",
                        "description": "Wire success/error message nodes when nodes_to_add omitted (default true).",
                    },
                    "summary": {"type": "string"},
                },
                "required": ["app_name", "script_code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "plan_task",
            "description": (
                "Split a LARGE task into small subtasks that are executed one by one, each in "
                "its own short agent run, then return results for final assembly. Use it when "
                "the request needs several files, more than ~250 lines of code, or several "
                "independent features. Do NOT use it for small edits. Each subtask must be "
                "self-contained: one file or one scenario change, with exact file paths, "
                "function names and data formats shared between subtasks."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "goal": {"type": "string", "description": "Overall goal in one or two sentences."},
                    "shared_contract": {
                        "type": "string",
                        "description": (
                            "Interfaces every subtask must follow: file layout, function "
                            "signatures, return formats, variable names."
                        ),
                    },
                    "subtasks": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "instructions": {"type": "string"},
                                "files": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "Files this subtask must create or rewrite.",
                                },
                            },
                            "required": ["title", "instructions"],
                        },
                    },
                },
                "required": ["goal", "subtasks"],
            },
        },
    },
]

SUBTASK_PROMPT = """You are executing ONE subtask of a larger plan. Do only this subtask, using tools.

GOAL: {goal}

SHARED CONTRACT (must be followed exactly):
{contract}

PLAN:
{plan}

ALREADY DONE:
{done}

CURRENT CANVAS:
{canvas}

YOUR SUBTASK ({index}/{total}): {title}
{instructions}
Files to produce: {files}

Rules: write complete files (no placeholders, no "rest of code here"). Keep code compact.
If the subtask is still too large, write it as several smaller modules.
When finished, reply with one short line describing what was done."""


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class ChatMessage(BaseModel):
    role: str
    content: str = ""


class ChatPayload(BaseModel):
    messages: list[ChatMessage] = Field(default_factory=list)
    bot_id: str | int | None = None
    current_scenario: dict[str, Any] | None = None
    auto_pilot: bool = True  # Auto-Pilot by default
    message: str = ""  # optional single new user turn
    request_id: str | None = Field(default=None, max_length=64)


class PluginSuggestion(BaseModel):
    plugin_name: str = "custom_plugin"
    description: str = ""
    rationale: str = ""


class ScenarioAction(BaseModel):
    mode: Literal["replace", "patch"] = "replace"
    hint: str = ""


class ChatIntentResponse(BaseModel):
    """Legacy structured intent (kept for fallback when tools unsupported)."""

    reply: str = ""
    intent: Literal["clarify", "need_plugin", "ready_replace", "ready_patch", "answer"] = "answer"
    plugin_suggestion: Optional[PluginSuggestion] = None
    scenario_action: Optional[ScenarioAction] = None


class GeneratePluginPayload(BaseModel):
    description: str = ""
    plugin_name: str = ""
    context: str = ""
    ai_notes: str = ""


class GeneratedPluginPayload(BaseModel):
    ui_json: dict[str, Any] = Field(default_factory=dict)
    jinja_code: str = ""

    @classmethod
    def model_validate_loose(cls, data: dict[str, Any]) -> "GeneratedPluginPayload":
        ui = data.get("ui_json") if isinstance(data.get("ui_json"), dict) else data
        code = str(data.get("jinja_code") or data.get("template_code") or "")
        return cls(ui_json=ui if isinstance(ui, dict) else {}, jinja_code=code)


class ScenarioOpPayload(BaseModel):
    mode: str = "replace"
    instruction: str = ""
    current_scenario: dict[str, Any] = Field(default_factory=dict)
    messages: list[ChatMessage] = Field(default_factory=list)
    available_plugins: list[str] = Field(default_factory=list)
    auto_pilot: bool = True


class GenerateScenarioPayload(BaseModel):
    description: str = ""
    available_plugins: list[str] = Field(default_factory=list)
    messages: list[ChatMessage] = Field(default_factory=list)
    current_scenario: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize_chat_messages(messages: list[ChatMessage] | list[dict[str, Any]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for msg in messages:
        if isinstance(msg, ChatMessage):
            role = (msg.role or "").strip().lower()
            content = (msg.content or "").strip()
        elif isinstance(msg, dict):
            role = str(msg.get("role") or "").strip().lower()
            content = str(msg.get("content") or "").strip()
        else:
            continue
        if role not in ("user", "assistant"):
            continue
        if not content:
            continue
        out.append({"role": role, "content": content})
    return out[-MAX_CHAT_TURNS:]


def _instruction_from_messages(body_instruction: str, messages: list[ChatMessage]) -> str:
    chat = _normalize_chat_messages(messages)
    users = [m["content"] for m in chat if m["role"] == "user"]
    if users:
        text = users[0]
        if len(users) > 1:
            text = users[0] + "\n\nУточнения:\n" + "\n".join(users[1:])
        return text
    return (body_instruction or "").strip()


def _build_meta_context(
    catalog: list[dict[str, Any]],
    current_scenario: dict[str, Any] | None,
    *,
    bot_id: str | int | None = None,
    user_text: str = "",
) -> str:
    topo = "(empty canvas)"
    if isinstance(current_scenario, dict) and (current_scenario.get("blocks") or []):
        topo = serialize_scenario_for_llm(current_scenario)[:4500]
    runtime_errors = bot_error_registry.format_for_prompt(bot_id, limit=8)
    intent_block = format_intent_guidelines(classify_user_intent(user_text))
    prompt = BOTCOPILOT_META_CONTEXT.format(
        plugin_catalog=format_catalog_for_prompt(catalog),
        canvas_topology=topo,
        botbuilder_system_rules=BOTBUILDER_SYSTEM_RULES,
        runtime_errors=runtime_errors,
        intent_guidelines=intent_block or "",
        workspace_file_critical=WORKSPACE_FILE_CRITICAL_DIRECTIVE,
    )
    if bot_id is None:
        workspace = (
            "WORKSPACE: none (no bot open). File tools will fail; never pass a bot_id yourself "
            "and never simulate a script with message blocks."
        )
    else:
        workspace = (
            f"WORKSPACE: bot {bot_id}. The server binds every file tool to this bot; "
            "do not pass bot_id. Standalone code MUST be created with "
            "create_complete_standalone_app (block type app_bridge), never with message blocks. "
            "Connection outputIndex is always a numeric string: app_bridge \"0\"=success, "
            "\"1\"=error; one target per output port.\n"
            "To CHANGE an existing app (an app_bridge with appFolder already exists on the canvas): "
            "call write_workspace_file with the FULL new content of <appFolder>/app.py, do not "
            "create a second bridge. Change message texts or images with patch_graph. "
            "The bridge stores the script's \"result\" value as plain text in "
            "{{app_bridge_result}}; return ready-to-send text there. Never answer that work is "
            "done unless a tool call in this turn succeeded."
        )
    return f"{prompt}\n\n{workspace}\n\n{TASK_SIZE_DIRECTIVE}"


def _validate_jinja_python(code: str, handler_name: str) -> None:
    raw = (code or "").strip()
    if not raw:
        raise PluginGeneratorError("jinja_code is empty")
    probe = re.sub(r"\{\{.*?\}\}", "x", raw)
    probe = re.sub(r"\{%.*?%\}", "", probe)
    if handler_name not in probe and "_type_handler_" not in probe:
        raise PluginGeneratorError(f"jinja_code must define {handler_name}")
    try:
        ast.parse(probe)
    except SyntaxError as exc:
        if "async def" not in probe and "def " not in probe:
            raise PluginGeneratorError(f"jinja_code is not valid Python: {exc}") from exc


def _coerce_block(item: dict[str, Any], idx: int) -> dict[str, Any]:
    return {
        "id": str(item.get("id") or f"block_{idx}"),
        "type": str(item.get("type") or "message"),
        "x": item.get("x") if item.get("x") is not None else 100 + idx * 320,
        "y": item.get("y") if item.get("y") is not None else 100,
        "data": item.get("data") if isinstance(item.get("data"), dict) else {},
    }


def _coerce_connection(item: dict[str, Any]) -> dict[str, Any]:
    frm = item.get("from") or item.get("from_block_id") or ""
    to = item.get("to") or item.get("to_block_id") or ""
    port = item.get("outputIndex") or item.get("from_port") or "0"
    return {
        "from": str(frm),
        "to": str(to),
        "outputIndex": str(port),
        "from_block_id": str(frm),
        "to_block_id": str(to),
        "from_port": str(port),
        "to_port": str(item.get("to_port") or "in"),
        "id": str(item.get("id") or f"c_{frm}_{port}_{to}"),
    }


# ---------------------------------------------------------------------------
# Plugin / scenario ops (shared)
# ---------------------------------------------------------------------------


async def _generate_and_save_plugin(
    *,
    description: str,
    plugin_name: str = "",
    context: str = "",
    ai_notes: str = "",
    code: str = "",
    ui_json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Shared plugin generation used by /generate-plugin and tool create_custom_plugin."""
    cfg = require_ai_ready()
    description = (description or plugin_name or "").strip()
    if not description and not (code and ui_json):
        raise HTTPException(status_code=400, detail="description required")

    ai_notes = (ai_notes or description or "").strip()
    jinja_code = (code or "").strip()
    ui: dict[str, Any] = ui_json if isinstance(ui_json, dict) else {}

    if not jinja_code or not ui:
        user_content = (
            f"plugin_name: {plugin_name or 'custom_plugin'}\n"
            f"description: {description}\n"
            f"context: {context or ''}\n"
            f"ai_notes: {ai_notes}\n"
            "Remember: read user message from ctx['last_message_text'], settings from data[field_key]. "
            "Never str(data) or send data dict to the user.\n"
        )
        provider = AIProvider(cfg)
        raw = await provider.complete(
            [{"role": "user", "content": user_content}],
            AI_PLUGIN_SYSTEM_PROMPT,
            json_mode=True,
            temperature=0.15,
            purpose="generate-plugin",
            model=cfg.model_for_role("coder"),
        )
        try:
            parsed = extract_json_object(raw)
        except ValueError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Невалидный JSON плагина: {exc}",
            ) from exc
        loose = GeneratedPluginPayload.model_validate_loose(parsed)
        if not ui:
            ui = loose.ui_json if isinstance(loose.ui_json, dict) else {}
        if not jinja_code:
            jinja_code = loose.jinja_code

    if ai_notes:
        caps = ui.get("ai_capabilities") if isinstance(ui.get("ai_capabilities"), dict) else {}
        caps = dict(caps)
        caps["summary"] = ai_notes[:300]
        if not caps.get("when_to_use"):
            caps["when_to_use"] = ai_notes[:300]
        ui["ai_capabilities"] = caps
        if not ui.get("description"):
            ui["description"] = ai_notes[:500]

    name = (plugin_name or str((ui or {}).get("type") or "custom_plugin")).strip()
    safe_guess = re.sub(r"[^a-z0-9_]", "_", name.lower()) or "custom_plugin"
    try:
        _validate_jinja_python(jinja_code, f"_type_handler_{safe_guess}")
    except PluginGeneratorError:
        pass

    try:
        folder = save_generated_plugin(
            name,
            ui if isinstance(ui, dict) else {},
            jinja_code,
            ai_notes=ai_notes,
        )
    except PluginGeneratorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to save plugin: {exc}") from exc

    try:
        get_plugin_manager().reload_user_plugins()
    except Exception:
        try:
            get_plugin_manager().reload()
        except Exception:
            pass

    saved_ui: dict[str, Any] = {}
    try:
        saved_ui = json.loads((folder / "ui.json").read_text(encoding="utf-8"))
    except Exception:
        saved_ui = ui if isinstance(ui, dict) else {}

    code_text = (folder / "code.py.jinja2").read_text(encoding="utf-8")
    catalog = build_plugin_catalog()
    return {
        "plugin_name": folder.name,
        "ui_json": saved_ui,
        "jinja_preview": code_text,
        "saved_path": str(folder),
        "plugin_catalog": catalog,
        "plugins": [c["type"] for c in catalog],
    }


async def _run_scenario_op(
    *,
    mode: str,
    instruction: str,
    current_scenario: dict[str, Any],
    messages: list[ChatMessage] | list[dict[str, str]],
    available_plugins: list[str],
) -> dict[str, Any]:
    try:
        cfg = require_ai_ready()
    except ValueError as exc:
        msg = str(exc)
        code = 403 if "disabled" in msg.lower() else 400
        raise HTTPException(status_code=code, detail=msg) from exc

    mode = (mode or "replace").strip().lower()
    if mode not in ("replace", "patch"):
        raise HTTPException(status_code=400, detail="mode must be replace or patch")

    if isinstance(messages, list) and messages and isinstance(messages[0], ChatMessage):
        chat_msgs = _normalize_chat_messages(messages)  # type: ignore[arg-type]
        instruction = _instruction_from_messages(instruction, messages) or instruction.strip()  # type: ignore[arg-type]
    else:
        chat_msgs = _normalize_chat_messages(
            [ChatMessage(role=m["role"], content=m["content"]) for m in messages if isinstance(m, dict)]  # type: ignore[index]
        )
        instruction = (instruction or "").strip()

    if not instruction and not chat_msgs:
        raise HTTPException(status_code=400, detail="instruction required")

    try:
        get_plugin_manager().reload_user_plugins()
    except Exception:
        pass
    catalog = build_plugin_catalog()
    allowed = catalog_types(catalog)
    if available_plugins:
        allowed = allowed | {str(x) for x in available_plugins if x}

    catalog_text = format_catalog_for_prompt(
        [c for c in catalog if c["type"] in allowed] or catalog
    )
    # Append FSM rules so replace/patch never emit collision-prone graphs
    catalog_text = catalog_text + "\n\n" + BOTBUILDER_SYSTEM_RULES
    # Silent keyword intent (payments / auth / AI agent) — no UI
    chat_for_intent: list[dict[str, str]] = []
    if chat_msgs:
        chat_for_intent = [
            {"role": str(m.get("role") or ""), "content": str(m.get("content") or "")}
            for m in chat_msgs
            if isinstance(m, dict)
        ]
    intent_user = extract_latest_user_text(instruction, chat_for_intent)

    provider = AIProvider(cfg)
    topo = serialize_scenario_for_llm(current_scenario or {})

    if mode == "replace":
        system = AI_SCENARIO_REPLACE_PROMPT.format(plugin_catalog=catalog_text)
        system = enhance_system_prompt(system, user_text=intent_user)
        user_bits = [instruction or "Создай сценарий по истории диалога."]
        if chat_msgs:
            hist = "\n".join(f"{m['role']}: {m['content'][:400]}" for m in chat_msgs[-12:])
            user_bits.append("История диалога:\n" + hist)
        if current_scenario and (current_scenario.get("blocks") or []):
            user_bits.append("Текущий canvas (для справки, будет заменён):\n" + topo[:3000])
        user_content = "\n\n".join(user_bits)
        doc = await provider.call_structured_llm(
            [{"role": "user", "content": user_content}],
            ScenarioDocument,
            system_prompt=system,
            max_retries=2,
            temperature=0.1,
            purpose="scenario-replace",
            model=cfg.model_for_role("scenario"),
        )
        summary = doc.summary or ""
        fixed = finalize_scenario(doc.model_dump(), allowed)
    else:
        system = AI_SCENARIO_PATCH_PROMPT.format(plugin_catalog=catalog_text)
        system = enhance_system_prompt(system, user_text=intent_user)
        user_content = (
            f"Инструкция: {instruction or 'Внеси правки по истории диалога.'}\n\n"
            f"Текущий сценарий (topology):\n{topo}\n"
        )
        if chat_msgs:
            hist = "\n".join(f"{m['role']}: {m['content'][:400]}" for m in chat_msgs[-12:])
            user_content += "\nИстория диалога:\n" + hist
        patch = await provider.call_structured_llm(
            [{"role": "user", "content": user_content}],
            ScenarioPatch,
            system_prompt=system,
            max_retries=2,
            temperature=0.1,
            purpose="scenario-patch",
            model=cfg.model_for_role("scenario"),
        )
        summary = patch.summary or ""
        fixed = apply_scenario_patch(current_scenario or {}, patch, allowed)

    if not fixed.get("blocks"):
        raise HTTPException(status_code=422, detail="Пустой сценарий после валидации")
    if not fixed.get("connections") and len(fixed["blocks"]) > 1:
        raise HTTPException(status_code=422, detail="Нет валидных связей в сценарии")

    return {
        "mode": mode,
        "summary": summary or ("Сценарий обновлён" if mode == "patch" else "Сценарий создан"),
        "scenario": fixed,
        "blocks": fixed["blocks"],
        "connections": fixed["connections"],
        "required_plugins": fixed.get("required_plugins") or [],
        "tags": fixed.get("tags") or [],
        "plugin_catalog": catalog,
    }


# ---------------------------------------------------------------------------
# Tool executors (agent state)
# ---------------------------------------------------------------------------


_WORKSPACE_TOOLS = frozenset(
    {
        "write_workspace_file",
        "create_complete_standalone_app",
        "inspect_and_wire_app",
        "generate_standalone_app",
    }
)


class _AgentState:
    def __init__(
        self,
        *,
        current_scenario: dict[str, Any] | None,
        messages: list[dict[str, str]],
        bot_id: str | int | None = None,
    ) -> None:
        self.scenario = dict(current_scenario) if isinstance(current_scenario, dict) else {}
        self.messages = messages
        self.bot_id = bot_id
        self.schema_vars: dict[str, str] = {}
        self.plugin_created: dict[str, Any] | None = None
        self.last_mode: str | None = None
        self.last_summary: str = ""
        self.actions: list[dict[str, Any]] = []
        # Set by the chat route; needed to run subtask agents for plan_task.
        self.provider: AIProvider | None = None
        self.system_prompt: str = ""
        self.model: str | None = None
        self.worker_model: str | None = None
        self.request_id: str | None = None
        self.plan_depth = 0

    def progress(self, kind: str, text: str) -> None:
        ai_progress.emit(self.request_id, text, kind=kind)

    def cancelled(self) -> bool:
        return ai_progress.is_cancelled(self.request_id)

    @staticmethod
    def _describe_tool(name: str, args: dict[str, Any]) -> str:
        if name == "write_workspace_file":
            return f"Пишу файл {args.get('relative_path') or args.get('path') or ''}".strip()
        if name == "create_complete_standalone_app":
            return f"Создаю приложение scripts/{args.get('app_name') or args.get('name') or ''}"
        if name == "inspect_and_wire_app":
            return f"Подключаю {args.get('app_folder_path') or args.get('app_folder') or 'приложение'} к боту"
        if name == "patch_graph":
            return "Меняю сценарий на холсте"
        if name == "generate_standalone_app":
            return f"Генерирую приложение {args.get('app_name') or ''}".strip()
        if name == "create_custom_plugin":
            return f"Создаю плагин {args.get('name') or args.get('plugin_name') or ''}".strip()
        if name == "update_db_schema":
            return "Обновляю схему данных"
        if name == "plan_task":
            n = len(args.get("subtasks") or [])
            return f"Задача большая: составлен план из {n} частей"
        return f"Выполняю {name}"

    async def _plan_task(self, args: dict[str, Any]) -> dict[str, Any]:
        if self.provider is None:
            return {"ok": False, "error": "plan_task unavailable: no provider bound"}
        if self.plan_depth >= 2:
            return {"ok": False, "error": "plan nesting too deep; execute the subtask directly"}
        raw = args.get("subtasks") if isinstance(args.get("subtasks"), list) else []
        subtasks = [s for s in raw if isinstance(s, dict) and (s.get("instructions") or s.get("title"))]
        if not subtasks:
            return {"ok": False, "error": "subtasks list is empty"}
        subtasks = subtasks[:MAX_PLAN_SUBTASKS]
        goal = str(args.get("goal") or "")[:2000]
        contract = str(args.get("shared_contract") or "(none)")[:6000]
        sub_tools = [t for t in BOTCOPILOT_TOOLS if t["function"]["name"] != "plan_task"]
        plan_lines = "\n".join(
            f"{i + 1}. {s.get('title') or 'step'} -> {', '.join(s.get('files') or []) or 'no files'}"
            for i, s in enumerate(subtasks)
        )
        log.info("plan_task: %d subtasks for goal=%r", len(subtasks), goal[:200])

        results: list[dict[str, Any]] = []
        self.plan_depth += 1
        try:
            for i, st in enumerate(subtasks):
                if self.cancelled():
                    break
                self.progress(
                    "plan",
                    f"Часть {i + 1} из {len(subtasks)}: {str(st.get('title') or 'шаг')[:120]}",
                )
                done = "\n".join(
                    f"- {r['title']}: {r['status']}; files={r['files_created']}; {r['summary']}"
                    for r in results
                ) or "(nothing yet)"
                canvas = (
                    serialize_scenario_for_llm(self.scenario)[:3000]
                    if (self.scenario or {}).get("blocks")
                    else "(empty canvas)"
                )
                prompt = SUBTASK_PROMPT.format(
                    goal=goal,
                    contract=contract,
                    plan=plan_lines,
                    done=done,
                    canvas=canvas,
                    index=i + 1,
                    total=len(subtasks),
                    title=str(st.get("title") or f"step {i + 1}"),
                    instructions=str(st.get("instructions") or "")[:8000],
                    files=", ".join(st.get("files") or []) or "(decide)",
                )
                before = len(self.actions)
                reply, executed = await self.provider.run_tool_loop(
                    [{"role": "user", "content": prompt}],
                    self.system_prompt,
                    sub_tools,
                    self.execute,
                    max_rounds=MAX_SUBTASK_STEPS,
                    max_tokens=SUBTASK_MAX_TOKENS,
                    split_tool=None,
                    temperature=0.2,
                    purpose=f"botcopilot-sub{i + 1}",
                    bot_id=self.bot_id,
                    model=self.worker_model or self.model,
                    on_event=self._sub_event,
                    should_stop=self.cancelled,
                )
                new_actions = self.actions[before:]
                files = sorted(
                    {str(p) for a in new_actions for p in (a.get("files_created") or []) if p}
                )
                failed_calls = [
                    e for e in executed
                    if isinstance(e.get("result"), dict) and e["result"].get("ok") is False
                ]
                if reply.startswith("SUBTASK_TOO_LARGE"):
                    status = "too_large"
                elif not new_actions:
                    status = "no_changes"
                else:
                    status = "done"
                missing = [
                    f for f in (st.get("files") or [])
                    if f and not any(str(x).endswith(str(f).lstrip("/")) for x in files)
                ]
                results.append(
                    {
                        "title": str(st.get("title") or f"step {i + 1}"),
                        "status": status,
                        "files_created": files,
                        "missing_files": missing,
                        "errors": [str(e["result"].get("error"))[:300] for e in failed_calls][:5],
                        "summary": truncate_reply(reply or "")[:400],
                    }
                )
                log.info("plan_task subtask %d/%d %s: %s files=%s",
                         i + 1, len(subtasks), results[-1]["title"], status, files)
                status_text = {"done": "готова", "no_changes": "без изменений",
                               "too_large": "слишком большая, будет разбита"}.get(status, status)
                self.progress(
                    "plan_done" if status == "done" else "warn",
                    f"Часть {i + 1} {status_text}" + (f": {', '.join(files)}" if files else ""),
                )
        finally:
            self.plan_depth -= 1

        verification = self._verify_written_files(
            sorted({f for r in results for f in r["files_created"]})
        )
        if verification["checked"]:
            self.progress(
                "plan_done" if verification["ok"] else "error",
                f"Проверка кода: {verification['checked']} файлов, ошибок {len(verification['errors'])}",
            )
        self.progress("plan", "Собираю части в одно целое")
        all_done = all(r["status"] == "done" and not r["missing_files"] for r in results)
        self.last_summary = f"Plan: {sum(r['status'] == 'done' for r in results)}/{len(results)} subtasks done"
        return {
            "ok": True,
            "all_done": all_done and verification["ok"],
            "subtasks": results,
            "verification": verification,
            "next_step": (
                "Assemble the result: connect the pieces (app_bridge via inspect_and_wire_app or "
                "patch_graph), fix every verification error and redo subtasks that are not done "
                "(call plan_task again for too_large ones). Then reply to the user."
            ),
        }

    def _sub_event(self, kind: str, text: str) -> None:
        # Per-round "thinking" noise of subtasks is not useful; keep warnings.
        if kind != "think":
            self.progress(kind, text)

    def _verify_written_files(self, rel_paths: list[str]) -> dict[str, Any]:
        """Syntax-check .py and parse .json files produced by subtasks."""
        import py_compile

        from backend.services.ai_tools import get_bot_workspace_dir

        if self.bot_id is None or not rel_paths:
            return {"ok": True, "checked": 0, "errors": []}
        root = get_bot_workspace_dir(self.bot_id)
        errors: list[str] = []
        for rel in rel_paths:
            path = root / rel
            if not path.is_file():
                errors.append(f"{rel}: missing on disk")
                continue
            try:
                if path.suffix == ".py":
                    py_compile.compile(str(path), doraise=True)
                elif path.suffix == ".json":
                    json.loads(path.read_text(encoding="utf-8"))
            except py_compile.PyCompileError as exc:
                errors.append(f"{rel}: {exc.msg.strip()[-400:]}")
            except (ValueError, OSError) as exc:
                errors.append(f"{rel}: {exc}")
        return {"ok": not errors, "checked": len(rel_paths), "errors": errors}

    def _workspace_guard(self, name: str, args: dict[str, Any]) -> dict[str, Any] | None:
        """
        File tools always target the session bot (validated by the /chat route).
        A model-supplied bot_id is ignored: it was the source of writes into
        invented folders such as projects/bot_default.
        """
        claimed = args.pop("bot_id", None) if isinstance(args, dict) else None
        if claimed not in (None, "") and str(claimed) != str(self.bot_id):
            log.warning(
                "tool %s: ignoring model bot_id=%r, session bot_id=%r", name, claimed, self.bot_id
            )
        if self.bot_id is None:
            return {
                "ok": False,
                "success": False,
                "error": (
                    "No bot workspace is open, files cannot be written. Do not invent a bot_id "
                    "and do not imitate scripts with message blocks; tell the user to open the "
                    "bot in the scenario editor and repeat the request."
                ),
            }
        return None

    async def execute(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        self.progress("tool", self._describe_tool(name, args if isinstance(args, dict) else {}))
        result = await self._dispatch(name, args)
        if isinstance(result, dict) and result.get("ok") is False:
            self.progress("error", f"Не получилось ({name}): {str(result.get('error'))[:160]}")
        return result

    async def _dispatch(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if name in _WORKSPACE_TOOLS:
            blocked = self._workspace_guard(name, args)
            if blocked:
                return blocked
        if name == "update_db_schema":
            return self._update_db_schema(args)
        if name == "patch_graph":
            return await self._patch_graph(args)
        if name == "create_custom_plugin":
            return await self._create_custom_plugin(args)
        if name == "inspect_and_wire_app":
            return self._inspect_and_wire_app(args)
        if name == "generate_standalone_app":
            return self._generate_standalone_app(args)
        if name == "write_workspace_file":
            return self._write_workspace_file(args)
        if name == "create_complete_standalone_app":
            return self._create_complete_standalone_app(args)
        if name == "plan_task":
            return await self._plan_task(args)
        return {"ok": False, "error": f"Unknown tool: {name}"}

    def _update_db_schema(self, args: dict[str, Any]) -> dict[str, Any]:
        variables = args.get("variables") if isinstance(args.get("variables"), dict) else {}
        cleaned: dict[str, str] = {}
        for k, v in variables.items():
            key = re.sub(r"[^a-zA-Z0-9_]", "_", str(k).strip())
            if not key:
                continue
            cleaned[key] = str(v)[:300]
        self.schema_vars.update(cleaned)
        action = {"tool": "update_db_schema", "variables": dict(cleaned)}
        self.actions.append(action)
        return {
            "ok": True,
            "variables": cleaned,
            "all_variables": dict(self.schema_vars),
            "hint": "Frontend should call BotBuilderDB.updateSchema(variables).",
        }

    async def _patch_graph(self, args: dict[str, Any]) -> dict[str, Any]:
        nodes_to_add = args.get("nodes_to_add") or args.get("add_blocks") or []
        edges_to_add = args.get("edges_to_add") or args.get("add_connections") or []
        nodes_to_update = args.get("nodes_to_update") or args.get("update_blocks") or []
        nodes_to_remove = args.get("nodes_to_remove") or args.get("remove_block_ids") or []
        layout_needed = args.get("layout_needed")
        if layout_needed is None:
            layout_needed = True
        mode = str(args.get("mode") or "").strip().lower()
        instruction = str(args.get("instruction") or args.get("summary") or "").strip()
        summary = str(args.get("summary") or "").strip()

        has_nodes = isinstance(nodes_to_add, list) and len(nodes_to_add) > 0
        has_updates = isinstance(nodes_to_update, list) and len(nodes_to_update) > 0
        has_edges = isinstance(edges_to_add, list) and len(edges_to_add) > 0
        has_removes = isinstance(nodes_to_remove, list) and len(nodes_to_remove) > 0

        catalog = build_plugin_catalog()
        allowed = catalog_types(catalog)

        if not (has_nodes or has_updates or has_edges or has_removes):
            # Delegate to structured scenario LLM
            if not mode:
                mode = autopilot_scenario_mode(self.scenario)
            if not instruction:
                instruction = "Обнови сценарий по запросу пользователя из истории."
            result = await _run_scenario_op(
                mode=mode,
                instruction=instruction,
                current_scenario=self.scenario,
                messages=self.messages,
                available_plugins=list(allowed),
            )
            self.scenario = result.get("scenario") or self.scenario
            self.last_mode = result.get("mode") or mode
            self.last_summary = str(result.get("summary") or summary)
            action = {
                "tool": "patch_graph",
                "mode": self.last_mode,
                "layout_needed": bool(layout_needed),
                "scenario": self.scenario,
                "summary": self.last_summary,
            }
            self.actions.append(action)
            return {
                "ok": True,
                "mode": self.last_mode,
                "summary": self.last_summary,
                "blocks_count": len((self.scenario or {}).get("blocks") or []),
                "connections_count": len((self.scenario or {}).get("connections") or []),
            }

        if not mode:
            mode = "replace" if (has_nodes and not (self.scenario.get("blocks") or [])) else "patch"

        if mode == "replace" and has_nodes:
            blocks = [_coerce_block(b, i) for i, b in enumerate(nodes_to_add) if isinstance(b, dict)]
            # Ensure start
            if not any(b.get("type") == "start" for b in blocks):
                blocks.insert(0, {"id": "start", "type": "start", "x": 100, "y": 100, "data": {}})
            conns = [
                _coerce_connection(e)
                for e in (edges_to_add if isinstance(edges_to_add, list) else [])
                if isinstance(e, dict)
            ]
            fixed = finalize_scenario(
                {"blocks": blocks, "connections": conns, "tags": self.scenario.get("tags") or []},
                allowed,
            )
            self.scenario = fixed
            self.last_mode = "replace"
            self.last_summary = summary or "Scenario replaced via patch_graph"
        else:
            patch_payload = {
                "summary": summary or "patch_graph",
                "add_blocks": [
                    _coerce_block(b, i) for i, b in enumerate(nodes_to_add) if isinstance(b, dict)
                ],
                "update_blocks": [
                    _coerce_block(b, i) for i, b in enumerate(nodes_to_update) if isinstance(b, dict)
                ],
                "remove_block_ids": [str(x) for x in nodes_to_remove if x and str(x) != "start"],
                "add_connections": [
                    _coerce_connection(e)
                    for e in (edges_to_add if isinstance(edges_to_add, list) else [])
                    if isinstance(e, dict)
                ],
                "remove_connection_ids": [],
            }
            fixed = apply_scenario_patch(self.scenario, patch_payload, allowed)
            self.scenario = fixed
            self.last_mode = "patch"
            self.last_summary = summary or "Scenario patched via patch_graph"

        action = {
            "tool": "patch_graph",
            "mode": self.last_mode,
            "layout_needed": bool(layout_needed),
            "scenario": self.scenario,
            "summary": self.last_summary,
            "nodes_added": len(nodes_to_add) if isinstance(nodes_to_add, list) else 0,
            "edges_added": len(edges_to_add) if isinstance(edges_to_add, list) else 0,
        }
        self.actions.append(action)
        return {
            "ok": True,
            "mode": self.last_mode,
            "summary": self.last_summary,
            "blocks_count": len((self.scenario or {}).get("blocks") or []),
            "connections_count": len((self.scenario or {}).get("connections") or []),
        }

    async def _create_custom_plugin(self, args: dict[str, Any]) -> dict[str, Any]:
        name = str(args.get("name") or "custom_plugin").strip()
        description = str(args.get("description") or "").strip()
        code = str(args.get("code") or "").strip()
        ui_json = args.get("ui_json") if isinstance(args.get("ui_json"), dict) else None

        # Strong preference: refuse if description clearly matches core plugins
        lower = (description + " " + name).lower()
        core_hints = (
            ("send text", "message"),
            ("send message", "message"),
            ("приветств", "message"),
            ("weather", "weather"),
            ("погод", "weather"),
            ("condition", "condition"),
            ("ветвлен", "condition"),
            ("menu", "menu"),
            ("меню", "menu"),
        )
        for needle, typ in core_hints:
            if needle in lower:
                return {
                    "ok": False,
                    "refused": True,
                    "error": (
                        f"Core plugin '{typ}' already covers this. "
                        f"Use patch_graph with type='{typ}' instead of create_custom_plugin."
                    ),
                }

        result = await _generate_and_save_plugin(
            description=description or name,
            plugin_name=name,
            context="",
            ai_notes=description,
            code=code,
            ui_json=ui_json,
        )
        self.plugin_created = {
            "plugin_name": result.get("plugin_name"),
            "ui_json": result.get("ui_json") or {},
            "saved_path": result.get("saved_path") or "",
        }
        action = {
            "tool": "create_custom_plugin",
            "plugin_created": self.plugin_created,
        }
        self.actions.append(action)

        # Auto-wire into scenario after plugin creation
        block_type = (
            (result.get("ui_json") or {}).get("type")
            or result.get("plugin_name")
            or name
        )
        mode = autopilot_scenario_mode(self.scenario)
        try:
            scenario_result = await _run_scenario_op(
                mode=mode,
                instruction=(
                    f"Плагин {block_type} только что создан. "
                    f"Встрой его в сценарий. Описание: {description}"
                ),
                current_scenario=self.scenario,
                messages=self.messages,
                available_plugins=list(result.get("plugins") or []),
            )
            self.scenario = scenario_result.get("scenario") or self.scenario
            self.last_mode = scenario_result.get("mode") or mode
            self.last_summary = str(scenario_result.get("summary") or "")
            self.actions.append(
                {
                    "tool": "patch_graph",
                    "mode": self.last_mode,
                    "scenario": self.scenario,
                    "summary": self.last_summary,
                    "after_plugin": block_type,
                }
            )
        except Exception as exc:
            return {
                "ok": True,
                "plugin_name": result.get("plugin_name"),
                "warning": f"Plugin saved but scenario wire failed: {exc}",
            }

        return {
            "ok": True,
            "plugin_name": result.get("plugin_name"),
            "block_type": block_type,
            "scenario_mode": self.last_mode,
            "blocks_count": len((self.scenario or {}).get("blocks") or []),
        }

    def _inspect_and_wire_app(self, args: dict[str, Any]) -> dict[str, Any]:
        folder = str(args.get("app_folder_path") or args.get("app_folder") or "").strip()
        if not folder:
            return {"ok": False, "error": "app_folder_path is required"}
        wire_msgs = args.get("wire_default_messages")
        if wire_msgs is None:
            wire_msgs = True
        try:
            result = inspect_and_wire_app(
                bot_id=self.bot_id,
                app_folder_path=folder,
                scenario=self.scenario,
                wire_default_messages=bool(wire_msgs),
            )
        except AppInspectorError as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:
            return {"ok": False, "error": f"inspect failed: {exc}"}

        catalog = build_plugin_catalog()
        allowed = catalog_types(catalog)
        # Ensure app_bridge is allowed even if catalog cache is stale
        allowed = set(allowed) | {"app_bridge", "message", "start"}
        fixed = finalize_scenario(result.get("scenario") or self.scenario, allowed)
        self.scenario = fixed
        self.last_mode = "patch"
        self.last_summary = str(
            args.get("summary") or result.get("summary") or "App bridge wired"
        )
        action = {
            "tool": "inspect_and_wire_app",
            "mode": "patch",
            "layout_needed": True,
            "scenario": self.scenario,
            "summary": self.last_summary,
            "bridge_id": result.get("bridge_id"),
            "analysis": result.get("analysis"),
        }
        self.actions.append(action)
        return {
            "ok": True,
            "bridge_id": result.get("bridge_id"),
            "summary": self.last_summary,
            "analysis": result.get("analysis"),
            "blocks_count": len((self.scenario or {}).get("blocks") or []),
            "connections_count": len((self.scenario or {}).get("connections") or []),
        }

    def _generate_standalone_app(self, args: dict[str, Any]) -> dict[str, Any]:
        app_name = str(args.get("app_name") or args.get("name") or "").strip()
        description = str(args.get("description") or "").strip()
        if not app_name:
            return {"ok": False, "error": "app_name is required"}
        python_files = args.get("python_files") if isinstance(args.get("python_files"), dict) else {}
        # If LLM omitted sources, synthesize a minimal async entrypoint from description
        if not python_files:
            safe_desc = (description or app_name).replace('"""', "'")[:400]
            python_files = {
                "main.py": (
                    f'"""{safe_desc}"""\n\n'
                    "async def main(**kwargs):\n"
                    "    # Standalone entrypoint — return ok + result dict\n"
                    "    return {\n"
                    '        "ok": True,\n'
                    f'        "result": {{"app": {app_name!r}, "kwargs": kwargs}},\n'
                    "    }\n"
                )
            }
        # Strip emojis from generated sources (RULE 9)
        cleaned_files: dict[str, str] = {}
        for k, v in python_files.items():
            text = str(v or "")
            text = re.sub(
                "[" 
                "\U0001F300-\U0001F9FF"
                "\U00002700-\U000027BF"
                "\U0001FA00-\U0001FAFF"
                "]+",
                "",
                text,
            )
            cleaned_files[str(k)] = text

        manifest = args.get("manifest") if isinstance(args.get("manifest"), dict) else None
        wire = args.get("wire")
        if wire is None:
            wire = True
        try:
            result = generate_and_wire_standalone_app(
                bot_id=self.bot_id,
                app_name=app_name,
                python_files=cleaned_files,
                manifest=manifest,
                description=description,
                scenario=self.scenario,
                wire=bool(wire),
            )
        except AppInspectorError as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:
            return {"ok": False, "error": f"generate failed: {exc}"}

        catalog = build_plugin_catalog()
        allowed = set(catalog_types(catalog)) | {"app_bridge", "message", "start"}
        if result.get("scenario"):
            fixed = finalize_scenario(result.get("scenario") or {}, allowed)
            self.scenario = fixed
            self.last_mode = "patch"
        self.last_summary = str(
            args.get("summary") or result.get("summary") or f"Generated {app_name}"
        )
        action = {
            "tool": "generate_standalone_app",
            "mode": self.last_mode or "patch",
            "layout_needed": True,
            "scenario": self.scenario,
            "summary": self.last_summary,
            "created": result.get("created") or {
                "app_folder_path": result.get("app_folder_path")
            },
            "bridge_id": result.get("bridge_id"),
        }
        self.actions.append(action)
        return {
            "ok": True,
            "summary": self.last_summary,
            "app_folder_path": (result.get("created") or {}).get("app_folder_path")
            or result.get("app_folder_path"),
            "bridge_id": result.get("bridge_id"),
            "blocks_count": len((self.scenario or {}).get("blocks") or []),
        }

    def _write_workspace_file(self, args: dict[str, Any]) -> dict[str, Any]:
        relative_path = str(args.get("relative_path") or args.get("path") or "").strip()
        content = args.get("content")
        if content is None:
            content = args.get("text") or ""
        bot_id = self.bot_id
        print(
            "[INFO] LOG: [AI Prompt Received] -> write_workspace_file "
            f"bot_id={bot_id!r} path={relative_path!r}"
        )
        result = write_workspace_file(
            bot_id=bot_id,
            relative_path=relative_path,
            content=str(content),
        )
        if not (result.get("ok") or result.get("success")):
            return result
        path = result.get("path") or result.get("relative_path")
        summary = str(
            args.get("summary") or result.get("summary") or f"Wrote {path}"
        )
        self.last_summary = summary
        files = list(result.get("files_created") or ([path] if path else []))
        action = {
            "tool": "write_workspace_file",
            "relative_path": path,
            "bytes": result.get("bytes"),
            "summary": summary,
            "files_created": files,
            "success": True,
            "path": path,
        }
        self.actions.append(action)
        return {
            "ok": True,
            "success": True,
            "path": path,
            "relative_path": path,
            "bytes": result.get("bytes"),
            "summary": summary,
            "files_created": files,
            "absolute_path": result.get("absolute_path"),
        }

    def _create_complete_standalone_app(self, args: dict[str, Any]) -> dict[str, Any]:
        bot_id = self.bot_id
        print(
            "[INFO] LOG: [AI Prompt Received] -> create_complete_standalone_app "
            f"bot_id={bot_id!r} app={args.get('app_name')!r}"
        )
        result = create_complete_standalone_app(
            bot_id=bot_id,
            app_name=str(args.get("app_name") or args.get("name") or ""),
            script_code=str(args.get("script_code") or args.get("code") or ""),
            manifest=args.get("manifest") if isinstance(args.get("manifest"), dict) else {},
            nodes_to_add=args.get("nodes_to_add")
            if isinstance(args.get("nodes_to_add"), list)
            else [],
            connections_to_add=args.get("connections_to_add")
            if isinstance(args.get("connections_to_add"), list)
            else [],
            scenario=self.scenario,
            wire_default_messages=bool(
                True if args.get("wire_default_messages") is None else args.get("wire_default_messages")
            ),
        )
        if not (result.get("ok") or result.get("success")):
            return result
        if result.get("scenario"):
            catalog = build_plugin_catalog()
            allowed = set(catalog_types(catalog)) | {"app_bridge", "message", "start", "command"}
            fixed = finalize_scenario(result.get("scenario") or {}, allowed)
            sanitize_scenario_connections(fixed)
            self.scenario = fixed
            self.last_mode = "patch"
        self.last_summary = str(
            args.get("summary") or result.get("summary") or "Standalone app created"
        )
        action = {
            "tool": "create_complete_standalone_app",
            "mode": self.last_mode or "patch",
            "layout_needed": True,
            "scenario": self.scenario,
            "summary": self.last_summary,
            "files_created": result.get("files_created") or [],
            "nodes_added": result.get("nodes_added") or 0,
            "app_folder_path": result.get("app_folder_path"),
            "connections_removed": len(result.get("connections_removed") or []),
            "refresh_canvas": True,
            "refresh_repo": True,
            "success": True,
        }
        self.actions.append(action)
        return {
            "ok": True,
            "success": True,
            "files_created": result.get("files_created") or [],
            "nodes_added": result.get("nodes_added") or 0,
            "connections_removed": len(result.get("connections_removed") or []),
            "app_folder_path": result.get("app_folder_path"),
            "summary": self.last_summary,
            "blocks_count": len((self.scenario or {}).get("blocks") or []),
        }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/status")
async def ai_status():
    cfg = load_ai_config()
    catalog = build_plugin_catalog()
    return {
        "enabled": bool(cfg.enabled and cfg.api_key),
        "configured": bool(cfg.api_key),
        "endpoint": cfg.endpoint,
        "provider": cfg.provider,
        "model": cfg.model,
        "models": {
            "planner": cfg.model_planner,
            "coder": cfg.model_coder,
            "worker": cfg.model_for_role("worker"),
            "scenario": cfg.model_scenario,
        },
        "plugins": [c["type"] for c in catalog],
        "plugin_catalog": catalog,
        "agent": "BotCopilot",
        "tools": [t["function"]["name"] for t in BOTCOPILOT_TOOLS],
    }


@router.get("/chat/{bot_id}")
async def ai_chat_history_get(bot_id: str):
    msgs = ai_chat_history.list_messages(bot_id)
    return {"bot_id": bot_id, "messages": msgs}


@router.delete("/chat/{bot_id}")
async def ai_chat_history_delete(bot_id: str):
    n = ai_chat_history.clear_history(bot_id)
    return {"ok": True, "bot_id": bot_id, "deleted": n}


@router.post("/runtime-errors")
async def ai_runtime_error_ingest(body: dict[str, Any]):
    """Ingest a structured node-execution error from a running bot process."""
    event = bot_error_registry.push(body if isinstance(body, dict) else {})
    if not event:
        raise HTTPException(status_code=400, detail="invalid error payload")
    return {"ok": True, "bot_id": event.get("bot_id"), "node_id": event.get("failing_node_id")}


@router.get("/runtime-errors/{bot_id}")
async def ai_runtime_errors_list(bot_id: str, limit: int = 20):
    return {
        "bot_id": bot_id,
        "errors": bot_error_registry.get_recent_errors(bot_id, limit=limit),
    }


@router.delete("/runtime-errors/{bot_id}")
async def ai_runtime_errors_clear(bot_id: str):
    n = bot_error_registry.clear(bot_id)
    return {"ok": True, "bot_id": bot_id, "deleted": n}


async def _resolve_session_bot_id(
    raw: str | int | None, user_id: int, db: AsyncSession
) -> int | None:
    """Only a real, accessible numeric bot may become the agent's workspace."""
    if raw is None or str(raw).strip() == "":
        return None
    text = str(raw).strip()
    if not text.isdigit() or int(text) < 1:
        raise HTTPException(status_code=400, detail=f"Invalid bot_id: {text!r}")
    bot_id = int(text)
    await require_bot_access(db, bot_id, user_id)
    return bot_id


@router.get("/progress/{request_id}")
async def ai_chat_progress(request_id: str, after: int = -1):
    """Step log of a running /chat request; the panel polls it while busy."""
    return ai_progress.snapshot(request_id, after=after)


@router.post("/cancel/{request_id}")
async def ai_chat_cancel(request_id: str):
    return {"ok": ai_progress.cancel(request_id)}


@router.post("/chat")
async def ai_chat(
    body: ChatPayload,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await _ai_chat_impl(body, user_id, db)
    finally:
        ai_progress.finish((body.request_id or "").strip() or None)


async def _ai_chat_impl(body: ChatPayload, user_id: int, db: AsyncSession):
    try:
        cfg = require_ai_ready()
    except ValueError as exc:
        msg = str(exc)
        code = 403 if "disabled" in msg.lower() else 400
        raise HTTPException(status_code=code, detail=msg) from exc

    body.bot_id = await _resolve_session_bot_id(body.bot_id, user_id, db)
    if body.bot_id is None:
        log.warning("ai_chat without bot_id: workspace file tools are disabled for this turn")

    # Merge persisted history + request messages
    stored: list[dict[str, Any]] = []
    if body.bot_id is not None:
        stored = ai_chat_history.list_messages(body.bot_id)

    req_msgs = _normalize_chat_messages(body.messages)
    if body.message and body.message.strip():
        req_msgs = [*req_msgs, {"role": "user", "content": body.message.strip()}]

    if stored:
        # Prefer stored history; append only the newest user turn from request if missing
        base = [
            {"role": m["role"], "content": m["content"]}
            for m in stored
            if m.get("role") in ("user", "assistant") and m.get("content")
        ]
        if req_msgs:
            last_req = req_msgs[-1]
            if last_req["role"] == "user" and (
                not base or base[-1].get("content") != last_req["content"]
            ):
                base.append(last_req)
                if body.bot_id is not None:
                    ai_chat_history.append_message(body.bot_id, "user", last_req["content"])
        msgs = base[-MAX_CHAT_TURNS:]
    else:
        msgs = req_msgs
        if body.bot_id is not None and msgs:
            # Persist fresh conversation (user turns already in msgs; we'll save assistant later)
            # Save only the latest user message to avoid duplicating full client history
            last_user = next((m for m in reversed(msgs) if m["role"] == "user"), None)
            if last_user:
                # If client sent full history first time, replace store
                ai_chat_history.replace_history(body.bot_id, msgs)

    if not msgs:
        raise HTTPException(status_code=400, detail="messages required")

    catalog = build_plugin_catalog()
    user_text = extract_latest_user_text(
        "",
        [{"role": m["role"], "content": m["content"]} for m in msgs],
    )
    system = _build_meta_context(
        catalog,
        body.current_scenario,
        bot_id=body.bot_id,
        user_text=user_text,
    )
    recent = bot_error_registry.get_recent_errors(body.bot_id, limit=3)
    if recent and body.auto_pilot:
        system = (
            system
            + "\n\nACTIVE RUNTIME ERRORS PRESENT. Prefer patch_graph to repair "
            "the failing_node_id from RECENT RUNTIME ERRORS before other work."
        )
    provider = AIProvider(cfg)
    state = _AgentState(
        current_scenario=body.current_scenario,
        messages=msgs,
        bot_id=body.bot_id,
    )
    state.provider = provider
    state.system_prompt = system
    state.model = cfg.model_for_role("planner")
    state.worker_model = cfg.model_for_role("worker")
    state.request_id = (body.request_id or "").strip() or None
    ai_progress.start(state.request_id)
    state.progress("think", "Читаю запрос")

    from backend.services.ai_intent import user_requests_script_creation

    if user_requests_script_creation(user_text):
        print(
            "[INFO] LOG: [AI Prompt Received] -> User asks for script creation."
        )

    reply = ""
    try:
        reply, executed = await provider.run_tool_loop(
            msgs,
            system,
            BOTCOPILOT_TOOLS,
            state.execute,
            max_rounds=MAX_AGENT_STEPS,
            temperature=0.25,
            purpose="botcopilot",
            bot_id=body.bot_id,
            model=cfg.model_for_role("planner"),
            split_tool="plan_task",
            on_event=state.progress,
            should_stop=state.cancelled,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Agent failed: {exc}") from exc

    reply = truncate_reply(reply or "")
    if not reply:
        if state.actions:
            reply = format_autopilot_status(
                mode=state.last_mode,
                plugin_name=(state.plugin_created or {}).get("plugin_name"),
                summary=state.last_summary,
            )
        else:
            reply = NO_ACTION_REPLY

    # Safety net: markdown code blocks → physical scripts/ files
    already_wrote = any(
        (a or {}).get("tool")
        in (
            "write_workspace_file",
            "generate_standalone_app",
            "inspect_and_wire_app",
            "create_complete_standalone_app",
        )
        for a in state.actions
    )
    autosaved = maybe_autosave_code_blocks(
        bot_id=body.bot_id,
        user_text=user_text,
        reply=reply,
        already_wrote=already_wrote,
    )
    for item in autosaved:
        state.actions.append(
            {
                "tool": "write_workspace_file",
                "relative_path": item.get("relative_path"),
                "bytes": item.get("bytes"),
                "summary": item.get("summary") or f"Autosaved {item.get('relative_path')}",
                "files_created": item.get("files_created")
                or [item.get("relative_path")],
                "autosave": True,
            }
        )
        state.last_summary = str(item.get("summary") or state.last_summary)

    if (
        not state.actions
        and not reply.startswith("Изменения не применены")
        and _CLAIMS_DONE_RE.search(reply)
    ):
        reply = f"{reply}\n\n{NO_ACTION_NOTE}"

    files_created: list[str] = []
    for a in state.actions:
        for p in a.get("files_created") or []:
            if p and p not in files_created:
                files_created.append(str(p))
        # generate_standalone_app may nest written_files
        created = a.get("created") if isinstance(a.get("created"), dict) else {}
        for p in created.get("written_files") or []:
            if p and p not in files_created:
                files_created.append(str(p))
        rel = a.get("relative_path")
        if a.get("tool") == "write_workspace_file" and rel and rel not in files_created:
            files_created.append(str(rel))

    # Enrich status if tools ran
    if state.actions and "Auto-Pilot" not in reply:
        status = format_autopilot_status(
            mode=state.last_mode,
            plugin_name=(state.plugin_created or {}).get("plugin_name"),
            summary=state.last_summary,
        )
        reply = truncate_reply(f"{status}\n{reply}".strip())

    undoable = bool(state.scenario and state.actions)
    meta: dict[str, Any] = {
        "undoable": undoable,
        "actions": [
            {k: v for k, v in a.items() if k != "scenario"}
            for a in state.actions
        ],
        "files_created": files_created,
    }
    if body.bot_id is not None:
        ai_chat_history.append_message(body.bot_id, "assistant", reply, meta=meta)

    out: dict[str, Any] = {
        "reply": reply,
        "intent": "answer",
        "auto_pilot": True,
        "auto_executed": bool(state.actions),
        "undoable": undoable,
        "actions": state.actions,
        "files_created": files_created,
        "refresh_canvas": bool(state.scenario and state.actions)
        or any(a.get("refresh_canvas") for a in state.actions),
        "refresh_repo": bool(files_created) or any(a.get("refresh_repo") for a in state.actions),
        "tool_calls": [
            {"name": a.get("tool"), "summary": a.get("summary") or a.get("plugin_created")}
            for a in state.actions
        ],
        "schema_updates": dict(state.schema_vars) if state.schema_vars else None,
        "plugin_created": state.plugin_created,
        "scenario": state.scenario if state.actions and state.scenario else None,
        "mode": state.last_mode,
        "summary": state.last_summary,
        "available_plugins": [c["type"] for c in catalog],
        "plugin_catalog": catalog,
        # Hide legacy confirmation cards
        "plugin_suggestion": None,
        "scenario_action": None,
    }
    if out["scenario"]:
        out["blocks"] = out["scenario"].get("blocks")
        out["connections"] = out["scenario"].get("connections")
        out["required_plugins"] = out["scenario"].get("required_plugins") or []
    return out


@router.post("/generate-plugin")
async def ai_generate_plugin(body: GeneratePluginPayload):
    try:
        require_ai_ready()
    except ValueError as exc:
        msg = str(exc)
        code = 403 if "disabled" in msg.lower() else 400
        raise HTTPException(status_code=code, detail=msg) from exc

    return await _generate_and_save_plugin(
        description=body.description,
        plugin_name=body.plugin_name,
        context=body.context,
        ai_notes=body.ai_notes,
    )


@router.post("/scenario-op")
async def ai_scenario_op(body: ScenarioOpPayload):
    return await _run_scenario_op(
        mode=body.mode,
        instruction=body.instruction,
        current_scenario=body.current_scenario or {},
        messages=body.messages,
        available_plugins=body.available_plugins,
    )


@router.post("/generate-scenario")
async def ai_generate_scenario(body: GenerateScenarioPayload):
    """Legacy endpoint — always replace mode."""
    return await _run_scenario_op(
        mode="replace",
        instruction=body.description,
        current_scenario=body.current_scenario or {},
        messages=body.messages,
        available_plugins=body.available_plugins,
    )
