"""SELF plugin system with dynamic plug, unplug, and hash pinning."""
from __future__ import annotations

from agent.plugins.manifest import (
    CORE_API_VERSION,
    DeclaredNeeds,
    PluginAction,
    PluginManifest,
    PluginManifestValidationError,
    PluginSensor,
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
    "PluginManager",
    "PluginManifest",
    "PluginManifestValidationError",
    "PluginSensor",
    "compute_plugin_hash",
    "is_core_api_compatible",
    "parse_manifest",
]
