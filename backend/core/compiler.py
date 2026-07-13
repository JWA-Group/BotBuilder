"""Dynamic scenario → main.py compiler using /plugins Jinja2 templates."""

from __future__ import annotations

from typing import Any

from backend.core.plugin_manager import PluginManager, get_executable_types, get_plugin_manager
from backend.core.scenario_deps import PhantomNodeError, validate_scenario_plugins

PLUGIN_DEFINITIONS_MARKER = "__PLUGIN_HANDLER_DEFINITIONS__"
PLUGIN_DISPATCH_MARKER = "__PLUGIN_EXECUTE_DISPATCH__"
# Backward compatibility
PLUGIN_HANDLERS_MARKER = PLUGIN_DISPATCH_MARKER


class CodeGenerator:
    """Stitches plugin code templates into the bot runtime shell."""

    def __init__(self, plugin_manager: PluginManager | None = None) -> None:
        self.plugins = plugin_manager or get_plugin_manager()

    def build_execute_handlers(self, scenario: dict[str, Any]) -> str:
        return self.plugins.render_handlers_for_scenario(scenario)

    def build_python_script(
        self,
        scenario: dict[str, Any],
        shell_template: str,
        *,
        platform: str = "telegram",
    ) -> str:
        _ = platform
        self._validate_scenario_plugins(scenario)
        definitions = self.plugins.render_handler_definitions(scenario)
        dispatch = self.plugins.render_execute_dispatch(scenario)
        if PLUGIN_DEFINITIONS_MARKER not in shell_template:
            raise ValueError(
                f"Shell template must contain marker {PLUGIN_DEFINITIONS_MARKER!r}"
            )
        if PLUGIN_DISPATCH_MARKER not in shell_template:
            raise ValueError(
                f"Shell template must contain marker {PLUGIN_DISPATCH_MARKER!r}"
            )
        code = shell_template.replace(PLUGIN_DEFINITIONS_MARKER, definitions)
        code = code.replace(PLUGIN_DISPATCH_MARKER, dispatch)
        return code

    BuildPythonScript = build_python_script

    def _validate_scenario_plugins(self, scenario: dict[str, Any]) -> None:
        validate_scenario_plugins(scenario, self.plugins)
        missing_handlers: list[str] = []
        for typ in self.plugins.types_in_scenario(scenario):
            if typ not in get_executable_types(self.plugins):
                continue
            body = self.plugins.render_handler_for_type(typ, scenario)
            if not body:
                missing_handlers.append(typ)
        if missing_handlers:
            label = missing_handlers[0] if len(missing_handlers) == 1 else ", ".join(sorted(missing_handlers))
            raise PhantomNodeError(label, missing=sorted(set(missing_handlers)))

    @staticmethod
    def build_deployment_artifacts(platform: str = "telegram", bot_id: int = 0) -> dict[str, str]:
        """Docker + compose + requirements for production export."""
        from backend.core.deploy_bundle import (
            render_docker_compose,
            render_dockerfile,
            render_requirements_txt,
        )

        return {
            "Dockerfile": render_dockerfile(platform),
            "docker-compose.yml": render_docker_compose(bot_id),
            "requirements.txt": render_requirements_txt(platform),
        }
