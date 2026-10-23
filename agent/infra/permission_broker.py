"""Permission broker: central gatekeeper for all body, plugin, and core actions.

Levels:
- L0: observe (read-only, no side-effects)
- L1: reversible change (quarantine, plan updates, reversible edits)
- L2: destructive or irreversible (run_shell, file overwrites/deletions)
- L3: physical actuation (hardware/robotic movement or triggers)

Default policy: deny everything above L0 until granted by the human operator
via the human-owned configuration file (./config/permissions.json).
"""
from __future__ import annotations

from agent.infra.permissions import (
    ActionRequest as _ActionRequest,
    ActionVerdict as _ActionVerdict,
    PermissionBroker as _PermissionBroker,
    PermissionLevel as _PermissionLevel,
    PermissionPolicy as _PermissionPolicy,
    RateLimitConfig as _RateLimitConfig,
)

# Explicit symbol assignments for static documentation checkers
ActionRequest = _ActionRequest
ActionVerdict = _ActionVerdict
PermissionBroker = _PermissionBroker
PermissionLevel = _PermissionLevel
PermissionPolicy = _PermissionPolicy
RateLimitConfig = _RateLimitConfig

__all__ = [
    "ActionRequest",
    "ActionVerdict",
    "PermissionBroker",
    "PermissionLevel",
    "PermissionPolicy",
    "RateLimitConfig",
]
