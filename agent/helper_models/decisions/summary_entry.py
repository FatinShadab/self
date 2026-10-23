"""Summary entry formatting for model picker prompts."""
from __future__ import annotations

from typing import Any


def build_summary_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Format model metadata, probe history, and measured performance into a picker summary."""
    evidence = str(entry.get("assessment_evidence", ""))
    invalid_ids = {item.get("id") for item in entry.get("probe_history", []) if item.get("invalidated")}
    assessment = "" if any(f"probe:{probe_id}" in evidence for probe_id in invalid_ids) else str(entry.get("agent_assessment", ""))[:300]
    stats = entry.get("measured_stats", {})
    calls = int(stats.get("calls", 0) or 0)
    failures = int(stats.get("failures", 0) or 0)
    truncated = int(stats.get("truncated_calls", 0) or 0)
    network_errors = int(stats.get("network_errors", 0) or 0)
    total_latency = int(stats.get("latency_ms_total", 0) or 0)
    max_latency = stats.get("latency_ms_max")
    avg_latency_ms = round(total_latency / calls) if calls > 0 else "unknown"
    max_latency_ms = max_latency if max_latency is not None else "unknown"
    truncation_rate = f"{truncated / calls:.1%}" if calls > 0 else "unknown"

    probe_passes = int(stats.get("probe_passes", 0) or 0)
    probe_failures = int(stats.get("probe_failures", 0) or 0)
    probe_inconclusive = int(stats.get("probe_inconclusive", 0) or 0)

    research = entry.get("research", {}) if isinstance(entry.get("research"), dict) else {}
    research_status = research.get("status", "not_checked")
    latest_probe = next(
        (p for p in reversed(entry.get("probe_history", [])) if isinstance(p, dict) and not p.get("invalidated")),
        None,
    )
    probe_latency_ms = (
        latest_probe.get("latency_ms")
        if latest_probe and latest_probe.get("latency_ms") is not None
        else "unknown"
    )

    facts_summary = [
        {
            "field": str(f.get("field", "")),
            "value": str(f.get("value", "")),
            "origin": str(f.get("origin", "web")),
            "verified": bool(f.get("verified", f.get("origin") != "model_knowledge")),
        }
        for f in research.get("facts", [])
        if isinstance(f, dict) and f.get("field")
    ]
    facts_origin = {
        f["field"]: f.get("origin", "web")
        for f in research.get("facts", [])
        if isinstance(f, dict) and f.get("field")
    }
    total_params = research.get("total_params") or "unknown"
    active_params = research.get("active_params") or "unknown"
    context_window = research.get("context_window") or "unknown"
    pricing = research.get("pricing") or "unknown"
    speed = research.get("speed") or "unknown"
    strengths = research.get("strengths") or "unknown"

    return {
        "name": entry["name"],
        "role": entry.get("role", "helper"),
        "status": "untested" if entry.get("status") == "configured" else entry.get("status", "unknown"),
        "assessment": assessment,
        "calls": calls,
        "failures": failures,
        "network_errors": network_errors,
        "avg_latency_ms": avg_latency_ms,
        "probe_latency_ms": probe_latency_ms,
        "max_latency_ms": max_latency_ms,
        "truncation_rate": truncation_rate,
        "probes": {"passes": probe_passes, "failures": probe_failures, "inconclusive": probe_inconclusive},
        "research_status": research_status,
        "total_params": total_params,
        "active_params": active_params,
        "context_window": context_window,
        "pricing": pricing,
        "speed": speed,
        "strengths": strengths,
        "facts": facts_summary,
        "facts_origin": facts_origin,
    }


__all__ = [
    "build_summary_entry",
]
