"""Dynamic scenario → main.py compiler using /plugins Jinja2 templates."""

from __future__ import annotations

import logging
from typing import Any

from jinja2 import TemplateSyntaxError

from backend.core.plugin_manager import PluginManager, get_executable_types, get_plugin_manager
from backend.core.scenario_deps import PhantomNodeError, validate_scenario_plugins

log = logging.getLogger(__name__)

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
        try:
            definitions = self.plugins.render_handler_definitions(scenario)
            dispatch = self.plugins.render_execute_dispatch(scenario)
        except TemplateSyntaxError as exc:
            name = getattr(exc, "name", None) or getattr(exc, "filename", None) or "plugin"
            log.error(
                "Jinja TemplateSyntaxError during scenario compile (template=%s): %s",
                name,
                exc,
            )
            raise RuntimeError(
                f"Scenario compile failed for block/template '{name}': {exc}"
            ) from exc
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
        from backend.core.bot_runtime_helpers import ensure_button_layout_helpers
        from backend.core.bot_runtime_data import (
            ensure_bot_data_runtime,
            patch_init_user_db,
            patch_resolve_text,
            patch_scoped_field_setters,
        )
        from backend.core.ai_spam_guard import ensure_ai_spam_guard_runtime
        from backend.core.channel_hub_runtime import patch_channel_hub_runtime

        code = ensure_button_layout_helpers(code)
        code = patch_init_user_db(code)
        code = ensure_bot_data_runtime(code)
        code = ensure_ai_spam_guard_runtime(code)
        code = patch_resolve_text(code)
        code = patch_scoped_field_setters(code)
        code = patch_channel_hub_runtime(code)
        return code

    BuildPythonScript = build_python_script

    def _validate_scenario_plugins(self, scenario: dict[str, Any]) -> None:
        validate_scenario_plugins(scenario, self.plugins)
        missing_handlers: list[str] = []
        for typ in self.plugins.types_in_scenario(scenario):
            if typ not in get_executable_types(self.plugins):
                continue
            try:
                body = self.plugins.render_handler_for_type(typ, scenario)
            except TemplateSyntaxError as exc:
                log.error(
                    "Jinja TemplateSyntaxError for block type '%s': %s",
                    typ,
                    exc,
                )
                continue
            if not body:
                missing_handlers.append(typ)
        if missing_handlers:
            label = (
                missing_handlers[0]
                if len(missing_handlers) == 1
                else ", ".join(sorted(missing_handlers))
            )
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
