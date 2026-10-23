"""System capability requests and core harness patch proposal handlers."""
from __future__ import annotations

from typing import Any


def handle_request_capability(
    capabilities: Any,
    kind: str,
    summary: str,
    reason: str,
    provider: str = "",
    env_names: list[str] | None = None,
    signup_url: str = "",
) -> dict[str, Any]:
    """Record a human-facing request for expanded capabilities."""
    if capabilities is None:
        raise RuntimeError("capability request system is not configured")
    return capabilities.request(kind, summary, reason, provider, env_names, signup_url)


def handle_propose_core_patch(
    identity: Any,
    name: str,
    diff: str,
    reasoning: str,
) -> dict[str, Any]:
    """Reject direct harness changes and record a proposed patch instead."""
    if identity is None:
        raise RuntimeError("identity and core-patch system is not configured")
    return identity.propose_core_patch(name, diff, reasoning)
