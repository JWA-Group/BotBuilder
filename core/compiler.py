"""Re-export compiler for desktop / core package layout."""

from backend.core.compiler import (
    PLUGIN_DEFINITIONS_MARKER,
    PLUGIN_DISPATCH_MARKER,
    CodeGenerator,
)
from backend.core.scenario_deps import PhantomNodeError

__all__ = [
    "CodeGenerator",
    "PhantomNodeError",
    "PLUGIN_DEFINITIONS_MARKER",
    "PLUGIN_DISPATCH_MARKER",
    "PLUGIN_HANDLERS_MARKER",
]

PLUGIN_HANDLERS_MARKER = PLUGIN_DISPATCH_MARKER
