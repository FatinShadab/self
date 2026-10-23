"""Build route decision tracking, outcome recording, and comparative statistics."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
import statistics
from typing import Any
import uuid


def record_build_route(
    decisions: Any,
    task: str,
    route: str,
    reasons: str,
    expected_effort: str,
    forced_by: str | None = None,
) -> dict[str, Any]:
    """Record a decision to build via 'self' or delegate to 'opencode'."""
    route_clean = str(route).strip().lower()
    if route_clean not in {"self", "opencode"}:
        raise ValueError(f"Route must be 'self' or 'opencode', got {route!r}")

    forced_clean = str(forced_by).strip() if forced_by else None
    if forced_clean and forced_clean.startswith("forced:"):
        forced_clean = forced_clean[7:]

    origin = f"forced:{forced_clean}" if forced_clean else "agent"

    call_id = uuid.uuid4().hex
    record = {
        "call_id": call_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_id": decisions.session_id,
        "task_id": decisions.active_task_id or task[:80],
        "task": task,
        "task_type": "build_route",
        "route": route_clean,
        "reason": reasons,
        "reasons": reasons,
        "expected_effort": str(expected_effort),
        "forced_by": forced_clean,
        "origin": origin,
        "source": "checkpoint:build_route",
        "status": "selected",
    }
    decisions._append(record)
    return record


def record_build_outcome(
    decisions: Any,
    task_id: str,
    result: str,
    notes: str | None = None,
    *,
    route: str | None = None,
    duration: float = 0.0,
    acceptance_passed: bool | None = None,
    retries: int = 0,
    provider: str | None = None,
    model: str | None = None,
    forced_by: str | None = None,
) -> dict[str, Any]:
    """Record the outcome of a build task (for route 'self' or manual completion)."""
    result_clean = str(result).strip().lower()
    decision_rows = decisions.last_decisions(limit=100)
    matched_decision = None
    for dec in reversed(decision_rows):
        if dec.get("task_type") == "build_route" and (
            dec.get("task_id") == task_id
            or dec.get("task") == task_id
            or dec.get("call_id") == task_id
            or (isinstance(dec.get("task"), str) and task_id in dec["task"])
        ):
            matched_decision = dec
            break

    rec_route = route or (matched_decision.get("route") if matched_decision else "self")
    reasons = (
        matched_decision.get("reasons")
        if matched_decision and matched_decision.get("reasons")
        else (notes or "")
    )
    expected_effort = (
        matched_decision.get("expected_effort")
        if matched_decision and matched_decision.get("expected_effort")
        else "unknown"
    )
    rec_forced_by = forced_by or (matched_decision.get("forced_by") if matched_decision else None)

    if acceptance_passed is None:
        acceptance_passed = result_clean == "accepted"

    return decisions.build_outcomes.append(
        task_id=task_id,
        route=rec_route,
        reasons=reasons,
        expected_effort=expected_effort,
        result=result_clean,
        acceptance_passed=acceptance_passed,
        duration=duration,
        retries=retries,
        provider=provider,
        model=model,
        forced_by=rec_forced_by,
        notes=notes,
        session_id=decisions.session_id,
    )


def build_route_stats(
    decisions: Any,
    limit: int = 10,
    opencode_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute summary statistics and recent records for build routes."""
    all_outcomes = decisions.build_outcomes.last_outcomes(limit=None)
    non_forced = [r for r in all_outcomes if not r.get("forced_by")]

    counts = {"self": 0, "opencode": 0, "total": len(non_forced)}
    passes = {"self": 0, "opencode": 0}
    durations: dict[str, list[float]] = {"self": [], "opencode": []}

    for r in non_forced:
        route = r.get("route", "self")
        if route in counts:
            counts[route] += 1
        if r.get("result") == "accepted" or r.get("acceptance_passed") is True:
            if route in passes:
                passes[route] += 1
        dur = float(r.get("duration", 0.0) or 0.0)
        if dur > 0 and route in durations:
            durations[route].append(dur)

    pass_rate = {
        "self": round(passes["self"] / counts["self"], 3) if counts["self"] > 0 else None,
        "opencode": round(passes["opencode"] / counts["opencode"], 3) if counts["opencode"] > 0 else None,
    }

    median_duration = {
        "self": round(statistics.median(durations["self"]), 3) if durations["self"] else None,
        "opencode": round(statistics.median(durations["opencode"]), 3) if durations["opencode"] else None,
    }

    note = None
    if len(non_forced) >= 10:
        last_10 = non_forced[-10:]
        route_10_counts = Counter(r.get("route") for r in last_10)
        most_common_route, count = route_10_counts.most_common(1)[0]
        if count / 10.0 > 0.8:
            note = "I have mostly used one route lately; a comparison on a similar task may be worth doing when it fits."

    recent_slice = all_outcomes[-limit:] if limit else all_outcomes
    recent_lines = []
    for r in recent_slice:
        ts = r.get("timestamp", "")[:19]
        route = r.get("route", "unknown")
        forced_lbl = f" (forced:{r['forced_by']})" if r.get("forced_by") else ""
        res = r.get("result", "unknown")
        task = r.get("task_id", "")[:40]
        dur = r.get("duration", 0.0)
        recent_lines.append(f"[{ts}] route={route}{forced_lbl} task={task} result={res} duration={dur}s")

    usability_data = opencode_status or {"usable": False, "reason": "status not queried"}

    result_payload = {
        "ok": True,
        "counts": counts,
        "pass_rate": pass_rate,
        "median_duration_seconds": median_duration,
        "recent_records": recent_lines,
        "opencode_usability": usability_data,
        "note": note,
    }

    max_cap = 3000
    while len(json.dumps(result_payload, ensure_ascii=False)) > max_cap and result_payload["recent_records"]:
        result_payload["recent_records"].pop(0)

    return result_payload


__all__ = [
    "record_build_route",
    "record_build_outcome",
    "build_route_stats",
]
