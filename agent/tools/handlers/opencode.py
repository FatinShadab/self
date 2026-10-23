"""Opencode coding delegation and build route decision handlers."""
from __future__ import annotations

from typing import Any


def ensure_opencode(runner: Any) -> Any:
    """Lazily initialize OpencodeDelegator on runner if not already set."""
    if runner.opencode is None:
        from agent.opencode.wrapper import OpencodeDelegator

        runner.opencode = OpencodeDelegator(
            workspace=runner.workspace,
            model_decisions=ensure_model_decisions(runner),
        )
    return runner.opencode


def ensure_model_decisions(runner: Any) -> Any:
    """Lazily initialize ModelDecisions for recording build routes and outcomes."""
    if runner.model_decisions is None:
        from agent.helper_models.model_decisions import ModelDecisions
        from agent.infra.event_log import EventLogger

        logger = getattr(runner, "logger", None) or EventLogger(runner.workspace / "logs" / "actions.jsonl")
        runner.model_decisions = ModelDecisions(runner.workspace, logger, None, None, "default_session")
    return runner.model_decisions


def handle_opencode_status(runner: Any) -> dict[str, Any]:
    """Check opencode availability status."""
    return ensure_opencode(runner).status()


def handle_delegate_coding(runner: Any, **kwargs: Any) -> dict[str, Any]:
    """Delegate a scoped coding task to opencode in a sandbox."""
    return ensure_opencode(runner).delegate_coding(**kwargs)


def handle_apply_delegation(runner: Any, delegation_id: str) -> dict[str, Any]:
    """Apply a completed delegation's changes to the real repository."""
    return ensure_opencode(runner).apply_delegation(delegation_id)


def handle_discard_delegation(runner: Any, delegation_id: str) -> dict[str, Any]:
    """Discard a delegation record and delete its sandbox directory."""
    return ensure_opencode(runner).discard_delegation(delegation_id)


def handle_record_build_route(runner: Any, **kwargs: Any) -> dict[str, Any]:
    """Record a build route choice (self or opencode)."""
    return ensure_model_decisions(runner).record_build_route(**kwargs)


def handle_record_build_outcome(runner: Any, **kwargs: Any) -> dict[str, Any]:
    """Record the final outcome of a build task."""
    return ensure_model_decisions(runner).record_build_outcome(**kwargs)


def handle_build_route_stats(runner: Any, limit: int = 10) -> dict[str, Any]:
    """Read recent build route history and statistics."""
    return ensure_model_decisions(runner).build_route_stats(
        limit=limit,
        opencode_status=runner.opencode_status(),
    )


def get_opencode_tool_definitions() -> list[dict[str, Any]]:
    """Return schema definitions for opencode delegation tools."""
    from agent.opencode.tools import OPENCODE_TOOL_DEFINITIONS

    return list(OPENCODE_TOOL_DEFINITIONS)
