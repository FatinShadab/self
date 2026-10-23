"""Evidence-backed traits, session reflections, and record compaction."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from agent.identity.store.constants import now
from agent.identity.store.schema import safe_text


def identity_has_trait(traits: list[dict[str, Any]], trait: str) -> bool:
    """Check if trait already exists in traits list (case-insensitive)."""
    return any(str(item.get("trait", "")).casefold() == trait.casefold() for item in traits)


def add_trait_to_identity(
    identity: dict[str, Any],
    log_change_fn: Callable[[str, str, str], None],
    redactor: Any,
    trait: str,
    evidence: str,
    session_id: str,
) -> bool:
    """Record an evidence-backed identity trait."""
    trait_text = safe_text(trait, redactor, 160)
    evidence_text = safe_text(evidence, redactor, 1_000)
    traits = list(identity.get("traits", []))
    if not trait_text or not evidence_text or identity_has_trait(traits, trait_text):
        return False
    traits.append({"trait": trait_text, "evidence": evidence_text, "added": safe_text(session_id, redactor, 160)})
    identity["traits"] = traits[-32:]
    log_change_fn(
        f"Added trait: {trait_text}.",
        f"Observed evidence: {evidence_text}",
        session_id,
    )
    return True


def reflect_on_session(
    workspace: Path,
    identity: dict[str, Any],
    reflections_path: Path,
    add_trait_fn: Callable[[str, str, str], bool],
    append_jsonl_fn: Callable[[Path, dict[str, Any]], None],
    log_change_fn: Callable[[str, str, str], None],
    compact_fn: Callable[[str], bool],
    redactor: Any,
    session_id: str,
    started_at: str,
    summary: str = "",
) -> list[str]:
    """Record evidence-only answers to the session reflection questions."""
    calls: list[str] = []
    successful: set[str] = set()
    try:
        actions_file = workspace / "logs" / "actions.jsonl"
        for line in actions_file.read_text(encoding="utf-8", errors="replace").splitlines()[-2_000:]:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            if str(event.get("timestamp", "")) < started_at:
                continue
            if event.get("event") == "tool_call":
                calls.append(str(event.get("tool", "unknown")))
            elif event.get("event") == "tool_result" and event.get("ok"):
                successful.add(str(event.get("tool", "unknown")))
    except OSError:
        pass

    call_summary = ", ".join(calls[:12]) or "no recorded tool call"
    added: list[str] = []
    if "update_environment_map" in successful and add_trait_fn(
        "evidence-oriented",
        f"Session {session_id}: successfully recorded an observed fact with update_environment_map.",
        session_id,
    ):
        added.append("evidence-oriented")
    if "create_tool" in successful and add_trait_fn(
        "tool-building",
        f"Session {session_id}: successfully created and registered a tested tool.",
        session_id,
    ):
        added.append("tool-building")

    record = {
        "timestamp": now(),
        "session_id": session_id,
        "questions": {
            "What did I choose to do when I had freedom?": f"The observable session actions were: {call_summary}.",
            "What did I find interesting?": "No interest claim was inferred beyond the selected work; future evidence may clarify recurring choices.",
            "How did I handle failure?": "See the action log and session handoff for failures; no trait is inferred from an isolated failure.",
            "What would I do differently?": "Keep verified observations and pending questions explicit in the next plan.",
        },
        "traits_added": added,
        "session_summary": safe_text(summary, redactor, 1_500),
    }
    append_jsonl_fn(reflections_path, record)
    log_change_fn(
        "Recorded an evidence-only session reflection" + (f" and added: {', '.join(added)}." if added else "."),
        "The reflection is based on logged actions; no unsupported personality claim was added.",
        session_id,
    )
    compact_fn(session_id)
    return added


def compact_identity_record(
    identity_path: Path,
    load_fn: Callable[[], dict[str, Any]],
    atomic_json_fn: Callable[[Path, dict[str, Any]], None],
    log_change_fn: Callable[[str, str, str], None],
    max_bytes: int,
    session_id: str = "",
) -> bool:
    """Only compact a genuinely oversize identity, logging any removal visibly."""
    if not identity_path.exists() or identity_path.stat().st_size <= max_bytes:
        return False
    identity = load_fn()
    original_traits, original_values = len(identity["traits"]), len(identity["values"])
    identity["traits"] = identity["traits"][-12:]
    identity["values"] = identity["values"][-12:]
    identity["interests"] = identity["interests"][-12:]
    identity["open_questions_about_self"] = identity["open_questions_about_self"][-12:]
    atomic_json_fn(identity_path, identity)
    log_change_fn(
        "Compacted an oversized identity record.",
        f"Kept the newest evidence-backed entries to stay below the {max_bytes}-byte cap "
        f"(traits {original_traits}->{len(identity['traits'])}; values {original_values}->{len(identity['values'])}).",
        session_id,
    )
    return True
