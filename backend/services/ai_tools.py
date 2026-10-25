"""AI Copilot physical workspace tools — safe file writes under bot project root."""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from backend.core.app_paths import PROJECTS_DIR

log = logging.getLogger(__name__)

# Deny absolute paths, traversal, and sensitive filenames
_UNSAFE_NAME = re.compile(r"(^|[\\/])\.\.([\\/]|$)")
_ALLOWED_SUFFIXES = frozenset(
    {
        ".py",
        ".json",
        ".txt",
        ".md",
        ".yml",
        ".yaml",
        ".toml",
        ".ini",
        ".cfg",
        ".csv",
        ".html",
        ".css",
        ".js",
        ".ts",
        ".env.example",
    }
)


def get_bot_workspace_dir(bot_id: str | int | None) -> Path:
    """
    Resolve absolute bot workspace root under PROJECTS_DIR (42 -> bot_42).

    Only positive numeric ids are accepted: string labels used to create
    phantom workspaces (bot_default, bot_test_bot) that no bot ever reads.
    """
    if bot_id is None or str(bot_id).strip() == "":
        raise ValueError("bot_id is required to resolve workspace")
    raw = str(bot_id).strip()
    if raw.startswith("bot_"):
        raw = raw[4:]
    if not raw.isdigit() or int(raw) < 1:
        raise ValueError(f"bot_id must be a positive integer, got {bot_id!r}")
    root = (PROJECTS_DIR / f"bot_{int(raw)}").resolve()
    os.makedirs(root, exist_ok=True)
    os.makedirs(root / "scripts", exist_ok=True)
    return root


# Backward-compatible alias
_bot_workspace_dir = get_bot_workspace_dir


def _is_allowed_suffix(name: str) -> bool:
    lower = name.lower()
    if lower.endswith(".env.example"):
        return True
    return Path(lower).suffix in _ALLOWED_SUFFIXES


def write_workspace_file(
    bot_id: str | int | None,
    relative_path: str,
    content: str,
) -> dict[str, Any]:
    """
    Safely write a text file inside the bot workspace (projects/bot_<id>/).

    Prefer paths under scripts/, e.g. scripts/book_parser/app.py or
    scripts/book_parser/manifest.json. Creates parent directories as needed.
    """
    try:
        workspace_dir = get_bot_workspace_dir(bot_id)
    except ValueError as exc:
        msg = str(exc)
        print(f"[ERROR] LOG: [Tool Execution Error] -> Exception: {msg}")
        log.error("[Tool Execution Error] workspace resolve failed: %s", msg)
        return {"ok": False, "success": False, "error": msg}

    rel = (relative_path or "").strip().replace("\\", "/").lstrip("/")
    if not rel:
        return {"ok": False, "success": False, "error": "relative_path is required"}
    if rel.startswith("/") or ":" in rel.split("/")[0]:
        return {"ok": False, "success": False, "error": "absolute paths are not allowed"}
    if _UNSAFE_NAME.search(rel) or ".." in rel.split("/"):
        return {"ok": False, "success": False, "error": "path traversal is not allowed"}

    # Default scripts/ prefix when writing bare app files
    if "/" not in rel and not rel.startswith("scripts"):
        rel = f"scripts/{rel}"

    name = Path(rel).name
    if name.startswith(".") and name not in (".env.example",):
        return {"ok": False, "success": False, "error": f"hidden file not allowed: {name}"}
    if not _is_allowed_suffix(name):
        return {
            "ok": False,
            "success": False,
            "error": f"file type not allowed: {Path(name).suffix or name}",
        }

    target_path = (workspace_dir / rel).resolve()
    try:
        target_path.relative_to(workspace_dir)
    except ValueError:
        return {"ok": False, "success": False, "error": "path escapes bot workspace"}

    # Never overwrite main bot runtime / secrets via this tool
    blocked = {
        "main.py",
        "config.json",
        "user_data.db",
        "scenario.json",
        "token.txt",
        ".env",
    }
    try:
        if target_path.relative_to(workspace_dir).as_posix() in blocked or target_path.name in blocked:
            if target_path.parent == workspace_dir:
                return {
                    "ok": False,
                    "success": False,
                    "error": f"refusing to overwrite {target_path.name}",
                }
    except ValueError:
        return {"ok": False, "success": False, "error": "path escapes bot workspace"}

    text = "" if content is None else str(content)
    # Strip common emoji ranges from AI-written sources
    text = re.sub(
        "["
        "\U0001F300-\U0001F9FF"
        "\U00002700-\U000027BF"
        "\U0001FA00-\U0001FAFF"
        "]+",
        "",
        text,
    )

    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path = str(target_path)
        print(f"[INFO] LOG: [Tool Execution] -> Writing file to: {abs_path}")
        log.info("[Tool Execution] Writing file to: %s", abs_path)
        target_path.write_text(text, encoding="utf-8")
    except OSError as exc:
        print(f"[ERROR] LOG: [Tool Execution Error] -> Exception: {exc}")
        log.exception("[Tool Execution Error] write failed: %s", exc)
        return {"ok": False, "success": False, "error": str(exc)}

    written_rel = target_path.relative_to(workspace_dir).as_posix()
    print(f"[SUCCESS] LOG: [Tool Execution] -> Wrote {written_rel} ({len(text)} bytes)")
    log.info(
        "write_workspace_file bot_id=%s -> %s (%s bytes)",
        bot_id,
        written_rel,
        len(text),
    )
    return {
        "ok": True,
        "success": True,
        "path": written_rel,
        "absolute_path": str(target_path),
        "relative_path": written_rel,
        "bytes": len(text.encode("utf-8")),
        "summary": f"Wrote {written_rel}",
        "files_created": [written_rel],
    }


def _slug_app_name(name: str) -> str:
    raw = re.sub(r"[^a-zA-Z0-9_\-]", "_", (name or "").strip().lower())
    raw = re.sub(r"_+", "_", raw).strip("_")
    return raw or "standalone_app"


def _strip_emojis(text: str) -> str:
    return re.sub(
        "["
        "\U0001F300-\U0001F9FF"
        "\U00002700-\U000027BF"
        "\U0001FA00-\U0001FAFF"
        "]+",
        "",
        text or "",
    )


def create_complete_standalone_app(
    *,
    bot_id: str | int | None,
    app_name: str,
    script_code: str,
    manifest: dict[str, Any] | None = None,
    nodes_to_add: list[dict[str, Any]] | None = None,
    connections_to_add: list[dict[str, Any]] | None = None,
    scenario: dict[str, Any] | None = None,
    wire_default_messages: bool = True,
) -> dict[str, Any]:
    """
    Atomic tool: write scripts/<app>/app.py + manifest.json, wire an app_bridge
    node into scenario.json, normalize port ids and strip broken connections.

    Disk failures raise RuntimeError (logged with traceback) instead of being
    swallowed, so the agent loop reports the real cause.
    """
    name = _slug_app_name(app_name)
    if not script_code or not str(script_code).strip():
        return {
            "ok": False,
            "success": False,
            "error": "script_code is required",
        }

    code = _strip_emojis(str(script_code))
    if "async def main" not in code and "def main" not in code:
        code = (
            code.rstrip()
            + "\n\nasync def main(**kwargs):\n"
            + "    return {\"ok\": True, \"result\": kwargs}\n"
        )

    workspace_root = get_bot_workspace_dir(bot_id)
    app_dir = workspace_root / "scripts" / name
    app_dir.mkdir(parents=True, exist_ok=True)

    rel_app = f"scripts/{name}/app.py"
    rel_man = f"scripts/{name}/manifest.json"
    files_created: list[str] = []

    w1 = write_workspace_file(bot_id, rel_app, code if code.endswith("\n") else code + "\n")
    if not (w1.get("ok") or w1.get("success")):
        msg = f"disk write failed for {rel_app}: {w1.get('error')}"
        log.error("[Tool Execution Error] %s", msg)
        raise RuntimeError(msg)
    files_created.append(rel_app)

    man: dict[str, Any] = dict(manifest or {})
    man.setdefault("name", name)
    man.setdefault("entryFile", "app.py")
    man.setdefault("entryFunction", "main")
    man.setdefault("entryAsync", True)
    if "inputs" not in man:
        man["inputs"] = {}
    man_text = json.dumps(man, ensure_ascii=False, indent=2) + "\n"
    w2 = write_workspace_file(bot_id, rel_man, man_text)
    if not (w2.get("ok") or w2.get("success")):
        msg = f"disk write failed for {rel_man}: {w2.get('error')}"
        log.error("[Tool Execution Error] %s", msg)
        raise RuntimeError(msg)
    files_created.append(rel_man)

    for rel in files_created:
        if not (workspace_root / rel).is_file():
            msg = f"file reported written but missing on disk: {workspace_root / rel}"
            log.error("[Tool Execution Error] %s", msg)
            raise RuntimeError(msg)

    # Merge scenario graph (in-memory + persist scenario.json)
    from backend.services.ai_intent import inspect_and_wire_app

    sc = dict(scenario) if isinstance(scenario, dict) else {}
    scenario_path = workspace_root / "scenario.json"
    if not (sc.get("blocks") or []) and scenario_path.is_file():
        try:
            disk = json.loads(scenario_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.exception("scenario.json unreadable at %s", scenario_path)
            raise RuntimeError(f"scenario.json unreadable: {exc}") from exc
        if isinstance(disk, dict):
            sc = disk
    # Drop stale edges first so they cannot block auto-wiring (e.g. start -> deleted node).
    removed = sanitize_scenario_connections(sc)

    extra_nodes = [n for n in (nodes_to_add or []) if isinstance(n, dict) and n.get("id")]
    own_bridge = next((n for n in extra_nodes if n.get("type") == "app_bridge"), None)
    manifest_outputs = _manifest_output_names(man)
    nodes_added = 0
    bridge_id: str | None = None

    if own_bridge is None:
        wired = inspect_and_wire_app(
            bot_id=bot_id,
            app_folder_path=f"scripts/{name}",
            scenario=sc,
            wire_default_messages=bool(wire_default_messages and not connections_to_add),
        )
        sc = wired.get("scenario") or sc
        bridge_id = str(wired.get("bridge_id") or "") or None
        nodes_added += 1 + len(wired.get("added_messages") or [])

    blocks = [b for b in (sc.get("blocks") or []) if isinstance(b, dict)]
    connections = list(sc.get("connections") or [])
    for node in extra_nodes:
        nid = str(node["id"])
        if node.get("type") == "app_bridge":
            data = dict(node.get("data") or {})
            data.setdefault("appFolder", f"scripts/{name}")
            data.setdefault("appName", name)
            data.setdefault("entryFile", man["entryFile"])
            data.setdefault("entryFunction", man["entryFunction"])
            data.setdefault("entryAsync", man["entryAsync"])
            node = {**node, "data": data}
        blocks = [b for b in blocks if str(b.get("id")) != nid]
        blocks.append(node)
        nodes_added += 1
    if own_bridge is not None:
        bridge_id = str(own_bridge["id"])

    types_by_id = {str(b.get("id")): str(b.get("type") or "") for b in blocks}
    for edge in connections_to_add or []:
        norm = _normalize_edge(edge, bridge_id, manifest_outputs, types_by_id)
        if norm:
            connections.append(norm)

    sc["blocks"] = blocks
    sc["connections"] = connections
    removed += sanitize_scenario_connections(sc)

    req = set(sc.get("required_plugins") or [])
    req.update({"app_bridge", "message", "start"})
    for b in blocks:
        if b.get("type"):
            req.add(str(b["type"]))
    sc["required_plugins"] = sorted(req)
    if not isinstance(sc.get("tags"), list):
        sc["tags"] = []

    try:
        scenario_path.parent.mkdir(parents=True, exist_ok=True)
        scenario_path.write_text(
            json.dumps(sc, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        log.exception("scenario.json save failed at %s", scenario_path)
        raise RuntimeError(f"scenario.json save failed: {exc}") from exc

    log.info(
        "[Tool Execution] create_complete_standalone_app app=%s files=%s nodes=%s removed_edges=%s",
        name,
        files_created,
        nodes_added,
        len(removed),
    )
    print(
        f"[SUCCESS] LOG: [Tool Execution] -> create_complete_standalone_app "
        f"app={name} files={files_created} nodes={nodes_added} removed_edges={len(removed)}"
    )
    return {
        "ok": True,
        "success": True,
        "app_name": name,
        "app_folder_path": f"scripts/{name}",
        "files_created": files_created,
        "nodes_added": nodes_added,
        "bridge_id": bridge_id,
        "connections_removed": removed,
        "scenario": sc,
        "layout_needed": True,
        "refresh_canvas": True,
        "refresh_repo": True,
        "summary": f"Created scripts/{name} and wired app_bridge",
    }


_BRIDGE_PLACEHOLDERS = frozenset({"app_bridge", "bridge", "$bridge", "{bridge}", "app"})
_SUCCESS_PORTS = frozenset(
    {"success", "ok", "yes", "true", "done", "result", "has_items", "has_data", "found", "next",
     "out", "default"}
)
_FAIL_PORTS = frozenset(
    {"error", "err", "fail", "failed", "no", "false", "no_new_items", "no_data", "empty",
     "not_found"}
)


def _manifest_output_names(man: dict[str, Any]) -> list[str]:
    ports = man.get("ports") if isinstance(man.get("ports"), dict) else {}
    raw = man.get("outputs") or ports.get("outputs") or ports.get("output") or []
    names: list[str] = []
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, dict):
            item = item.get("id") or item.get("name") or ""
        if item:
            names.append(str(item).strip().lower())
    return names


def _normalize_port(port: Any, manifest_outputs: list[str]) -> int | None:
    """Map a port reference (index, port_out_N, semantic name) to a numeric output index."""
    if port is None or port == "":
        return 0
    if isinstance(port, bool):
        return 0 if port else 1
    if isinstance(port, int):
        return port
    s = str(port).strip().lower()
    m = re.fullmatch(r"(?:port_)?(?:out(?:put)?_?)?(\d+)", s)
    if m:
        return int(m.group(1))
    if s in manifest_outputs:
        return manifest_outputs.index(s)
    if s in _SUCCESS_PORTS:
        return 0
    if s in _FAIL_PORTS:
        return 1
    return None


def _normalize_edge(
    edge: Any,
    bridge_id: str | None,
    manifest_outputs: list[str],
    types_by_id: dict[str, str],
) -> dict[str, str] | None:
    if not isinstance(edge, dict):
        return None
    frm = edge.get("from") or edge.get("from_node") or edge.get("from_block_id") or edge.get("source")
    to = edge.get("to") or edge.get("to_node") or edge.get("to_block_id") or edge.get("target")
    if not frm or not to:
        return None
    frm, to = str(frm), str(to)
    if bridge_id:
        if frm.lower() in _BRIDGE_PLACEHOLDERS:
            frm = bridge_id
        if to.lower() in _BRIDGE_PLACEHOLDERS:
            to = bridge_id
    port = next(
        (
            edge.get(k)
            for k in ("outputIndex", "from_port", "port", "output")
            if edge.get(k) is not None
        ),
        None,
    )
    idx = _normalize_port(port, manifest_outputs)
    if idx is None:
        return None
    # app_bridge exposes exactly two ports: 0 = success, 1 = error
    if types_by_id.get(frm) == "app_bridge" and idx > 1:
        idx = 1
    return {"from": frm, "to": to, "outputIndex": str(idx)}


def _block_output_count(block: dict[str, Any]) -> int | None:
    """Number of output ports the canvas renders for a block; None = unknown (skip check)."""
    typ = str(block.get("type") or "")
    data = block.get("data") if isinstance(block.get("data"), dict) else {}
    if typ == "note":
        return 0
    if typ in ("start", "command"):
        return 1
    if typ in ("condition", "app_bridge"):
        return 2
    if typ == "data":
        return 2 if data.get("action") == "issue" else 1
    if typ == "message":
        return max(len(data.get("inlineButtons") or []), 1)
    if typ == "menu":
        return max(len(data.get("buttons") or []), 1)
    try:
        from backend.core.plugin_manager import get_plugin_manager

        plugin = get_plugin_manager().get_by_type(typ)
    except Exception:
        plugin = None
    ui = getattr(plugin, "ui", None) if plugin is not None else None
    if isinstance(ui, dict) and isinstance(ui.get("outputs"), int):
        return max(int(ui["outputs"]), 0)
    return None


def sanitize_scenario_connections(sc: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Normalize connections in place and drop broken ones: unknown from/to block,
    self-loops, edges into start/note, out-of-range output index. For duplicate
    (from, outputIndex) pairs the last edge wins, matching canvas behaviour.
    Returns the list of removed edges with a reason.
    """
    blocks = {
        str(b.get("id")): b
        for b in (sc.get("blocks") or [])
        if isinstance(b, dict) and b.get("id") is not None
    }
    removed: list[dict[str, Any]] = []
    kept: dict[tuple[str, str], dict[str, str]] = {}
    for raw in sc.get("connections") or []:
        if not isinstance(raw, dict):
            removed.append({"edge": raw, "reason": "not an object"})
            continue
        frm = str(raw.get("from") or raw.get("from_node") or "")
        to = str(raw.get("to") or raw.get("to_node") or "")
        port = raw.get("outputIndex", raw.get("from_port"))
        idx = _normalize_port(port, [])
        reason = None
        if frm not in blocks:
            reason = "missing source block"
        elif to not in blocks:
            reason = "missing target block"
        elif frm == to:
            reason = "self loop"
        elif str(blocks[to].get("type")) in ("start", "note"):
            reason = "target has no input port"
        elif idx is None or idx < 0:
            reason = "invalid output index"
        else:
            count = _block_output_count(blocks[frm])
            if count is not None and idx >= count:
                reason = f"output index {idx} out of range ({count})"
        if reason:
            removed.append({"edge": raw, "reason": reason})
            continue
        key = (frm, str(idx))
        if key in kept:
            removed.append({"edge": kept.pop(key), "reason": "duplicate output port"})
        kept[key] = {"from": frm, "to": to, "outputIndex": str(idx)}
    sc["connections"] = list(kept.values())
    if removed:
        log.warning("sanitize_scenario_connections removed %d edge(s): %s", len(removed), removed)
    return removed


def execute_tool_call(
    tool_call: dict[str, Any] | None = None,
    *,
    name: str | None = None,
    arguments: dict[str, Any] | None = None,
    bot_id: str | int | None = None,
) -> dict[str, Any]:
    """
    Dispatch a single OpenAI/DeepSeek-style tool_call (or name+arguments) to a local tool.

    Accepts shapes:
      {"function": {"name": "...", "arguments": "{...}"}}
      {"name": "...", "arguments": {...}}
    """
    fn_name = (name or "").strip()
    args: dict[str, Any] = dict(arguments or {})

    if isinstance(tool_call, dict):
        fn = tool_call.get("function") if isinstance(tool_call.get("function"), dict) else {}
        if not fn_name:
            fn_name = str(
                fn.get("name") or tool_call.get("name") or tool_call.get("tool") or ""
            ).strip()
        raw_args = fn.get("arguments") if fn else tool_call.get("arguments")
        if isinstance(raw_args, str):
            try:
                parsed = json.loads(raw_args or "{}")
            except json.JSONDecodeError:
                parsed = {}
            if isinstance(parsed, dict):
                args = {**parsed, **args}
        elif isinstance(raw_args, dict):
            args = {**raw_args, **args}

    print(f"[INFO] LOG: [Tool Dispatch] -> name={fn_name!r} args_keys={list(args.keys())}")
    log.info("[Tool Dispatch] name=%s keys=%s", fn_name, list(args.keys()))

    if fn_name == "write_workspace_file":
        bid = args.get("bot_id")
        if bid is None or bid == "":
            bid = bot_id
        result = write_workspace_file(
            bot_id=bid,
            relative_path=str(args.get("relative_path") or args.get("path") or ""),
            content=str(
                args.get("content")
                if args.get("content") is not None
                else args.get("text") or ""
            ),
        )
        return result

    if fn_name == "create_complete_standalone_app":
        bid = args.get("bot_id")
        if bid is None or bid == "":
            bid = bot_id
        return create_complete_standalone_app(
            bot_id=bid,
            app_name=str(args.get("app_name") or args.get("name") or ""),
            script_code=str(args.get("script_code") or args.get("code") or ""),
            manifest=args.get("manifest") if isinstance(args.get("manifest"), dict) else {},
            nodes_to_add=args.get("nodes_to_add")
            if isinstance(args.get("nodes_to_add"), list)
            else [],
            connections_to_add=args.get("connections_to_add")
            if isinstance(args.get("connections_to_add"), list)
            else [],
            scenario=args.get("scenario") if isinstance(args.get("scenario"), dict) else None,
            wire_default_messages=bool(args.get("wire_default_messages", True)),
        )

    print(f"[ERROR] LOG: [Tool Execution Error] -> Unknown tool: {fn_name}")
    return {"ok": False, "success": False, "error": f"Unknown tool: {fn_name}"}
