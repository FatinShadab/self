"""Telemetry and call statistics recording for model registry."""
from __future__ import annotations

import time
from typing import Any

from agent.llm.registry.constants import MAX_COUNTER


def record_call_stats(
    data: dict[str, Any],
    name: str,
    failed: bool,
    latency_ms: int,
    not_found: bool = False,
) -> None:
    """Update measured call, token, latency, and failure statistics."""
    entry = next((item for item in data.get("models", []) if item.get("name") == name), None)
    if entry is None:
        return
    latency = min(MAX_COUNTER, max(0, int(latency_ms)))
    stats = entry["measured_stats"]
    stats["calls"] = min(MAX_COUNTER, stats["calls"] + 1)
    stats["failures"] = min(MAX_COUNTER, stats["failures"] + int(failed))
    stats["consecutive_failures"] = (
        min(MAX_COUNTER, stats["consecutive_failures"] + 1) if failed else 0
    )
    stats["latency_ms_total"] = min(MAX_COUNTER, stats["latency_ms_total"] + latency)
    stats["latency_ms_min"] = (
        latency if stats["latency_ms_min"] is None else min(stats["latency_ms_min"], latency)
    )
    stats["latency_ms_max"] = (
        latency if stats["latency_ms_max"] is None else max(stats["latency_ms_max"], latency)
    )
    entry["status"] = "not_found" if not_found else "last_call_failed" if failed else "reachable"
    entry["status_message"] = (
        "The endpoint did not recognize this configured model name." if not_found else ""
    )
    entry["last_failure_at"] = time.time() if failed else None


def mark_not_found_status(data: dict[str, Any], name: str) -> None:
    """Mark a configured model as unavailable after a failed lookup."""
    entry = next((item for item in data.get("models", []) if item.get("name") == name), None)
    if entry is None:
        return
    entry["status"] = "not_found"
    entry["status_message"] = "The endpoint did not recognize this configured model name."
    entry["last_failure_at"] = time.time()


def record_output_failure_stats(data: dict[str, Any], name: str) -> None:
    """Count an unusable response already counted as a successful API call."""
    entry = next((item for item in data.get("models", []) if item.get("name") == name), None)
    if entry is None:
        return
    stats = entry["measured_stats"]
    stats["failures"] = min(MAX_COUNTER, stats["failures"] + 1)
    stats["consecutive_failures"] = min(MAX_COUNTER, stats["consecutive_failures"] + 1)
    entry["status"] = "last_call_failed"
    entry["status_message"] = "The last response was empty or truncated."
    entry["last_failure_at"] = time.time()


def record_truncated_call_stats(data: dict[str, Any], name: str) -> None:
    """Count a response that ended in max_tokens/truncation without marking clean success."""
    entry = next((item for item in data.get("models", []) if item.get("name") == name), None)
    if entry is not None:
        stats = entry["measured_stats"]
        stats["truncated_calls"] = min(MAX_COUNTER, stats.get("truncated_calls", 0) + 1)


def record_network_error_stats(data: dict[str, Any], name: str, *, latency_ms: int = 0) -> None:
    """Record a transient network/connection error without counting it as a model failure."""
    entry = next((item for item in data.get("models", []) if item.get("name") == name), None)
    if entry is not None:
        latency = min(MAX_COUNTER, max(0, int(latency_ms)))
        stats = entry["measured_stats"]
        stats["network_errors"] = min(MAX_COUNTER, stats.get("network_errors", 0) + 1)
        stats["calls"] = min(MAX_COUNTER, stats["calls"] + 1)
        stats["latency_ms_total"] = min(MAX_COUNTER, stats["latency_ms_total"] + latency)
        if stats["latency_ms_min"] is None:
            stats["latency_ms_min"] = latency
        else:
            stats["latency_ms_min"] = min(stats["latency_ms_min"], latency)
        stats["latency_ms_max"] = max(stats.get("latency_ms_max") or 0, latency)
