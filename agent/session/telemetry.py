"""Runtime telemetry tracking and status snapshots for wake sessions."""
from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any


@dataclass
class WakeStatus:
    """Current identity, timing, and usage of the wake session."""

    session_id: str = ""
    iteration: int = 0
    tokens_used: int = 0
    active_model: str = "uninitialized"
    active_provider: str = "uninitialized"
    started_monotonic: float = 0.0
    last_human_input: float = 0.0


@dataclass
class RuntimeTelemetry:
    """Live, non-secret runtime facts used by the presence panel."""

    state: str = "STARTING"
    active_calls: int = 0
    total_calls: int = 0
    completed_calls: int = 0
    failed_calls: int = 0
    calls_by_ai: dict[str, int] = field(default_factory=dict)
    current_ai: str = "-"
    last_ai: str = "-"
    run_tokens_used: int = 0
    run_budget: int = 0
    daily_used: int = 0
    daily_reserved: int = 0
    daily_cap: int = 0
    daily_blocked: bool = False
    current_activity: str = ""
    active_cycle: int = 0


def update_telemetry(
    telemetry: RuntimeTelemetry,
    record: dict[str, Any],
    lock: threading.Lock | None = None,
) -> None:
    """Update runtime telemetry fields from an event log record."""
    event = str(record.get("event", ""))

    def _apply() -> None:
        if event == "run_started":
            telemetry.state = "THINKING"
            telemetry.active_cycle = 0
            telemetry.run_budget = int(record.get("token_budget", 0) or telemetry.run_budget)
            telemetry.daily_cap = int(record.get("daily_token_budget", 0) or telemetry.daily_cap)
        elif event == "cycle_started":
            telemetry.active_cycle = int(record.get("cycle", 0) or 0)
        elif event == "cycle_completed":
            telemetry.active_cycle = 0
        elif event == "llm_call_started":
            ai = f"{record.get('provider', 'unknown')}/{record.get('model', 'unknown')}"
            telemetry.active_calls += 1
            telemetry.total_calls += 1
            telemetry.current_ai = ai
            telemetry.last_ai = ai
            telemetry.calls_by_ai[ai] = telemetry.calls_by_ai.get(ai, 0) + 1
            telemetry.state = "THINKING"
        elif event == "llm_call_completed":
            telemetry.active_calls = max(0, telemetry.active_calls - 1)
            telemetry.completed_calls += 1
            telemetry.state = "THINKING" if telemetry.active_calls else "WORKING"
        elif event == "provider_call_completed":
            ai = f"{record.get('provider', 'unknown')}/{record.get('model', 'unknown')}"
            telemetry.total_calls += 1
            telemetry.completed_calls += 1
            telemetry.current_ai = ai
            telemetry.last_ai = ai
            telemetry.calls_by_ai[ai] = telemetry.calls_by_ai.get(ai, 0) + 1
            telemetry.state = "WORKING"
        elif event in {"llm_call_failed", "provider_call_failed", "provider_call_unavailable"}:
            telemetry.active_calls = max(0, telemetry.active_calls - 1)
            telemetry.failed_calls += 1
            if event != "llm_call_failed":
                ai = f"{record.get('provider', 'unknown')}/{record.get('model', 'unknown')}"
                telemetry.total_calls += 1
                telemetry.last_ai = ai
                telemetry.calls_by_ai[ai] = telemetry.calls_by_ai.get(ai, 0) + 1
            telemetry.state = "WORKING"
        elif event == "tool_call":
            telemetry.state = "USING TOOL"
        elif event == "tool_result":
            telemetry.state = "WORKING"
        elif event == "token_spend":
            telemetry.run_tokens_used = int(record.get("run_tokens_used", telemetry.run_tokens_used) or 0)
            reported_budget = int(record.get("run_token_budget", telemetry.run_budget) or 0)
            if telemetry.run_budget <= reported_budget:
                telemetry.run_budget = reported_budget
        elif event == "run_token_budget_adapted":
            telemetry.run_budget = int(record.get("new_budget", telemetry.run_budget) or 0)
        elif event == "daily_token_budget_updated":
            telemetry.daily_used = int(record.get("used", telemetry.daily_used) or 0)
            telemetry.daily_reserved = int(record.get("reserved", telemetry.daily_reserved) or 0)
            telemetry.daily_cap = int(record.get("cap", telemetry.daily_cap) or 0)
        elif event == "daily_token_budget_blocked":
            telemetry.daily_blocked = True
            telemetry.daily_used = int(record.get("used", telemetry.daily_used) or 0)
            telemetry.daily_reserved = int(record.get("reserved", telemetry.daily_reserved) or 0)
            telemetry.daily_cap = int(record.get("cap", telemetry.daily_cap) or 0)
            telemetry.state = "WAITING FOR HUMAN"
        elif event == "run_completed":
            telemetry.active_cycle = 0
            telemetry.state = "IDLE" if record.get("reason") != "human_request_pending" else "WAITING FOR HUMAN"

    if lock is not None:
        with lock:
            _apply()
    else:
        _apply()


def build_runtime_snapshot(
    telemetry: RuntimeTelemetry,
    activity: deque[str] | list[str],
    lock: threading.Lock | None = None,
) -> dict[str, Any]:
    """Return a dictionary snapshot of current runtime telemetry."""
    def _snapshot() -> dict[str, Any]:
        effort_level = "low"
        if telemetry.state in {"WORKING", "USING TOOL"}:
            effort_level = "high"
        elif "THINK" in telemetry.state:
            effort_level = "medium"
        elif telemetry.active_calls > 1:
            effort_level = "high"

        return {
            "state": telemetry.state,
            "effort_level": effort_level,
            "active_calls": telemetry.active_calls,
            "total_calls": telemetry.total_calls,
            "completed_calls": telemetry.completed_calls,
            "failed_calls": telemetry.failed_calls,
            "calls_by_ai": dict(telemetry.calls_by_ai),
            "current_ai": telemetry.current_ai,
            "last_ai": telemetry.last_ai,
            "run_tokens_used": telemetry.run_tokens_used,
            "run_budget": telemetry.run_budget,
            "daily_used": telemetry.daily_used,
            "daily_reserved": telemetry.daily_reserved,
            "daily_cap": telemetry.daily_cap,
            "daily_blocked": telemetry.daily_blocked,
            "current_activity": telemetry.current_activity,
            "active_cycle": telemetry.active_cycle,
            "activity": list(activity)[-80:],
        }

    if lock is not None:
        with lock:
            return _snapshot()
    return _snapshot()


__all__ = [
    "WakeStatus",
    "RuntimeTelemetry",
    "update_telemetry",
    "build_runtime_snapshot",
]
