"""SELF plugin system with dynamic plug, unplug, and hash pinning."""
from __future__ import annotations

from agent.plugins.manifest import (
    CORE_API_VERSION,
    DeclaredNeeds,
    PluginAction,
    PluginCommand,
    PluginManifest,
    PluginManifestValidationError,
    PluginSensor,
    RESERVED_SLASH_COMMANDS,
    is_core_api_compatible,
    parse_manifest,
)
from agent.plugins.manager import (
    Plugin,
    PluginManager,
    compute_plugin_hash,
)

__all__ = [
    "CORE_API_VERSION",
    "DeclaredNeeds",
    "Plugin",
    "PluginAction",
    "PluginCommand",
    "PluginManager",
    "PluginManifest",
    "PluginManifestValidationError",
    "PluginSensor",
    "RESERVED_SLASH_COMMANDS",
    "compute_plugin_hash",
    "is_core_api_compatible",
    "parse_manifest",
]
