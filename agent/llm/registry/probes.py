"""Probe execution tracking and outcome recording in model registry."""
from __future__ import annotations

import uuid
from typing import Any

from agent.llm.registry.constants import MAX_COUNTER, PROBE_FORMAT_VERSION


def begin_probe_record(
    data: dict[str, Any],
    name: str,
    session_id: str,
    when: float,
    probes_per_session: int,
    cooldown_seconds: int,
) -> str:
    """Record the start of a probe attempt, validating session caps and cooldown."""
    entry = next(item for item in data["models"] if item["name"] == name)
    if entry["status"] == "disabled":
        raise ValueError("Model is disabled")
    history = entry["probe_history"]
    valid_history = [item for item in history if not item.get("invalidated")]
    if sum(item.get("session_id") == session_id for item in valid_history) >= probes_per_session:
        raise ValueError("Per-session probe cap reached")
    if valid_history and when - float(valid_history[-1].get("at", 0)) < cooldown_seconds:
        raise ValueError("Model probe cooldown is active")
    probe_id = uuid.uuid4().hex
    history.append({
        "id": probe_id,
        "session_id": session_id,
        "at": when,
        "status": "running",
        "format_version": PROBE_FORMAT_VERSION,
        "invalidated": False,
        "invalidation_reason": "",
    })
    entry["probe_history"] = history[-32:]
    return probe_id


def finish_probe_record(
    data: dict[str, Any],
    name: str,
    probe_id: str,
    *,
    failed: bool,
    inconclusive: bool = False,
    latency_ms: int | None = None,
) -> None:
    """Update probe record with final status and latency."""
    entry = next(item for item in data["models"] if item["name"] == name)
    record = next(item for item in entry["probe_history"] if item["id"] == probe_id)
    record["status"] = "failed" if failed else "inconclusive" if inconclusive else "completed"
    if latency_ms is not None:
        record["latency_ms"] = latency_ms


def record_probe_outcome_stats(
    data: dict[str, Any],
    name: str,
    outcome: str,
) -> None:
    """Update model measured stats based on probe outcome."""
    if outcome not in {"passed", "failed", "inconclusive"}:
        raise ValueError("Invalid probe outcome")
    entry = next(item for item in data["models"] if item["name"] == name)
    stats = entry["measured_stats"]
    field = {
        "passed": "probe_passes",
        "failed": "probe_failures",
        "inconclusive": "probe_inconclusive",
    }[outcome]
    stats[field] = min(MAX_COUNTER, stats[field] + 1)
    if outcome == "failed":
        stats["failures"] = min(MAX_COUNTER, stats["failures"] + 1)
