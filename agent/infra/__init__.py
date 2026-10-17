"""SELF infra package: event logging, file locking, process execution, permissions, audit, and hardening."""
from __future__ import annotations

from agent.infra.audit_trail import AuditTrail
from agent.infra.egress_allowlist import Allowlist
from agent.infra.event_log import EventLogger
from agent.infra.file_lock import locked_file
from agent.infra.hardening import CapabilityRequests, DailyTokenLedger, RunCheckpoint
from agent.infra.permission_broker import (
    ActionRequest,
    ActionVerdict,
    PermissionBroker,
    PermissionLevel,
    PermissionPolicy,
    RateLimitConfig,
)
from agent.infra.process_runner import run_process
from agent.infra.provider_calls import reserve_provider_call
from agent.infra.stop_watcher import StopWatcher
from agent.infra.untrusted import (
    PERMISSION_RULE,
    SAFETY_CRITICAL_CONSTANTS,
    STOP_RULE,
    UNTRUSTED_DATA_RULE,
    get_safety_critical_constant,
    is_wrapped,
    load_editable_extension,
    unwrap_untrusted,
    validate_extension_content,
    wrap_untrusted,
)

__all__ = [
    "ActionRequest",
    "ActionVerdict",
    "Allowlist",
    "AuditTrail",
    "CapabilityRequests",
    "DailyTokenLedger",
    "EventLogger",
    "PERMISSION_RULE",
    "PermissionBroker",
    "PermissionLevel",
    "PermissionPolicy",
    "RateLimitConfig",
    "RunCheckpoint",
    "SAFETY_CRITICAL_CONSTANTS",
    "STOP_RULE",
    "StopWatcher",
    "UNTRUSTED_DATA_RULE",
    "get_safety_critical_constant",
    "is_wrapped",
    "load_editable_extension",
    "locked_file",
    "run_process",
    "unwrap_untrusted",
    "validate_extension_content",
    "wrap_untrusted",
]
