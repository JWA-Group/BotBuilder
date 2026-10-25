"""Scenario ops for AI assistant: Pydantic schemas, layout, patch, catalog."""

from __future__ import annotations

import copy
import re
from collections import deque
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from backend.core.plugin_manager import get_plugin_manager
from backend.core.scenario_deps import normalize_scenario_document
from backend.services.ai_scenario_perplexity import sanitize_user_placeholders

# Spec spacing (docs/AI_ASSISTANT.md §7)
LAYOUT_DX = 320
LAYOUT_DY = 160
LAYOUT_BASE_X = 100
LAYOUT_BASE_Y = 100


# ---------------------------------------------------------------------------
# Pydantic v2 schemas (LLM contract — docs/AI_ASSISTANT.md §3)
# ---------------------------------------------------------------------------


class BlockConnection(BaseModel):
    id: str = Field(default="", description="Unique connection ID")
    from_block_id: str = Field(..., description="Source block ID")
    from_port: str = Field(default="0", description="Source port (out index / name)")
    to_block_id: str = Field(..., description="Target block ID")
    to_port: str = Field(default="in", description="Target port name")

    @model_validator(mode="before")
    @classmethod
    def coerce_canvas_or_ports(cls, data: Any) -> Any:
        """Accept LLM port schema OR legacy canvas {from,to,outputIndex}."""
        if not isinstance(data, dict):
            return data
        d = dict(data)
        if "from_block_id" not in d and d.get("from") is not None:
            d["from_block_id"] = d["from"]
        if "to_block_id" not in d and d.get("to") is not None:
            d["to_block_id"] = d["to"]
        if "from_port" not in d and d.get("outputIndex") is not None:
            d["from_port"] = str(d["outputIndex"])
        if not d.get("to_port"):
            d["to_port"] = "in"
        frm = str(d.get("from_block_id") or "")
        to = str(d.get("to_block_id") or "")
        port = str(d.get("from_port") or "0")
        if not d.get("id"):
            d["id"] = f"c_{frm}_{port}_{to}"
        d["from_port"] = str(d.get("from_port") or "0")
        d["to_port"] = str(d.get("to_port") or "in")
        return d

    def to_canvas(self) -> dict[str, Any]:
        """Runtime canvas connection: {from, to, outputIndex}."""
        port = self.from_port
        # Named ports → indices used by BotBuilder canvas
        named = {"out": "0", "default": "0", "success": "0", "true": "0", "yes": "0",
                 "false": "1", "no": "1", "error": "1", "fail": "1"}
        oi = named.get(port.lower(), port) if isinstance(port, str) else "0"
        return {
            "from": self.from_block_id,
            "to": self.to_block_id,
            "outputIndex": str(oi),
        }


class ScenarioBlock(BaseModel):
    id: str = Field(..., description="Unique block ID")
    type: str = Field(default="", description="Plugin/block type")
    x: int = Field(default=0, description="X on canvas")
    y: int = Field(default=0, description="Y on canvas")
    data: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("id", mode="before")
    @classmethod
    def _id_str(cls, v: Any) -> str:
        return str(v or "").strip()

    @field_validator("type", mode="before")
    @classmethod
    def _type_str(cls, v: Any) -> str:
        return str(v or "").strip()

    @field_validator("x", "y", mode="before")
    @classmethod
    def _coord_int(cls, v: Any) -> int:
        try:
            return int(v if v is not None else 0)
        except (TypeError, ValueError):
            return 0

    def to_canvas(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "x": self.x,
            "y": self.y,
            "data": self.data if isinstance(self.data, dict) else {},
        }


class ScenarioDocument(BaseModel):
    blocks: List[ScenarioBlock]
    connections: List[BlockConnection] = Field(default_factory=list)
    summary: str = ""
    required_plugins: List[str] = Field(default_factory=list)
    tags: List[Any] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def unwrap_nested_scenario(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        d = dict(data)
        nested = d.get("scenario")
        if isinstance(nested, dict) and ("blocks" in nested or "connections" in nested):
            for key in ("blocks", "connections", "required_plugins", "tags"):
                if key not in d and key in nested:
                    d[key] = nested[key]
            if not d.get("summary") and nested.get("summary"):
                d["summary"] = nested["summary"]
        return d


class ScenarioPatch(BaseModel):
    summary: str = ""
    add_blocks: List[ScenarioBlock] = Field(default_factory=list)
    update_blocks: List[ScenarioBlock] = Field(default_factory=list)
    remove_block_ids: List[str] = Field(default_factory=list)
    add_connections: List[BlockConnection] = Field(default_factory=list)
    remove_connection_ids: List[str] = Field(default_factory=list)
    # Legacy alias accepted from older prompts
    remove_connections: List[BlockConnection] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def coerce_remove_connections(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        d = dict(data)
        # If model returns remove_connections objects without ids, derive ids
        rem = d.get("remove_connections")
        if isinstance(rem, list) and not d.get("remove_connection_ids"):
            ids: list[str] = []
            for item in rem:
                if isinstance(item, str):
                    ids.append(item)
                elif isinstance(item, dict):
                    try:
                        bc = BlockConnection.model_validate(item)
                        ids.append(bc.id)
                    except ValidationError:
                        frm = item.get("from") or item.get("from_block_id") or ""
                        to = item.get("to") or item.get("to_block_id") or ""
                        oi = item.get("outputIndex") or item.get("from_port") or "0"
                        ids.append(f"c_{frm}_{oi}_{to}")
            d["remove_connection_ids"] = ids
        return d


# ---------------------------------------------------------------------------
# Adapters: canvas ↔ LLM
# ---------------------------------------------------------------------------


def canvas_connection_to_model(c: dict[str, Any]) -> BlockConnection:
    return BlockConnection.model_validate(c)


def canvas_block_to_model(b: dict[str, Any]) -> ScenarioBlock:
    return ScenarioBlock.model_validate(
        {
            "id": b.get("id"),
            "type": b.get("type"),
            "x": b.get("x") or 0,
            "y": b.get("y") or 0,
            "data": b.get("data") if isinstance(b.get("data"), dict) else {},
        }
    )


def document_to_canvas(doc: ScenarioDocument) -> dict[str, Any]:
    blocks = [b.to_canvas() for b in doc.blocks]
    conns = [c.to_canvas() for c in doc.connections]
    required = doc.required_plugins or sorted({b["type"] for b in blocks if b.get("type")})
    return {
        "blocks": blocks,
        "connections": conns,
        "tags": list(doc.tags or []),
        "required_plugins": required,
        "summary": doc.summary or "",
    }


def canvas_to_document(scenario: dict[str, Any]) -> ScenarioDocument:
    blocks = [
        canvas_block_to_model(b)
        for b in (scenario.get("blocks") or [])
        if isinstance(b, dict) and b.get("id")
    ]
    conns = [
        canvas_connection_to_model(c)
        for c in (scenario.get("connections") or [])
        if isinstance(c, dict)
    ]
    return ScenarioDocument(
        blocks=blocks,
        connections=conns,
        required_plugins=list(scenario.get("required_plugins") or []),
        tags=list(scenario.get("tags") or []),
    )


# ---------------------------------------------------------------------------
# Compact topology for LLM context
# ---------------------------------------------------------------------------


def serialize_scenario_for_llm(scenario: dict[str, Any] | None) -> str:
    """Lightweight topological summary — avoids dumping full data payloads."""
    if not isinstance(scenario, dict):
        return "(empty scenario)"
    blocks = scenario.get("blocks") or []
    conns = scenario.get("connections") or []
    if not blocks:
        return "(empty scenario)"

    lines: list[str] = ["BLOCKS:"]
    for b in blocks:
        if not isinstance(b, dict):
            continue
        bid = b.get("id")
        typ = b.get("type")
        data = b.get("data") if isinstance(b.get("data"), dict) else {}
        hint_parts: list[str] = []
        for key in ("text", "command", "fieldName", "name", "service", "city"):
            if data.get(key) not in (None, ""):
                val = str(data[key]).replace("\n", " ")
                if len(val) > 60:
                    val = val[:59] + "…"
                hint_parts.append(f"{key}={val}")
        hint = (", ".join(hint_parts)) if hint_parts else ""
        lines.append(f"  - {bid} [{typ}]" + (f" {{{hint}}}" if hint else ""))

    lines.append("CONNECTIONS:")
    if not conns:
        lines.append("  (none)")
    else:
        for c in conns:
            if not isinstance(c, dict):
                continue
            try:
                bc = canvas_connection_to_model(c)
                lines.append(
                    f"  - {bc.id}: {bc.from_block_id}:{bc.from_port} -> {bc.to_block_id}:{bc.to_port}"
                )
            except ValidationError:
                lines.append(
                    f"  - {c.get('from')}[{c.get('outputIndex', 0)}] -> {c.get('to')}"
                )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Auto-layout grid (ΔX=320, ΔY=160)
# ---------------------------------------------------------------------------


def layout_blocks_grid(blocks: list[dict[str, Any]], connections: list[dict[str, Any]]) -> None:
    """Topological BFS layout from start/command entries; orphans to the right."""
    if not blocks:
        return
    ids = {str(b["id"]) for b in blocks if b.get("id") is not None}
    adj: dict[str, list[str]] = {bid: [] for bid in ids}
    for c in connections:
        fr = str(c.get("from") or "").strip()
        to = str(c.get("to") or "").strip()
        if fr in ids and to in ids and fr != to and to not in adj[fr]:
            adj[fr].append(to)

    depth: dict[str, int] = {bid: -1 for bid in ids}
    roots = [bid for bid in ids if bid == "start"]
    if not roots:
        # Prefer command / start types as roots
        for b in blocks:
            if str(b.get("type")) in ("start", "command") and str(b.get("id")) in ids:
                roots.append(str(b["id"]))
        if not roots and blocks:
            roots = [str(blocks[0]["id"])]

    q: deque[str] = deque()
    for r in roots:
        if depth.get(r, -1) < 0:
            depth[r] = 0
            q.append(r)
    while q:
        u = q.popleft()
        for v in adj.get(u, []):
            nd = depth[u] + 1
            if depth[v] < 0 or nd < depth[v]:
                depth[v] = nd
                q.append(v)

    max_d = max((d for d in depth.values() if d >= 0), default=0)
    for bid in ids:
        if depth[bid] < 0:
            max_d += 1
            depth[bid] = max_d

    by_layer: dict[int, list[str]] = {}
    for bid, d in depth.items():
        by_layer.setdefault(d, []).append(bid)

    for layer in sorted(by_layer.keys()):
        row_ids = sorted(by_layer[layer])
        for idx, bid in enumerate(row_ids):
            for b in blocks:
                if str(b.get("id")) == bid:
                    b["x"] = LAYOUT_BASE_X + layer * LAYOUT_DX
                    b["y"] = LAYOUT_BASE_Y + idx * LAYOUT_DY
                    break


# ---------------------------------------------------------------------------
# Plugin catalog
# ---------------------------------------------------------------------------


def _ports_for_ui(ui: dict[str, Any]) -> list[str]:
    outputs = ui.get("outputs")
    if isinstance(outputs, list) and outputs:
        return [str(x) for x in outputs][:16]
    try:
        n = max(1, int(outputs))
    except (TypeError, ValueError):
        n = 1
    if str(ui.get("type")) == "condition" or n == 2:
        return ["0", "1"]  # true / false indices
    if outputs == "dynamic":
        return ["0..N"]
    return [str(i) for i in range(n)]


def build_plugin_catalog() -> list[dict[str, Any]]:
    """Compact catalog with full ai_capabilities + ports for LLM prompts."""
    mgr = get_plugin_manager()
    out: list[dict[str, Any]] = []
    for plugin in mgr.list_plugins():
        ui = plugin.ui if isinstance(plugin.ui, dict) else {}
        typ = plugin.block_type
        if not typ:
            continue
        caps = ui.get("ai_capabilities")
        if not isinstance(caps, dict):
            caps = {}
        ports = caps.get("ports") if isinstance(caps.get("ports"), list) else _ports_for_ui(ui)
        out.append(
            {
                "type": typ,
                "name": str(ui.get("name") or typ),
                "ai_capabilities": {
                    "summary": str(caps.get("summary") or ui.get("description") or typ)[:300],
                    "can": [str(x)[:120] for x in (caps.get("can") or []) if x][:12],
                    "cannot": [str(x)[:120] for x in (caps.get("cannot") or []) if x][:12],
                    "when_to_use": str(caps.get("when_to_use") or "")[:300],
                    "data_shape_hint": str(caps.get("data_shape_hint") or "")[:400],
                    "ports": [str(p) for p in ports][:16],
                },
            }
        )
    out.sort(key=lambda x: x["type"])
    return out


def _named_ports_by_type() -> dict[str, list[str]]:
    """Semantic output names per block type, position = numeric output index."""
    out: dict[str, list[str]] = {}
    for plugin in get_plugin_manager().list_plugins():
        ui = plugin.ui if isinstance(plugin.ui, dict) else {}
        caps = ui.get("ai_capabilities") if isinstance(ui.get("ai_capabilities"), dict) else {}
        names = caps.get("ports") if isinstance(caps.get("ports"), list) else []
        labels = ui.get("outputLabels") if isinstance(ui.get("outputLabels"), list) else []
        src = names or labels
        if plugin.block_type and src:
            out[str(plugin.block_type)] = [str(x).strip().lower() for x in src]
    return out


def catalog_types(catalog: list[dict[str, Any]] | None = None) -> set[str]:
    cat = catalog if catalog is not None else build_plugin_catalog()
    return {str(x["type"]) for x in cat if x.get("type")}


def format_catalog_for_prompt(catalog: list[dict[str, Any]] | None = None) -> str:
    cat = catalog if catalog is not None else build_plugin_catalog()
    lines: list[str] = []
    for item in cat:
        caps = item.get("ai_capabilities") or {}
        ports = [
            p if str(p).isdigit() or ".." in str(p) else f'outputIndex "{i}" = {p}'
            for i, p in enumerate(caps.get("ports") or [])
        ]
        lines.append(
            f"- {item['type']} ({item.get('name')}): {caps.get('summary', '')}\n"
            f"  can: {', '.join(caps.get('can') or []) or '—'}\n"
            f"  cannot: {', '.join(caps.get('cannot') or []) or '—'}\n"
            f"  when: {caps.get('when_to_use') or '—'}\n"
            f"  data: {caps.get('data_shape_hint') or '—'}\n"
            f"  ports: {', '.join(str(p) for p in ports) or '0'}"
        )
    return "\n".join(lines) if lines else "(нет плагинов)"


# ---------------------------------------------------------------------------
# Sanitize / finalize / patch
# ---------------------------------------------------------------------------


def _sanitize_data_strings(data: Any) -> Any:
    if isinstance(data, str):
        return sanitize_user_placeholders(data)
    if isinstance(data, list):
        return [_sanitize_data_strings(x) for x in data]
    if isinstance(data, dict):
        return {k: _sanitize_data_strings(v) for k, v in data.items()}
    return data


def _clean_block(block: dict[str, Any], allowed: set[str], idx: int) -> dict[str, Any] | None:
    typ = str(block.get("type") or "").strip()
    if not typ or typ not in allowed:
        return None
    bid = str(block.get("id") or "").strip()
    bid = re.sub(r"[^a-zA-Z0-9_-]", "_", bid) or f"{typ}_{idx}"
    if typ == "start":
        bid = "start"
    try:
        x = int(block.get("x") or 0)
    except (TypeError, ValueError):
        x = LAYOUT_BASE_X + idx * LAYOUT_DX
    try:
        y = int(block.get("y") or 0)
    except (TypeError, ValueError):
        y = LAYOUT_BASE_Y
    data = block.get("data") if isinstance(block.get("data"), dict) else {}
    data = _sanitize_data_strings(data)
    return {"id": bid, "type": typ, "x": x, "y": y, "data": data}


def _clean_connection(c: dict[str, Any], id_set: set[str]) -> dict[str, Any] | None:
    if not isinstance(c, dict):
        return None
    try:
        bc = BlockConnection.model_validate(c)
    except ValidationError:
        return None
    canvas = bc.to_canvas()
    if canvas["from"] not in id_set or canvas["to"] not in id_set:
        return None
    return canvas


def finalize_scenario(raw: dict[str, Any], allowed: set[str] | None = None) -> dict[str, Any]:
    """Validate → filter types → layout → required_plugins (canvas shape)."""
    allowed = allowed or catalog_types()

    # Prefer Pydantic parse when possible (accepts port + legacy shapes)
    try:
        doc = ScenarioDocument.model_validate(raw if isinstance(raw, dict) else {})
        raw_canvas = document_to_canvas(doc)
    except ValidationError:
        raw_canvas = raw if isinstance(raw, dict) else {}

    normalized = normalize_scenario_document(raw_canvas)
    blocks_in = normalized.get("blocks") or []
    blocks: list[dict[str, Any]] = []
    seen: set[str] = set()
    has_start = False
    for i, item in enumerate(blocks_in):
        if not isinstance(item, dict):
            continue
        cleaned = _clean_block(item, allowed, i)
        if not cleaned:
            continue
        bid = cleaned["id"]
        if bid in seen:
            bid = f"{bid}_{i}"
            cleaned["id"] = bid
        seen.add(bid)
        if cleaned["type"] == "start":
            has_start = True
            cleaned["id"] = "start"
        blocks.append(cleaned)

    if not has_start:
        blocks.insert(0, {"id": "start", "type": "start", "x": LAYOUT_BASE_X, "y": LAYOUT_BASE_Y, "data": {}})
        seen.add("start")

    from backend.services.ai_tools import _normalize_port, sanitize_scenario_connections

    id_set = {str(b["id"]) for b in blocks}
    types_by_id = {str(b["id"]): str(b["type"]) for b in blocks}
    port_names = _named_ports_by_type()
    conns: list[dict[str, Any]] = []
    for c in normalized.get("connections") or []:
        cc = _clean_connection(c if isinstance(c, dict) else {}, id_set)
        if not cc:
            continue
        # Canvas DOM and runtime NEXT_MAP only understand numeric ports; a named
        # port ("has_items") is invisible on canvas yet collapses to 0 at runtime.
        src_type = types_by_id.get(cc["from"], "")
        idx = _normalize_port(cc["outputIndex"], port_names.get(src_type, []))
        if idx is None:
            continue
        if src_type == "app_bridge" and idx > 1:
            idx = 1
        cc["outputIndex"] = str(idx)
        conns.append(cc)

    if not any(c["from"] == "start" for c in conns) and len(blocks) > 1:
        nxt = next((b["id"] for b in blocks if b["id"] != "start"), None)
        if nxt:
            conns.insert(0, {"from": "start", "outputIndex": "0", "to": nxt})

    graph = {"blocks": blocks, "connections": conns}
    sanitize_scenario_connections(graph)
    conns = graph["connections"]

    layout_blocks_grid(blocks, conns)
    required = sorted({str(b["type"]) for b in blocks})
    return {
        "blocks": blocks,
        "connections": conns,
        "tags": normalized.get("tags") or [],
        "required_plugins": required,
    }


def apply_scenario_patch(
    current: dict[str, Any],
    patch: dict[str, Any] | ScenarioPatch,
    allowed: set[str] | None = None,
) -> dict[str, Any]:
    """Merge validated patch into current canvas scenario, then finalize."""
    allowed = allowed or catalog_types()
    if isinstance(patch, ScenarioPatch):
        patch_model = patch
    else:
        patch_model = ScenarioPatch.model_validate(patch if isinstance(patch, dict) else {})

    base = normalize_scenario_document(current if isinstance(current, dict) else {})
    blocks_by_id: dict[str, dict[str, Any]] = {}
    for i, b in enumerate(base.get("blocks") or []):
        if not isinstance(b, dict):
            continue
        cleaned = _clean_block(b, allowed | {str(b.get("type") or "")}, i)
        if cleaned:
            blocks_by_id[cleaned["id"]] = cleaned
        elif str(b.get("id") or ""):
            bid = str(b.get("id"))
            blocks_by_id[bid] = {
                "id": bid,
                "type": str(b.get("type") or "message"),
                "x": int(b.get("x") or 0),
                "y": int(b.get("y") or 0),
                "data": b.get("data") if isinstance(b.get("data"), dict) else {},
            }

    # Keep canvas conns + stable ids for removal by remove_connection_ids
    conns: list[dict[str, Any]] = []
    conn_id_map: list[tuple[str, dict[str, Any]]] = []
    for c in base.get("connections") or []:
        if not isinstance(c, dict):
            continue
        canvas_c = {
            "from": str(c.get("from") or ""),
            "to": str(c.get("to") or ""),
            "outputIndex": str(c.get("outputIndex", "0")),
        }
        try:
            cid = canvas_connection_to_model(c).id
        except ValidationError:
            cid = f"c_{canvas_c['from']}_{canvas_c['outputIndex']}_{canvas_c['to']}"
        conns.append(canvas_c)
        conn_id_map.append((cid, canvas_c))

    for rid in patch_model.remove_block_ids:
        rid_s = str(rid)
        if rid_s == "start":
            continue
        blocks_by_id.pop(rid_s, None)
        conns = [c for c in conns if c["from"] != rid_s and c["to"] != rid_s]
        conn_id_map = [(i, c) for i, c in conn_id_map if c["from"] != rid_s and c["to"] != rid_s]

    remove_ids = set(str(x) for x in patch_model.remove_connection_ids)
    if remove_ids:
        conns = [c for cid, c in conn_id_map if cid not in remove_ids]
        # Also match legacy from/to keys embedded in remove list strings
        for legacy in patch_model.remove_connections:
            canvas = legacy.to_canvas()
            conns = [
                c
                for c in conns
                if not (
                    c["from"] == canvas["from"]
                    and c["to"] == canvas["to"]
                    and str(c["outputIndex"]) == str(canvas["outputIndex"])
                )
            ]

    for i, ab in enumerate(patch_model.add_blocks):
        cleaned = _clean_block(ab.to_canvas(), allowed, 1000 + i)
        if not cleaned:
            continue
        if cleaned["id"] in blocks_by_id and cleaned["id"] != "start":
            cleaned["id"] = f"{cleaned['id']}_new_{i}"
        blocks_by_id[cleaned["id"]] = cleaned

    for ub in patch_model.update_blocks:
        bid = ub.id
        if not bid or bid not in blocks_by_id:
            continue
        cur = copy.deepcopy(blocks_by_id[bid])
        if ub.type and ub.type in allowed:
            cur["type"] = ub.type
        if isinstance(ub.data, dict) and ub.data:
            merged = {**(cur.get("data") or {}), **ub.data}
            cur["data"] = _sanitize_data_strings(merged)
        if "x" in ub.model_fields_set:
            cur["x"] = ub.x
        if "y" in ub.model_fields_set:
            cur["y"] = ub.y
        blocks_by_id[bid] = cur

    for ac in patch_model.add_connections:
        conns.append(ac.to_canvas())

    merged = {
        "blocks": list(blocks_by_id.values()),
        "connections": conns,
        "tags": base.get("tags") or [],
    }
    allowed_merge = allowed | {str(b.get("type")) for b in merged["blocks"]}
    return finalize_scenario(merged, allowed_merge)


def truncate_reply(text: str, max_chars: int = 50000) -> str:
    """Sanitize assistant reply for the UI without cutting fold/details content.

    Historically this capped replies at ~900 chars and replaced fenced code with
    a placeholder, which produced trailing ellipses in «Детали изменений».
    Keep the full reply; only normalize whitespace.
    """
    s = (text or "").strip()
    if not s:
        return ""
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    # Hard safety ceiling only — never used for normal chat/tool replies
    if max_chars > 0 and len(s) > max_chars:
        return s[:max_chars].rstrip()
    return s


# Appended to the chat system prompt when auto_pilot=True.
AUTOPILOT_CHAT_ADDENDUM = """
AUTO-PILOT MODE (обязательно):
- НИКОГДА не спрашивай «создать плагин?», «обновить сценарий?», «продолжить?» и т.п.
- Не жди согласия пользователя — сразу решай и возвращай исполняемый intent.
- Если нужен новый плагин — intent=need_plugin + полный plugin_suggestion (имя + description).
- Если нужно собрать/пересобрать бота — intent=ready_replace + scenario_action.
- Если нужно добавить/починить на текущем canvas — intent=ready_patch + scenario_action.
- reply: коротко сообщи ЧТО сейчас будет сделано (без вопросов и без просьб подтвердить).
"""


def autopilot_scenario_mode(current_scenario: dict[str, Any] | None) -> str:
    """Smart default: patch existing canvas, replace empty/new canvas."""
    blocks = (current_scenario or {}).get("blocks") or []
    return "patch" if blocks else "replace"


def format_autopilot_status(
    *,
    mode: str | None = None,
    plugin_name: str | None = None,
    summary: str = "",
) -> str:
    bits: list[str] = []
    if plugin_name:
        bits.append(f"created plugin [{plugin_name}]")
    if mode == "patch":
        bits.append("applied scenario patch")
    elif mode == "replace":
        bits.append("applied scenario replace")
    elif mode:
        bits.append(f"applied scenario ({mode})")
    body = " & ".join(bits) if bits else "done"
    status = f"Auto-Pilot executed: {body}."
    if summary:
        status = f"{status} {summary.strip()}"
    return status.strip()
