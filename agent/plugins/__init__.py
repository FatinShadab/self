"""SELF plugin system with dynamic plug, unplug, and hash pinning."""
from __future__ import annotations

from agent.plugins.manifest import (
    DeclaredNeeds,
    PluginAction,
    PluginManifest,
    PluginManifestValidationError,
    PluginSensor,
    parse_manifest,
)
from agent.plugins.manager import (
    Plugin,
    PluginManager,
    compute_plugin_hash,
)

__all__ = [
    "DeclaredNeeds",
    "Plugin",
    "PluginAction",
    "PluginManager",
    "PluginManifest",
    "PluginManifestValidationError",
    "PluginSensor",
    "compute_plugin_hash",
    "parse_manifest",
]
