"""Human input handling, name extraction, conversation context, and model snapshots."""
from __future__ import annotations

import json
import re
import time
from collections import deque
from pathlib import Path
from typing import Any

from agent.session.handoff_builder import _read_json
from agent.session.plan_recovery import visible_plan_items


def human_name_candidate(text: str) -> str | None:
    """Extract a candidate person name from conversational text, or return None."""
    clean = " ".join(text.strip().split())
    if not clean or clean.startswith("/"):
        return None
    lower = clean.lower()
    for prefix in ("my name is ", "i am ", "i'm "):
        if lower.startswith(prefix):
            clean = clean[len(prefix):].strip(" .,!?:;")
            break
    if not clean or len(clean) > 80 or len(clean.split()) > 3:
        return None
    if lower in {"hi", "hello", "help", "yes", "no", "are you there", "what", "thanks", "thank you"}:
        return None
    if not re.fullmatch(r"[A-Za-z][A-Za-z .'-]*", clean):
        return None
    return clean


def handle_receive_human_input(
    coordinator: Any,
    text: str,
    kind: str = "goal",
) -> None:
    """Queue human input for the next safe agent turn and update name state."""
    coordinator.inbox.add(text, kind=kind)
    coordinator.status.last_human_input = time.monotonic()
    if coordinator.identity.awaiting_name():
        coordinator.identity.record_human_answer(text, coordinator.status.session_id)
    if not coordinator.identity.human_name():
        candidate = human_name_candidate(text)
        if candidate:
            try:
                saved = coordinator.identity.set_human_name(candidate, coordinator.status.session_id)
                coordinator.logger.narrate(f"Thank you, {saved}. I saved your name and will use it in future conversations.")
            except ValueError:
                pass
    coordinator.logger.narrate(f"Human: {text}")


def format_recent_decisions(plan_store: Any) -> str:
    """Return formatted markdown of recent human input decisions."""
    plan_store.load()
    decisions = plan_store.human_input_decisions[-10:]
    if not decisions:
        return "No human input decisions recorded yet."
    lines = ["Recent human input decisions:"]
    for d in decisions:
        dec = d.get("decision", "unknown")
        inp = d.get("input", "")
        reason = d.get("reason", "")
        cycle = d.get("cycle", 0)
        p = d.get("priority")
        p_str = f" [priority {p}]" if p is not None else ""
        lines.append(f"- [{dec}]{p_str} '{inp}' (cycle {cycle}): {reason}")
    return "\n".join(lines)


def build_conversation_context(
    identity: Any,
    handoff: dict[str, Any],
    plan_store: Any,
    plan: list[dict[str, Any]],
    activity: deque[str] | list[str],
    cycle_summaries: deque[str] | list[str],
    *,
    status_summary: str = "",
    requests_summary: str = "",
) -> str:
    """Build a bounded read-only snapshot for independent conversation and reflection threads."""
    identity_ctx = identity.prompt_context()
    handoff_str = json.dumps(handoff, ensure_ascii=False)[:6_000]
    plan_store.load()
    active_plan = plan_store.top_items(limit=5)
    plan_str = json.dumps(
        active_plan if active_plan else visible_plan_items(plan)[:5],
        ensure_ascii=False,
    )[:4_000]
    decisions = plan_store.human_input_decisions[-5:]
    decisions_summary = json.dumps(decisions, ensure_ascii=False)[:2_000] if decisions else "No decisions recorded yet."
    activity_str = "\n".join(list(activity)[-40:])[:6_000]
    summaries_str = "\n\n".join(list(cycle_summaries)[-6:])[:8_000]
    parts = [identity_ctx]
    if status_summary:
        parts.append(f"Current loop status:\n{status_summary}")
    if requests_summary and requests_summary != "No pending human requests.":
        parts.append(f"Pending requests / reports:\n{requests_summary}")
    parts.extend([
        f"Current handoff:\n{handoff_str}",
        f"Active plan items:\n{plan_str}",
        f"Recent human input decisions:\n{decisions_summary}",
        f"Recent cycle summaries:\n{summaries_str}",
        f"Recent activity:\n{activity_str}",
    ])
    return "\n\n".join(parts)


def build_models_snapshot(
    llm: Any,
    workspace: Path,
    logger: Any,
) -> dict[str, Any]:
    """Return model registry data and recent model selection decisions."""
    registry = getattr(llm, "model_registry", None)
    if registry is not None:
        models = registry.list_models()
    else:
        models = _read_json(workspace / "state" / "models.json")
    decisions_path = workspace / "state" / "model_decisions.jsonl"
    recent: deque[dict[str, Any]] = deque(maxlen=10)
    try:
        with decisions_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    value = json.loads(line)
                    if isinstance(value, dict) and (
                        value.get("source") == "agent_tool"
                        or str(value.get("source", "")).startswith("checkpoint:")
                    ):
                        recent.append(value)
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return logger.redactor.value({"registry": models, "last_ten_decisions": list(recent)})


__all__ = [
    "human_name_candidate",
    "handle_receive_human_input",
    "format_recent_decisions",
    "build_conversation_context",
    "build_models_snapshot",
]
