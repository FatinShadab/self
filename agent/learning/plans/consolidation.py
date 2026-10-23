"""Plan size capping by consolidation without loss of active goals."""
from __future__ import annotations

from typing import Any

from agent.learning.plan_statuses import COMPLETED_PLAN_STATUSES, SUSPENDED_PLAN_STATUS_PREFIX


def consolidate_plan_items(plan: list[dict[str, Any]], max_items: int = 8) -> list[dict[str, Any]]:
    """Cap plan size by consolidating older or lower-priority items rather than truncating.

    Suspended goals are exempt from consolidation over max_items.
    """
    suspended: list[dict[str, Any]] = []
    non_suspended: list[dict[str, Any]] = []
    for item in plan:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status", "")).strip().lower()
        if status.startswith(SUSPENDED_PLAN_STATUS_PREFIX):
            suspended.append(item)
        else:
            non_suspended.append(item)

    if len(non_suspended) <= max_items:
        active: list[dict[str, Any]] = []
        completed: list[dict[str, Any]] = []
        for item in non_suspended:
            status = str(item.get("status", "todo")).strip().lower()
            if status in COMPLETED_PLAN_STATUSES:
                completed.append(item)
            else:
                active.append(item)

        if len(active) <= max_items:
            if completed:
                consolidated_goal = "Completed milestones: " + "; ".join(
                    str(item.get("goal") or item.get("step", "")).strip() for item in completed
                )
                consolidated_item = {
                    "id": "milestones-consolidated",
                    "goal": consolidated_goal[:500],
                    "step": consolidated_goal[:500],
                    "status": "done",
                    "priority": 3,
                    "why": "Consolidated completed milestones for plan hygiene",
                    "evidence": f"Consolidated from {len(completed)} completed goals",
                    "next_steps": "Milestones achieved.",
                    "created_cycle": 1,
                    "updated_cycle": 1,
                    "plugin": "core",
                    "body": "container",
                }
                return active + [consolidated_item] + suspended
            return active + suspended

    active_items = [
        it for it in non_suspended
        if str(it.get("status", "todo")).strip().lower() not in COMPLETED_PLAN_STATUSES
    ]
    keep_count = max_items - 1
    preserved = active_items[:keep_count]
    consolidated_active = active_items[keep_count:]

    combined_goals = "; ".join(
        str(item.get("goal") or item.get("step", "")).strip() for item in consolidated_active
    )
    combined_steps = "; ".join(
        str(item.get("next_steps", "")).strip() for item in consolidated_active if item.get("next_steps")
    )
    consolidated_item = {
        "id": "active-consolidated",
        "goal": f"Consolidated secondary objectives: {combined_goals}"[:500],
        "step": f"Consolidated secondary objectives: {combined_goals}"[:500],
        "status": "todo",
        "priority": 3,
        "why": "Consolidated secondary goals to preserve plan bounds without truncation",
        "evidence": f"Consolidated from {len(consolidated_active)} active goals",
        "next_steps": combined_steps[:500] or "Address consolidated objectives after primary goals.",
        "created_cycle": active_items[0].get("created_cycle", 1) if active_items else 1,
        "updated_cycle": active_items[0].get("updated_cycle", 1) if active_items else 1,
        "plugin": "core",
        "body": "container",
    }

    return preserved + [consolidated_item] + suspended
