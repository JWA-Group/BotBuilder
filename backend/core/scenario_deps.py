"""Scenario plugin dependency validation and template manifest helpers."""

from __future__ import annotations

from typing import Any

from backend.core.plugin_manager import PluginManager, get_plugin_manager


class PhantomNodeError(ValueError):
    """Raised when scenario references block types with no installed plugin."""

    def __init__(self, plugin_id: str, *, missing: list[str] | None = None) -> None:
        self.plugin_id = plugin_id
        self.missing = missing or [plugin_id]
        label = plugin_id if len(self.missing) == 1 else ", ".join(self.missing)
        super().__init__(
            f"Compilation locked: Phantom Node [{label}] detected. "
            "Please install the missing plugin to run the bot."
        )


def types_in_scenario(scenario: dict[str, Any]) -> set[str]:
    types: set[str] = set()
    for block in scenario.get("blocks") or []:
        typ = block.get("type")
        if typ:
            types.add(str(typ))
    return types


def compute_required_plugins(scenario: dict[str, Any]) -> list[str]:
    """Unique block types referenced by the scenario graph."""
    return sorted(types_in_scenario(scenario))


def normalize_scenario_document(raw: dict[str, Any] | None) -> dict[str, Any]:
    """
    Normalize scenario or template manifest payloads.

    Supports flat `{blocks, connections, tags}` and wrapped:
    `{template_name, required_plugins, graph: {blocks, connections, tags}}`.
    """
    if not isinstance(raw, dict):
        return {"blocks": [], "connections": [], "tags": [], "required_plugins": []}

    graph = raw.get("graph")
    if isinstance(graph, dict):
        blocks = graph.get("blocks", raw.get("blocks", []))
        connections = graph.get("connections", raw.get("connections", []))
        tags = graph.get("tags", raw.get("tags", []))
    else:
        blocks = raw.get("blocks", [])
        connections = raw.get("connections", [])
        tags = raw.get("tags", [])

    required = raw.get("required_plugins")
    if not isinstance(required, list):
        required = compute_required_plugins({"blocks": blocks})

    out: dict[str, Any] = {
        "blocks": blocks if isinstance(blocks, list) else [],
        "connections": connections if isinstance(connections, list) else [],
        "tags": tags if isinstance(tags, list) else [],
        "required_plugins": sorted({str(x) for x in required if x}),
    }
    template_name = raw.get("template_name")
    if template_name:
        out["template_name"] = str(template_name)
    return out


def validate_scenario_plugins(
    scenario: dict[str, Any],
    plugin_manager: PluginManager | None = None,
) -> None:
    """Ensure every block type in the scenario has an installed plugin."""
    mgr = plugin_manager or get_plugin_manager()
    missing: list[str] = []
    for typ in sorted(types_in_scenario(scenario)):
        if not mgr.get_by_type(typ):
            missing.append(typ)
    if missing:
        raise PhantomNodeError(missing[0], missing=missing)


def find_phantom_types(
    scenario: dict[str, Any],
    plugin_manager: PluginManager | None = None,
) -> list[str]:
    mgr = plugin_manager or get_plugin_manager()
    return sorted(t for t in types_in_scenario(scenario) if not mgr.get_by_type(t))
