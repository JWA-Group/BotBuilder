"""Capability manifest for AI Director — what the orchestrator may trigger."""

from __future__ import annotations

from typing import Any


def _block_label(block: dict[str, Any]) -> str:
    data = block.get("data") if isinstance(block.get("data"), dict) else {}
    typ = str(block.get("type") or "")
    for key in (
        "name",
        "item_title",
        "text",
        "inputPrompt",
        "command",
        "title",
        "fieldName",
    ):
        val = data.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()[:80]
    return typ or str(block.get("id") or "node")


def _parse_csv_keys(raw: str | list[str] | None) -> list[str]:
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    text = str(raw or "")
    parts: list[str] = []
    for chunk in text.replace("\n", ",").split(","):
        key = chunk.strip()
        if key and key not in parts:
            parts.append(key)
    return parts


def build_capability_manifest(
    scenario_data: dict[str, Any] | None,
    *,
    allowed_variables: str | list[str] | None = None,
    target_nodes: str | list[str] | None = None,
    director_block: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Lightweight JSON schema of what AI Director may do for a scenario.

    Returns::
        {
          "nodes": [{"node_id", "label", "type"}],
          "allowed_variables": ["phone", "email", ...],
          "allowed_trigger_nodes": ["node_id", ...],
          "actions": ["WRITE_DB", "TRIGGER_NODE", "REPLY"]
        }
    """
    scenario = scenario_data if isinstance(scenario_data, dict) else {}
    blocks = scenario.get("blocks") if isinstance(scenario.get("blocks"), list) else []

    nodes: list[dict[str, Any]] = []
    all_ids: list[str] = []
    for b in blocks:
        if not isinstance(b, dict):
            continue
        nid = str(b.get("id") or "").strip()
        if not nid:
            continue
        typ = str(b.get("type") or "")
        if typ in ("note",):
            continue
        all_ids.append(nid)
        nodes.append(
            {
                "node_id": nid,
                "label": _block_label(b),
                "type": typ,
            }
        )

    data = {}
    if isinstance(director_block, dict):
        data = director_block.get("data") if isinstance(director_block.get("data"), dict) else {}

    vars_raw = allowed_variables
    if vars_raw is None:
        vars_raw = data.get("allowed_variables")
    allowed_vars = _parse_csv_keys(vars_raw)
    if not allowed_vars:
        # Sensible defaults when author left the field empty
        allowed_vars = [
            "phone",
            "email",
            "name",
            "balance",
            "role",
            "city",
            "payment_status",
        ]

    targets_raw = target_nodes
    if targets_raw is None:
        targets_raw = data.get("target_nodes")
    allowed_triggers = _parse_csv_keys(targets_raw)
    if not allowed_triggers:
        # All non-start/command nodes are fair game when unrestricted
        allowed_triggers = [
            n["node_id"]
            for n in nodes
            if n["type"] not in ("start", "command", "ai_director")
        ]

    # Keep only triggers that exist on the canvas
    id_set = set(all_ids)
    allowed_triggers = [t for t in allowed_triggers if t in id_set]

    return {
        "nodes": nodes,
        "allowed_variables": allowed_vars,
        "allowed_trigger_nodes": allowed_triggers,
        "actions": ["WRITE_DB", "TRIGGER_NODE", "REPLY"],
        "output_schema": {
            "commands": [
                {"action": "WRITE_DB", "key": "var_name", "value": "val"},
                {"action": "TRIGGER_NODE", "node_id": "target_id"},
            ],
            "reply_text": "Text to send to user",
        },
    }


def format_manifest_for_prompt(manifest: dict[str, Any] | None) -> str:
    """Compact text block for the LLM system prompt."""
    import json

    m = manifest if isinstance(manifest, dict) else {}
    return json.dumps(m, ensure_ascii=False, indent=2)[:8000]
