"""Data models and constants for the plugin system."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from agent.plugins.manifest import PluginManifest
from agent.tools.base_tools import TOOL_DEFINITIONS
from agent.tools.tool_registry import CREATE_TOOL_DEFINITION

# Set of all core tool names that plugins can never collide with or override
CORE_TOOL_NAMES = frozenset(
    [tool["name"] for tool in TOOL_DEFINITIONS] + [CREATE_TOOL_DEFINITION["name"]]
)


@dataclass
class Plugin:
    """Runtime representation of a discovered or loaded plugin."""

    manifest: PluginManifest
    plugin_dir: Path
    is_shipped: bool
    module: Any | None = None
    tools: dict[str, Callable[..., Any]] = field(default_factory=dict)
    tool_specs: list[dict[str, Any]] = field(default_factory=list)
    state_dir: Path | None = None
    is_loaded: bool = False
    is_enabled: bool = False
    load_error: str | None = None
