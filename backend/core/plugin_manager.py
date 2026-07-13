"""Plugin loader — scans bundled + user plugin directories."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jinja2 import ChoiceLoader, Environment, FileSystemLoader, TemplateNotFound

from backend.core.app_paths import (
    BUNDLED_PLUGINS_DIR,
    PLUGINS_DIR,
    USER_PLUGINS_DIR,
    plugin_search_dirs,
)

BUILTIN_PLUGIN_FOLDERS = frozenset(
    {
        "start_node",
        "command_node",
        "send_message",
        "menu_node",
        "data_node",
        "condition_node",
        "weather_node",
        "note_node",
    }
)


def is_builtin_plugin(plugin_id: str) -> bool:
    return plugin_id in BUILTIN_PLUGIN_FOLDERS

_BUILTIN_EXECUTABLE_TYPES = frozenset({"message", "menu", "data", "condition", "weather"})
EXECUTABLE_TYPES = _BUILTIN_EXECUTABLE_TYPES


def get_executable_types(manager: "PluginManager | None" = None) -> frozenset[str]:
    """Built-in executable block types plus custom plugins marked executable in ui.json."""
    mgr = manager or get_plugin_manager()
    types = set(_BUILTIN_EXECUTABLE_TYPES)
    for plugin in mgr.list_plugins():
        if plugin.ui.get("executable") and plugin.code_template_name:
            types.add(plugin.block_type)
    return frozenset(types)


@dataclass(frozen=True)
class BlockPlugin:
    id: str
    path: Path
    ui: dict[str, Any]
    code_template_name: str

    @property
    def block_type(self) -> str:
        return str(self.ui.get("type") or self.id)

    def render_code(
        self,
        env: Environment,
        *,
        block: dict[str, Any] | None = None,
        scenario: dict[str, Any] | None = None,
    ) -> str:
        try:
            template = env.get_template(self.code_template_name)
        except TemplateNotFound:
            return ""
        return template.render(
            plugin=self.ui,
            block=block or {},
            data=(block or {}).get("data") or {},
            scenario=scenario or {},
        ).strip()


class PluginManager:
    def __init__(self, plugins_dirs: list[Path] | None = None) -> None:
        self.plugins_dirs = list(plugins_dirs) if plugins_dirs is not None else []
        self.plugins_dir = self.plugins_dirs[0] if self.plugins_dirs else PLUGINS_DIR
        self._plugins: list[BlockPlugin] | None = None
        self._by_type: dict[str, BlockPlugin] | None = None
        self._jinja_env: Environment | None = None

    def _resolved_dirs(self) -> list[Path]:
        if self.plugins_dirs:
            return [d for d in self.plugins_dirs if d.is_dir()]
        return plugin_search_dirs()

    def _jinja(self) -> Environment:
        if self._jinja_env is None:
            loaders = [FileSystemLoader(str(d)) for d in self._resolved_dirs()]
            if not loaders:
                loaders = [FileSystemLoader(str(BUNDLED_PLUGINS_DIR))]
            self._jinja_env = Environment(
                loader=ChoiceLoader(loaders) if len(loaders) > 1 else loaders[0],
                keep_trailing_newline=True,
                trim_blocks=False,
                lstrip_blocks=False,
            )
        return self._jinja_env

    def _scan_dir(self, plugins_dir: Path, seen_ids: set[str], seen_types: set[str]) -> list[BlockPlugin]:
        plugins: list[BlockPlugin] = []
        if not plugins_dir.is_dir():
            return plugins
        for folder in sorted(plugins_dir.iterdir()):
            if not folder.is_dir():
                continue
            if folder.name in seen_ids:
                continue
            ui_path = folder / "ui.json"
            if not ui_path.is_file():
                continue
            try:
                with open(ui_path, "r", encoding="utf-8") as f:
                    ui = json.load(f)
            except (OSError, json.JSONDecodeError):
                continue
            if not ui.get("type"):
                ui = {**ui, "type": folder.name}
            block_type = str(ui.get("type") or folder.name)
            if block_type in seen_types:
                continue
            code_file = folder / "code.py.jinja2"
            code_name = f"{folder.name}/code.py.jinja2" if code_file.is_file() else ""
            plugins.append(
                BlockPlugin(
                    id=folder.name,
                    path=folder,
                    ui=ui,
                    code_template_name=code_name,
                )
            )
            seen_ids.add(folder.name)
            seen_types.add(block_type)
        return plugins

    def reload(self) -> list[BlockPlugin]:
        self._jinja_env = None
        plugins: list[BlockPlugin] = []
        seen_ids: set[str] = set()
        seen_types: set[str] = set()
        for directory in self._resolved_dirs():
            plugins.extend(self._scan_dir(directory, seen_ids, seen_types))

        self._plugins = plugins
        self._by_type = {p.block_type: p for p in plugins}
        if plugins:
            self.plugins_dir = plugins[0].path.parent
        return plugins

    def list_plugins(self) -> list[BlockPlugin]:
        if self._plugins is None:
            self.reload()
        return list(self._plugins or [])

    def get_by_type(self, block_type: str) -> BlockPlugin | None:
        if self._by_type is None:
            self.reload()
        return (self._by_type or {}).get(block_type)

    def get_public_metadata(self) -> list[dict[str, Any]]:
        result = []
        for plugin in self.list_plugins():
            meta = dict(plugin.ui)
            meta["pluginId"] = plugin.id
            meta["builtin"] = is_builtin_plugin(plugin.id)
            meta["editable"] = not meta["builtin"]
            result.append(meta)
        return result

    def types_in_scenario(self, scenario: dict[str, Any]) -> set[str]:
        types: set[str] = set()
        for block in scenario.get("blocks") or []:
            typ = block.get("type")
            if typ:
                types.add(str(typ))
        return types

    def render_handler_for_type(
        self,
        block_type: str,
        scenario: dict[str, Any],
    ) -> str:
        plugin = self.get_by_type(block_type)
        if not plugin or not plugin.code_template_name:
            return ""
        blocks_of_type = [
            b for b in (scenario.get("blocks") or []) if b.get("type") == block_type
        ]
        return plugin.render_code(
            self._jinja(),
            block=blocks_of_type[0] if blocks_of_type else None,
            scenario=scenario,
        )

    def render_handler_definitions(self, scenario: dict[str, Any]) -> str:
        """Module-level handler functions and _TYPE_HANDLERS registry."""
        parts: list[str] = []
        registry_entries: list[str] = []
        seen: set[str] = set()

        for block in scenario.get("blocks") or []:
            typ = str(block.get("type") or "")
            if not typ or typ in seen:
                continue
            seen.add(typ)
            if typ not in get_executable_types(self):
                continue
            body = self.render_handler_for_type(typ, scenario)
            if not body:
                continue
            parts.append(body)
            safe = typ.replace("-", "_")
            registry_entries.append(f'    "{typ}": _type_handler_{safe},')

        if not registry_entries:
            return "_TYPE_HANDLERS = {}"

        registry = "_TYPE_HANDLERS = {\n" + "\n".join(registry_entries) + "\n}"
        return "\n\n".join(parts) + "\n\n" + registry

    def render_execute_dispatch(self, scenario: dict[str, Any]) -> str:
        """Body of execute_block: dispatch to plugin handler by block type."""
        executable = get_executable_types(self)
        has_handlers = any(
            str(b.get("type") or "") in executable for b in (scenario.get("blocks") or [])
        )
        if not has_handlers:
            return "    pass"
        return (
            "    handler = _TYPE_HANDLERS.get(typ)\n"
            "    if handler:\n"
            "        return await handler(bot, chat_id, user_id, block_id, ctx, data, disable)"
        )

    def render_handlers_for_scenario(self, scenario: dict[str, Any]) -> str:
        """Legacy single-string output (definitions + dispatch). Prefer split markers."""
        return (
            self.render_handler_definitions(scenario)
            + "\n\n"
            + self.render_execute_dispatch(scenario)
        )


_manager: PluginManager | None = None


def get_plugin_manager() -> PluginManager:
    global _manager
    if _manager is None:
        _manager = PluginManager()
        _manager.reload()
    return _manager
