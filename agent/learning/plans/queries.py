"""Plan queries, retrieval text derivation, and prompt formatting."""
from __future__ import annotations

from typing import Any

from agent.learning.plan_statuses import COMPLETED_PLAN_STATUSES, SUSPENDED_PLAN_STATUS_PREFIX


def filter_top_items(
    items: list[dict[str, Any]],
    limit: int = 3,
    active_plugins: Any = None,
) -> list[dict[str, Any]]:
    """Return active plan items sorted by priority and position."""
    active = []
    for item in items:
        status = str(item.get("status", "todo")).strip().lower()
        if status in COMPLETED_PLAN_STATUSES or status.startswith(SUSPENDED_PLAN_STATUS_PREFIX):
            continue
        plugin = item.get("plugin", "core")
        if active_plugins is not None and plugin != "core" and plugin not in active_plugins:
            continue
        active.append(item)
    return sorted(active, key=lambda it: int(it.get("priority", 2)))[:limit]


def build_retrieval_query(top_items: list[dict[str, Any]]) -> str:
    """Build retrieval query string from top active plan items."""
    if not top_items:
        return "Explore container environment and record discoveries."
    parts: list[str] = []
    for it in top_items:
        goal = str(it.get("goal") or it.get("step", "")).strip()
        next_steps = str(it.get("next_steps", "")).strip()
        parts.append(f"{goal} {next_steps}".strip())
    return "\n".join(parts)


def format_prompt_summary(
    active: list[dict[str, Any]],
    archived: list[dict[str, Any]],
    human_input_decisions: list[dict[str, Any]],
) -> str:
    """Format active plan items, archived goals, and human decisions for cycle prompts."""
    lines: list[str] = []
    if not active:
        lines.append("No active plan goals. Use update_plan to add a new exploration or self-improvement goal.")
    else:
        for idx, item in enumerate(active, 1):
            goal = str(item.get("goal") or item.get("step", "")).strip()
            status = str(item.get("status", "todo")).strip()
            priority = item.get("priority", 2)
            item_id = item.get("id", f"goal-{idx}")
            source = str(item.get("source", "agent"))
            next_steps = str(item.get("next_steps", "")).strip()
            evidence = str(item.get("evidence", "")).strip()
            entry = f"{idx}. [{item_id}] (priority={priority}, status={status}, source={source}) {goal}"
            if next_steps:
                entry += f"\n   Next step: {next_steps}"
            if evidence:
                entry += f"\n   Evidence: {evidence}"
            lines.append(entry)

    if archived:
        lines.append("\nRecently archived goals:")
        for arc in archived:
            outcome = arc.get("outcome", "done")
            goal = arc.get("goal", "")
            cycle_num = arc.get("cycle", 1)
            lines.append(f"- [{outcome}] (cycle {cycle_num}) {goal}")

    if human_input_decisions:
        lines.append("\nRecent human input decisions:")
        for dec in human_input_decisions[-4:]:
            lines.append(f"- [{dec.get('decision')}] \"{dec.get('input', '')[:80]}\": {dec.get('reason', '')[:120]}")

    return "\n".join(lines)
