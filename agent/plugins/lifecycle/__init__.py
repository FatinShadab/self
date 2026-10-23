"""Plugin lifecycle management, discovery, dynamic tools, and hash verification."""
from __future__ import annotations

from agent.plugins.lifecycle.models import CORE_TOOL_NAMES, Plugin
from agent.plugins.lifecycle.hashing import compute_plugin_hash

__all__ = [
    "CORE_TOOL_NAMES",
    "Plugin",
    "compute_plugin_hash",
]
