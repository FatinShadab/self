"""Permission levels and capability limits for harness tools."""
from __future__ import annotations

from agent.infra.permission_broker import PermissionLevel

DEFAULT_OUTPUT_CAP: int = 20_000

TOOL_PERMISSION_LEVELS: dict[str, PermissionLevel] = {
    # L0: observe
    "read_file": PermissionLevel.L0,
    "list_dir": PermissionLevel.L0,
    "http_get": PermissionLevel.L0,
    "probe_local_ollama": PermissionLevel.L0,
    "read_plan": PermissionLevel.L0,
    "list_models": PermissionLevel.L0,
    "probe_model": PermissionLevel.L0,
    "research_model": PermissionLevel.L0,
    "ask_model": PermissionLevel.L0,
    "research_provider": PermissionLevel.L0,
    "ask_brain": PermissionLevel.L0,
    "benchmark_providers": PermissionLevel.L0,
    # L0: observe (opencode)
    "opencode_status": PermissionLevel.L0,
    "build_route_stats": PermissionLevel.L0,
    # L1: reversible change
    "discard_delegation": PermissionLevel.L1,
    "record_build_route": PermissionLevel.L1,
    "record_build_outcome": PermissionLevel.L1,
    "update_plan": PermissionLevel.L1,
    "update_environment_map": PermissionLevel.L1,
    "record_model_assessment": PermissionLevel.L1,
    "record_delegation_outcome": PermissionLevel.L1,
    "record_provider_verification": PermissionLevel.L1,
    "request_provider_key": PermissionLevel.L1,
    "request_capability": PermissionLevel.L1,
    "propose_core_patch": PermissionLevel.L1,
    # L2: destructive / irreversible
    "run_shell": PermissionLevel.L2,
    "write_file": PermissionLevel.L2,
    "create_tool": PermissionLevel.L2,
    "delegate_coding": PermissionLevel.L2,
    "apply_delegation": PermissionLevel.L2,
}

REVERSIBLE_TOOL_NAMES: frozenset[str] = frozenset({
    "update_plan",
    "update_environment_map",
    "record_model_assessment",
    "record_delegation_outcome",
    "record_provider_verification",
    "request_provider_key",
    "request_capability",
    "propose_core_patch",
})
