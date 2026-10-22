"""Opencode delegation wrapper package for the Self agent."""
from __future__ import annotations

from agent.opencode.sandbox import (
    DEFAULT_ALLOWED_ROOTS,
    SandboxManager,
    build_opencode_env,
    is_protected_path,
)
from agent.opencode.status import (
    OpencodeStatusTracker,
    classify_failure,
    parse_reset_time,
)
from agent.opencode.tools import (
    OPENCODE_TOOL_DEFINITIONS,
    OPENCODE_TOOL_PERMISSIONS,
)
from agent.opencode.wrapper import OpencodeDelegator

__all__ = [
    "DEFAULT_ALLOWED_ROOTS",
    "OPENCODE_TOOL_DEFINITIONS",
    "OPENCODE_TOOL_PERMISSIONS",
    "OpencodeDelegator",
    "OpencodeStatusTracker",
    "SandboxManager",
    "build_opencode_env",
    "classify_failure",
    "is_protected_path",
    "parse_reset_time",
]
