"""Initialization and blank entry creation for the model registry."""
from __future__ import annotations

from typing import Any

from agent.llm.registry.constants import (
    LEGACY_PROBE_INVALIDATION_REASON,
    MAX_ASSESSMENT_CHARS,
    MAX_COUNTER,
    MAX_EVIDENCE_CHARS,
    MAX_NOTES_CHARS,
    PROBE_FORMAT_VERSION,
    RATING_CATEGORIES,
    RATING_VALUES,
    SCHEMA_VERSION,
)


def blank_model_entry(name: str, base_model: str) -> dict[str, Any]:
    """Return a blank template entry for a model."""
    return {
        "name": name,
        "role": "base" if name == base_model else "helper",
        "configured": True,
        "status": "configured",
        "status_message": "",
        "last_failure_at": None,
        "agent_assessment": "",
        "assessment_evidence": "",
        "ratings": None,
        "ratings_at": None,
        "measured_stats": {
            "calls": 0,
            "failures": 0,
            "truncated_calls": 0,
            "network_errors": 0,
            "latency_ms_total": 0,
            "latency_ms_min": None,
            "latency_ms_max": None,
            "consecutive_failures": 0,
            "probe_passes": 0,
            "probe_failures": 0,
            "probe_inconclusive": 0,
        },
        "notes": "",
        "probe_history": [],
        "research": {
            "status": "not_checked",
            "status_message": "",
            "source_url": None,
            "urls_tried": [],
            "last_checked": None,
            "last_verified": None,
            "facts": [],
            "total_params": None,
            "active_params": None,
            "context_window": None,
            "pricing": None,
            "speed": None,
            "strengths": None,
        },
    }


def initialize_registry_data(
    prior: dict[str, Any],
    base_model: str,
    names: list[str],
) -> dict[str, Any]:
    """Merge prior registry data with current configured models."""
    old_probe_format = int(prior.get("probe_format_version", 1) or 1)
    existing = {
        entry.get("name"): entry
        for entry in prior.get("models", [])
        if isinstance(entry, dict) and isinstance(entry.get("name"), str)
    }
    entries: list[dict[str, Any]] = []
    for name in names:
        entry = blank_model_entry(name, base_model)
        old = existing.pop(name, None)
        if old is not None:
            for field, limit in (
                ("agent_assessment", MAX_ASSESSMENT_CHARS),
                ("assessment_evidence", MAX_EVIDENCE_CHARS),
                ("notes", MAX_NOTES_CHARS),
            ):
                entry[field] = str(old.get(field, ""))[:limit]
            prior_ratings = old.get("ratings")
            if (
                isinstance(prior_ratings, dict)
                and set(prior_ratings) == set(RATING_CATEGORIES)
                and all(value in RATING_VALUES for value in prior_ratings.values())
            ):
                entry["ratings"] = prior_ratings
                entry["ratings_at"] = old.get("ratings_at")
            if old.get("status") in {"configured", "reachable", "last_call_failed", "not_found"}:
                entry["status"] = old["status"]
            if old.get("status") == "disabled":
                entry["status"] = "disabled"
            entry["status_message"] = str(old.get("status_message", ""))[:300]
            entry["last_failure_at"] = old.get("last_failure_at")
            if isinstance(old.get("probe_history"), list):
                entry["probe_history"] = [
                    {
                        "id": str(item.get("id", ""))[:32],
                        "session_id": str(item.get("session_id", ""))[:80],
                        "at": float(item.get("at", 0) or 0),
                        "status": str(item.get("status", ""))[:20],
                        "latency_ms": int(item["latency_ms"]) if item.get("latency_ms") is not None else None,
                        "format_version": int(item.get("format_version", old_probe_format) or old_probe_format),
                        "invalidated": old_probe_format < PROBE_FORMAT_VERSION or bool(item.get("invalidated", False)),
                        "invalidation_reason": (
                            LEGACY_PROBE_INVALIDATION_REASON
                            if old_probe_format < PROBE_FORMAT_VERSION
                            else str(item.get("invalidation_reason", ""))[:300]
                        ),
                    }
                    for item in old["probe_history"][-32:]
                    if isinstance(item, dict)
                ]
            invalidated_ids = {item["id"] for item in entry["probe_history"] if item["invalidated"]}
            if any(f"probe:{probe_id}" in entry["assessment_evidence"] for probe_id in invalidated_ids):
                entry["agent_assessment"] = ""
                entry["assessment_evidence"] = ""
                entry["ratings"] = None
                entry["ratings_at"] = None
            if isinstance(old.get("research"), dict):
                research = old["research"]
                facts_raw = [
                    {
                        "field": str(item.get("field", ""))[:80],
                        "value": str(item.get("value", ""))[:500],
                        "excerpt": str(item.get("excerpt", ""))[:500],
                        "source_url": str(item.get("source_url", ""))[:500] if item.get("source_url") else None,
                        "origin": str(item.get("origin", "web"))[:20],
                        "verified": bool(item.get("verified", item.get("origin") != "model_knowledge")),
                        "last_verified": str(item.get("last_verified", ""))[:80] if item.get("last_verified") else None,
                    }
                    for item in research.get("facts", [])[:16]
                    if isinstance(item, dict) and item.get("field") != "model_name_mentioned"
                ]
                old_status = str(research.get("status", "not_checked"))[:40]
                if old_status == "verified_mention":
                    status = "facts_found" if facts_raw else "fetched_no_model_fact"
                else:
                    status = old_status
                urls_tried = research.get("urls_tried")
                if not isinstance(urls_tried, list):
                    urls_tried = [research["source_url"]] if research.get("source_url") else []

                entry["research"] = {
                    "status": status,
                    "status_message": str(research.get("status_message", ""))[:300],
                    "source_url": str(research["source_url"])[:500] if research.get("source_url") else None,
                    "urls_tried": [str(u)[:500] for u in urls_tried][:10],
                    "last_checked": str(research["last_checked"])[:80] if research.get("last_checked") else None,
                    "last_verified": str(research["last_verified"])[:80] if research.get("last_verified") else None,
                    "facts": facts_raw,
                    "total_params": str(research.get("total_params", ""))[:40] if research.get("total_params") else None,
                    "active_params": str(research.get("active_params", ""))[:40] if research.get("active_params") else None,
                    "context_window": str(research.get("context_window", ""))[:40] if research.get("context_window") else None,
                    "pricing": str(research.get("pricing", ""))[:80] if research.get("pricing") else None,
                    "speed": str(research.get("speed", ""))[:40] if research.get("speed") else None,
                    "strengths": str(research.get("strengths", ""))[:120] if research.get("strengths") else None,
                }
            stats = old.get("measured_stats", {})
            if isinstance(stats, dict):
                for field in (
                    "calls",
                    "failures",
                    "truncated_calls",
                    "network_errors",
                    "latency_ms_total",
                    "consecutive_failures",
                    "probe_passes",
                    "probe_failures",
                    "probe_inconclusive",
                ):
                    entry["measured_stats"][field] = min(
                        MAX_COUNTER, max(0, int(stats.get(field, 0) or 0))
                    )
                if "consecutive_failures" not in stats and entry["status"] == "last_call_failed":
                    entry["measured_stats"]["consecutive_failures"] = 1
                for field in ("latency_ms_min", "latency_ms_max"):
                    value = stats.get(field)
                    entry["measured_stats"][field] = (
                        min(MAX_COUNTER, max(0, int(value))) if value is not None else None
                    )
        entries.append(entry)
    for old_name, old_entry in existing.items():
        # Preserve renamed or discontinued model history without attaching to new entries
        preserved = dict(old_entry)
        preserved["configured"] = False
        preserved["status"] = "unconfigured"
        preserved["status_message"] = (
            f"Model '{old_name}' is no longer configured in the registry; historical assessment and probes belong to this discontinued name."
        )
        entries.append(preserved)
    return {
        "schema_version": SCHEMA_VERSION,
        "probe_format_version": PROBE_FORMAT_VERSION,
        "base_model": base_model,
        "models": entries,
    }
