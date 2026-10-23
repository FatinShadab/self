"""Model research evidence and fact persistence in registry."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def record_facts_entry(
    entry: dict[str, Any],
    facts: list[dict[str, Any]] | dict[str, Any],
    origin: str,
    redactor: Any,
    blank_research: dict[str, Any],
) -> tuple[list[dict[str, Any]], int]:
    """Store agent-supplied facts into model research dictionary."""
    facts_list: list[dict[str, Any]] = []
    if isinstance(facts, dict):
        for k, v in facts.items():
            if v is not None:
                facts_list.append({
                    "field": str(k),
                    "value": str(v),
                    "excerpt": f"agent model knowledge: {k}={v}",
                })
    elif isinstance(facts, list):
        for item in facts:
            if isinstance(item, dict) and item.get("field") and item.get("value") is not None:
                facts_list.append({
                    "field": str(item["field"]),
                    "value": str(item["value"]),
                    "excerpt": str(item.get("excerpt", f"agent model knowledge: {item['field']}={item['value']}")),
                })
    else:
        raise ValueError("Facts must be a list of objects or a key-value dictionary")

    is_model_knowledge = origin == "model_knowledge"
    verified = not is_model_knowledge
    research = entry.setdefault("research", dict(blank_research))
    existing_facts = list(research.get("facts", []))
    for f in facts_list:
        fld = f["field"][:80]
        val = redactor.text(str(f["value"]))[:500]
        exc = redactor.text(str(f["excerpt"]))[:500]
        fact_obj = {
            "field": fld,
            "value": val,
            "excerpt": exc,
            "source_url": None,
            "origin": origin,
            "verified": verified,
            "last_verified": None,
        }
        idx = next(
            (
                i
                for i, ef in enumerate(existing_facts)
                if ef.get("field") == fld and ef.get("origin") == origin
            ),
            None,
        )
        if idx is not None:
            existing_facts[idx] = fact_obj
        else:
            existing_facts.append(fact_obj)

        if fld in {"total_params", "active_params", "context_window", "pricing", "speed", "strengths"}:
            if not research.get(fld):
                research[fld] = (
                    val[:40]
                    if fld in {"total_params", "active_params", "context_window", "speed"}
                    else val[:120]
                )

    research["facts"] = existing_facts[:16]
    return research["facts"], len(facts_list)


def record_research_entry(
    entry: dict[str, Any],
    status: str,
    source_url: str | None,
    facts: list[dict[str, Any]],
    status_message: str,
    urls_tried: list[str] | None,
    total_params: str | None,
    active_params: str | None,
    context_window: str | None,
    pricing: str | None,
    speed: str | None,
    strengths: str | None,
    redactor: Any,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    """Store official research evidence for a configured model."""
    checked = datetime.now(timezone.utc).isoformat()
    safe_facts = []
    for fact in facts[:16]:
        origin = str(fact.get("origin", "web"))[:20]
        is_model_knowledge = origin == "model_knowledge"
        verified = bool(fact.get("verified", not is_model_knowledge))
        safe_facts.append({
            "field": str(fact["field"])[:80],
            "value": redactor.text(str(fact["value"]))[:500],
            "excerpt": redactor.text(str(fact.get("excerpt", "")))[:500],
            "source_url": fact.get("source_url") or (None if is_model_knowledge else source_url),
            "origin": origin,
            "verified": verified,
            "last_verified": checked if verified else None,
        })
    tried = [str(u)[:500] for u in urls_tried][:10] if urls_tried else ([source_url] if source_url else [])
    entry["research"] = {
        "status": status,
        "status_message": str(status_message)[:300],
        "source_url": source_url,
        "urls_tried": tried,
        "last_checked": checked,
        "last_verified": checked if any(f["verified"] for f in safe_facts) else None,
        "facts": safe_facts,
        "total_params": str(total_params)[:40] if total_params else None,
        "active_params": str(active_params)[:40] if active_params else None,
        "context_window": str(context_window)[:40] if context_window else None,
        "pricing": str(pricing)[:80] if pricing else None,
        "speed": str(speed)[:40] if speed else None,
        "strengths": str(strengths)[:120] if strengths else None,
    }
    return entry["research"], safe_facts, tried
