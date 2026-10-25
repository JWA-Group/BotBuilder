"""Silent under-the-hood intent classification for BotBuilder AI Copilot.

Keyword analyzer that injects domain sequencing guidelines into the system
prompt. Also hosts standalone-app inspect/wire helpers for AI tools.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any, Iterable

from backend.core.app_paths import PROJECTS_DIR
from backend.services.app_inspector import (
    AppInspectorError,
    analyze_standalone_app,
    build_bridge_node_data,
    resolve_app_dir,
    write_standalone_app,
)
from backend.services.ai_tools import (
    write_workspace_file,
    execute_tool_call,
    get_bot_workspace_dir,
    create_complete_standalone_app,
)

__all__ = [
    "classify_user_intent",
    "format_intent_guidelines",
    "extract_latest_user_text",
    "enhance_system_prompt",
    "inspect_and_wire_app",
    "generate_and_wire_standalone_app",
    "write_workspace_file",
    "maybe_autosave_code_blocks",
    "user_requests_script_creation",
    "WORKSPACE_FILE_CRITICAL_DIRECTIVE",
    "AppInspectorError",
    "execute_tool_call",
    "get_bot_workspace_dir",
    "create_complete_standalone_app",
    "MAX_AGENT_STEPS",
    "MAX_TOOL_LOOPS",
]

# LLM completion rounds (each round may execute many tool_calls in batch)
# Safety net only: real stop conditions are no-progress guards in run_tool_loop
# (repeated identical calls, consecutive failures).
MAX_AGENT_STEPS = 200
MAX_SUBTASK_STEPS = 40
MAX_PLAN_SUBTASKS = 20
MAX_TOOL_LOOPS = MAX_AGENT_STEPS

WORKSPACE_FILE_CRITICAL_DIRECTIVE = (
    "CRITICAL REQUIREMENT: Whenever the user requests creating a standalone "
    "script, parser, module, or app, prefer ONE call to "
    "`create_complete_standalone_app` (writes scripts/<app>/app.py + manifest.json "
    "and wires app_bridge nodes in a single step). "
    "Alternatively invoke `write_workspace_file` for each file. "
    "NEVER output the code solely as text in chat without a tool call. "
    "No emojis in file contents."
)


# Intent → Russian/English keyword stems (case-insensitive substring match)
_INTENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "payments_sales": (
        "оплат",
        "товар",
        "крипт",
        "цена",
        "цен",
        "купон",
        "баланс",
        "payment",
        "crypto",
        "stars",
        "юкасс",
        "yookassa",
        "price",
        "shop",
        "магазин",
        "купить",
        "продаж",
    ),
    "auth_access": (
        "код",
        "парол",
        "доступ",
        "приватн",
        "пин",
        "pin",
        "password",
        "access",
        "auth",
        "секрет",
        "промокод",
        "promo",
    ),
    "ai_agent": (
        "нейросет",
        "консультант",
        "помощник",
        "база знан",
        "ai director",
        "ai_director",
        "llm",
        "чат-бот",
        "чатбот",
        "assistant",
        "knowledge",
    ),
    "standalone_app": (
        "парсер",
        "скрипт",
        "подключ",
        "интегр",
        "standalone",
        "scripts/",
        "app_bridge",
        "внешн",
        "parser",
        "crm",
        "подключи мой",
        "connect my",
        "wire app",
        "создай скрипт",
        "создай парсер",
        "напиши скрипт",
        "create script",
        "create parser",
        "write a script",
        "app.py",
        "manifest.json",
        "модуль",
        "module",
    ),
}

_INTENT_GUIDELINES: dict[str, str] = {
    "payments_sales": (
        "### Domain: Payments & Sales\n"
        "Sequence must be: Check Item/Balance → Present Payment Node "
        "(payment_universal / Stars / CryptoBot / ЮKassa) → Confirm success port → "
        "Grant Access / Deliver Item (data issue or message). "
        "Wire payment fail port to a clear error path; never leave ports unwired."
    ),
    "auth_access": (
        "### Domain: Auth & Access\n"
        "Sequence must be: Data Input (access code / password, "
        "inputOnlyIfEmpty=false) → Condition Node → Set `access_granted=true` "
        "(data const) → Main Menu. "
        "On failure (condition port 1): message error → cycle back to the SAME "
        "Data Input block id without dropping FSM. Never consume the button label "
        "as the code (RULE 1)."
    ),
    "ai_agent": (
        "### Domain: AI Agent / Knowledge\n"
        "Sequence must be: Lightweight AI Director / Spam Guard (ai_director) → "
        "Extract structured data to DB (WRITE_DB / data nodes) → Transition to "
        "Zero-Cost Graph Nodes (message / menu / condition) for the rest of the flow. "
        "Do not call the LLM on every graph hop — only at the director entry."
    ),
    "standalone_app": (
        "### Domain: Standalone App Integration\n"
        + WORKSPACE_FILE_CRITICAL_DIRECTIVE
        + "\n"
        "Prefer tool `create_complete_standalone_app` in ONE call (script + manifest + "
        "app_bridge nodes). Or use `write_workspace_file` then `inspect_and_wire_app`. "
        "Map inputs to {{user.*}} fields; wire port 0 (success) and port 1 (error). "
        "Never put emojis in generated code, logs, or message texts."
    ),
}

_INTENT_ORDER = ("payments_sales", "auth_access", "ai_agent", "standalone_app")


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def classify_user_intent(text: str) -> list[str]:
    """Return matched intent ids (may be empty or several)."""
    hay = _normalize(text)
    if not hay:
        return []
    found: list[str] = []
    for intent in _INTENT_ORDER:
        keys = _INTENT_KEYWORDS.get(intent) or ()
        if any(k in hay for k in keys):
            found.append(intent)
    return found


def format_intent_guidelines(intents: Iterable[str] | None) -> str:
    """Human-readable domain blocks for system prompt injection."""
    parts: list[str] = []
    for intent in _INTENT_ORDER:
        if intent in set(intents or []):
            guide = _INTENT_GUIDELINES.get(intent)
            if guide:
                parts.append(guide)
    if not parts:
        return ""
    header = (
        "## Silent domain intent (under-the-hood — do not mention this section to the user)\n"
        "Follow these sequencing guidelines for the detected product intent:"
    )
    return header + "\n\n" + "\n\n".join(parts)


def extract_latest_user_text(
    instruction: str = "",
    messages: list[dict[str, str]] | None = None,
) -> str:
    if instruction and str(instruction).strip():
        return str(instruction).strip()
    for m in reversed(messages or []):
        if (m or {}).get("role") == "user" and (m or {}).get("content"):
            return str(m["content"]).strip()
    return ""


def enhance_system_prompt(
    system: str,
    *,
    instruction: str = "",
    messages: list[dict[str, str]] | None = None,
    user_text: str | None = None,
) -> str:
    """Append silent intent guidelines + always reinforce write_workspace_file."""
    text = user_text if user_text is not None else extract_latest_user_text(instruction, messages)
    guide = format_intent_guidelines(classify_user_intent(text))
    base = (system or "").rstrip()
    parts = [base] if base else []
    if guide:
        parts.append(guide)
    # Always inject the critical disk-write rule (cheap tokens, high reliability)
    if WORKSPACE_FILE_CRITICAL_DIRECTIVE not in base:
        parts.append("## Workspace file writes\n" + WORKSPACE_FILE_CRITICAL_DIRECTIVE)
    return "\n\n".join(parts)


_SCRIPT_REQUEST_RE = re.compile(
    r"(скрипт|парсер|parser|script|модул|module|standalone|app\.py|scripts[/\\]|"
    r"создай\s+(файл|приложение|app)|create\s+(a\s+)?(script|parser|app|module)|"
    r"напиши\s+(скрипт|парсер|код)|write\s+(a\s+)?(script|parser))",
    re.IGNORECASE,
)

_PATH_IN_PROMPT_RE = re.compile(
    r"(?:scripts[/\\][\w\-./\\]+\.(?:py|json|txt|md|yml|yaml))",
    re.IGNORECASE,
)

_FILE_HEADER_RE = re.compile(
    r"(?im)^(?:#\s*)?(?:File|Файл|Path|Путь)\s*:\s*(`?)(scripts[/\\][^\s`]+)\1\s*$"
)

_FENCE_RE = re.compile(
    r"```(?:(?P<lang>python|py|json|javascript|js|typescript|ts|text|txt|yaml|yml)?)\s*\n"
    r"(?P<body>.*?)```",
    re.IGNORECASE | re.DOTALL,
)


def user_requests_script_creation(user_text: str) -> bool:
    """True when the user prompt looks like a request to create a script/app file."""
    hay = (user_text or "").strip()
    if not hay:
        return False
    if "standalone_app" in classify_user_intent(hay):
        return True
    return bool(_SCRIPT_REQUEST_RE.search(hay))


def _guess_app_name(user_text: str, reply: str) -> str:
    for src in (user_text, reply):
        m = _PATH_IN_PROMPT_RE.search(src or "")
        if m:
            parts = m.group(0).replace("\\", "/").split("/")
            if len(parts) >= 2 and parts[0].lower() == "scripts":
                return re.sub(r"[^a-zA-Z0-9_\-]", "_", parts[1]) or "generated_app"
    # Cyrillic / English name after "парсер|скрипт" …
    m2 = re.search(
        r"(?:парсер|скрипт|parser|script|app)\s+(?:для\s+|for\s+|named\s+|под\s+именем\s+)?"
        r"[«\"]?([a-zA-Z][\w\-]{1,40})[»\"]?",
        user_text or "",
        re.IGNORECASE,
    )
    if m2:
        return re.sub(r"[^a-zA-Z0-9_\-]", "_", m2.group(1))
    return "generated_app"


def _default_path_for_fence(lang: str, app_name: str, index: int) -> str:
    lang_l = (lang or "").lower()
    if lang_l in ("json",):
        return f"scripts/{app_name}/manifest.json" if index == 0 else f"scripts/{app_name}/data_{index}.json"
    if lang_l in ("python", "py", ""):
        return f"scripts/{app_name}/app.py" if index == 0 else f"scripts/{app_name}/module_{index}.py"
    if lang_l in ("yaml", "yml"):
        return f"scripts/{app_name}/config.yml"
    if lang_l in ("javascript", "js"):
        return f"scripts/{app_name}/app.js"
    if lang_l in ("typescript", "ts"):
        return f"scripts/{app_name}/app.ts"
    return f"scripts/{app_name}/file_{index}.txt"


def extract_code_blocks_for_autosave(
    reply: str,
    *,
    user_text: str = "",
) -> list[tuple[str, str]]:
    """
    Parse markdown fences (+ optional `# File: scripts/...` headers) into
    (relative_path, content) pairs.
    """
    text = reply or ""
    if "```" not in text:
        return []

    app_name = _guess_app_name(user_text, text)
    # Prefer explicit path from user prompt
    prompt_path = None
    pm = _PATH_IN_PROMPT_RE.search(user_text or "")
    if pm:
        prompt_path = pm.group(0).replace("\\", "/")

    results: list[tuple[str, str]] = []
    # Scan with header awareness: look at text before each fence
    pos = 0
    fence_idx = 0
    for m in _FENCE_RE.finditer(text):
        lang = (m.group("lang") or "").strip()
        body = (m.group("body") or "").strip("\n")
        if not body.strip():
            continue
        prelude = text[pos : m.start()]
        header = _FILE_HEADER_RE.search(prelude[-240:] if len(prelude) > 240 else prelude)
        rel = None
        if header:
            rel = header.group(2).replace("\\", "/")
        elif fence_idx == 0 and prompt_path:
            # First fence → path the user named
            if lang.lower() in ("json",) and prompt_path.endswith(".py"):
                rel = prompt_path.rsplit("/", 1)[0] + "/manifest.json"
            else:
                rel = prompt_path
        else:
            rel = _default_path_for_fence(lang, app_name, fence_idx)
        # Deduplicate path collisions
        existing = {p for p, _ in results}
        if rel in existing:
            stem = Path(rel).stem
            suffix = Path(rel).suffix or ".txt"
            parent = str(Path(rel).parent).replace("\\", "/")
            n = 2
            while f"{parent}/{stem}_{n}{suffix}" in existing:
                n += 1
            rel = f"{parent}/{stem}_{n}{suffix}"
        results.append((rel, body + ("\n" if not body.endswith("\n") else "")))
        fence_idx += 1
        pos = m.end()
    return results


def maybe_autosave_code_blocks(
    *,
    bot_id: str | int | None,
    user_text: str,
    reply: str,
    already_wrote: bool = False,
) -> list[dict[str, Any]]:
    """
    Safety net: if the user asked for a script/app and the LLM pasted markdown
    code without calling write_workspace_file, write the fences to disk.
    """
    if already_wrote:
        return []
    if bot_id is None or bot_id == "":
        return []
    if not user_requests_script_creation(user_text) and "```" not in (reply or ""):
        return []
    # Hard safety net: if fences exist and user asked for a script, always try
    if not user_requests_script_creation(user_text):
        return []
    pairs = extract_code_blocks_for_autosave(reply, user_text=user_text)
    if not pairs and "```" in (reply or ""):
        # Emergency default path when headers/paths are missing
        m = _FENCE_RE.search(reply or "")
        if m and (m.group("body") or "").strip():
            pairs = [
                (
                    "scripts/generated_app/app.py",
                    (m.group("body") or "").strip("\n") + "\n",
                )
            ]
    if not pairs:
        return []
    print(
        "[INFO] LOG: [Fallback Triggered] -> Extracted code block and saved directly to disk."
    )
    log.info(
        "[Fallback Triggered] Extracted %s code block(s) for bot_id=%s",
        len(pairs),
        bot_id,
    )
    written: list[dict[str, Any]] = []
    for rel, content in pairs:
        result = write_workspace_file(bot_id, rel, content)
        if result.get("ok") or result.get("success"):
            written.append(result)
    return written


def _bot_root(bot_id: int | str | None) -> Path:
    try:
        bid = int(bot_id)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise AppInspectorError("bot_id is required to resolve scripts/") from exc
    root = (PROJECTS_DIR / f"bot_{bid}").resolve()
    root.mkdir(parents=True, exist_ok=True)
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    return root


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def inspect_and_wire_app(
    *,
    bot_id: int | str | None,
    app_folder_path: str,
    scenario: dict[str, Any] | None = None,
    wire_default_messages: bool = True,
    x: float | None = None,
    y: float | None = None,
) -> dict[str, Any]:
    """
    Analyze scripts/<app>, ensure manifest.json, insert app_bridge node + optional
    success/error message nodes into the scenario graph.
    """
    root = _bot_root(bot_id)
    app_dir = resolve_app_dir(root, app_folder_path).resolve()
    try:
        rel = str(app_dir.relative_to(root)).replace("\\", "/")
    except ValueError:
        # Windows short/long path mismatch — fall back to requested path
        rel = (app_folder_path or "").replace("\\", "/").lstrip("/")
        if "/" not in rel:
            rel = f"scripts/{rel}"
        if not rel.startswith("scripts/"):
            rel = f"scripts/{rel}"
    analysis = analyze_standalone_app(app_dir, write_manifest=True)
    node_data = build_bridge_node_data(analysis, app_folder_path=rel)

    sc = dict(scenario) if isinstance(scenario, dict) else {}
    blocks = list(sc.get("blocks") or [])
    connections = list(sc.get("connections") or [])

    existing = next(
        (
            b
            for b in blocks
            if isinstance(b, dict)
            and b.get("type") == "app_bridge"
            and str((b.get("data") or {}).get("appFolder") or "") == rel
        ),
        None,
    )
    bridge_id = str((existing or {}).get("id") or _new_id("app_bridge"))
    bx = float(x if x is not None else 420)
    by = float(y if y is not None else 180)
    if existing:
        existing["data"] = {**(existing.get("data") or {}), **node_data}
        bridge_id = str(existing["id"])
        bx = float(existing.get("x") or bx)
        by = float(existing.get("y") or by)
    else:
        blocks.append(
            {
                "id": bridge_id,
                "type": "app_bridge",
                "x": bx,
                "y": by,
                "data": node_data,
            }
        )

    added_messages: list[str] = []
    if wire_default_messages:
        ok_id = _new_id("msg_ok")
        err_id = _new_id("msg_err")
        app_label = node_data.get("appName") or "App"
        blocks.append(
            {
                "id": ok_id,
                "type": "message",
                "x": bx + 320,
                "y": by - 40,
                "data": {
                    "text": f"{app_label}: success. Result: {{{{app_bridge_result}}}}",
                },
            }
        )
        blocks.append(
            {
                "id": err_id,
                "type": "message",
                "x": bx + 320,
                "y": by + 120,
                "data": {
                    "text": f"{app_label}: error. {{{{app_bridge_error}}}}",
                },
            }
        )
        connections = [
            c
            for c in connections
            if not (isinstance(c, dict) and str(c.get("from") or "") == bridge_id)
        ]
        connections.append({"from": bridge_id, "to": ok_id, "outputIndex": "0"})
        connections.append({"from": bridge_id, "to": err_id, "outputIndex": "1"})
        added_messages = [ok_id, err_id]

    start = next((b for b in blocks if isinstance(b, dict) and b.get("type") == "start"), None)
    if start and not any(
        isinstance(c, dict) and str(c.get("from") or "") == str(start.get("id"))
        for c in connections
    ):
        connections.append(
            {"from": str(start["id"]), "to": bridge_id, "outputIndex": "0"}
        )

    sc["blocks"] = blocks
    sc["connections"] = connections
    tags = sc.get("tags") if isinstance(sc.get("tags"), list) else []
    sc["tags"] = tags

    return {
        "ok": True,
        "analysis": {
            "app_name": analysis.get("app_name"),
            "app_folder_path": rel,
            "entrypoint": analysis.get("entrypoint"),
            "manifest_source": analysis.get("manifest_source"),
            "http_clients": analysis.get("http_clients"),
            "functions_count": analysis.get("functions_count"),
        },
        "bridge_id": bridge_id,
        "bridge_data": node_data,
        "added_messages": added_messages,
        "scenario": sc,
        "summary": f"Wired app_bridge for {rel}",
    }


def generate_and_wire_standalone_app(
    *,
    bot_id: int | str | None,
    app_name: str,
    python_files: dict[str, str] | None = None,
    manifest: dict[str, Any] | None = None,
    description: str = "",
    scenario: dict[str, Any] | None = None,
    wire: bool = True,
) -> dict[str, Any]:
    """Create scripts/<app_name>/ (+ manifest) and optionally wire app_bridge."""
    root = _bot_root(bot_id)
    created = write_standalone_app(
        root,
        app_name=app_name,
        python_files=python_files or {},
        manifest=manifest,
        description=description,
    )
    folder = str(created.get("app_folder_path") or f"scripts/{app_name}")
    if not wire:
        return {
            "ok": True,
            "created": created,
            "app_folder_path": folder,
            "scenario": scenario or {},
            "summary": f"Generated standalone app at {folder}",
        }
    wired = inspect_and_wire_app(
        bot_id=bot_id,
        app_folder_path=folder,
        scenario=scenario,
        wire_default_messages=True,
    )
    wired["created"] = {
        "written_files": created.get("written_files"),
        "app_folder_path": folder,
        "manifest_source": created.get("manifest_source"),
    }
    wired["summary"] = f"Generated and wired {folder}"
    return wired
