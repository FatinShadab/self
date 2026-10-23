"""Plan hygiene maintenance (archive purge, stale marking, size capping)."""
from __future__ import annotations

from typing import Any

from agent.learning.plan_statuses import COMPLETED_PLAN_STATUSES, SUSPENDED_PLAN_STATUS_PREFIX
from agent.learning.plans.consolidation import consolidate_plan_items
from agent.learning.plans.persistence import now_utc


def apply_plan_hygiene(
    items: list[dict[str, Any]],
    max_items: int,
    cycle: int,
    max_stale_cycles: int = 5,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], bool]:
    """Execute plan hygiene rules and return updated items, purged records, actions, and changed flag."""
    actions: list[str] = []
    changed = False

    # 1. Purge completed and dropped goals to plan_archive.jsonl
    purged_records: list[dict[str, Any]] = []
    retained_items: list[dict[str, Any]] = []
    for item in items:
        status = str(item.get("status", "todo")).strip().lower()
        if status.startswith(SUSPENDED_PLAN_STATUS_PREFIX):
            retained_items.append(item)
            continue
        if status in COMPLETED_PLAN_STATUSES:
            purged_records.append({
                "goal": str(item.get("goal") or item.get("step", "")).strip(),
                "outcome": status,
                "reason": str(item.get("why") or item.get("reason") or "Completed or dropped during exploration").strip(),
                "evidence": str(item.get("evidence", "")).strip(),
                "cycle": cycle,
                "timestamp": now_utc(),
                "plugin": item.get("plugin", "core"),
                "body": item.get("body", "container"),
            })
        else:
            retained_items.append(item)

    if purged_records:
        items = retained_items
        actions.append(f"Archived and purged {len(purged_records)} completed/dropped goal(s) to plan_archive.jsonl")
        changed = True

    # 2. Mark stale items (suspended goals are exempt from stale-item pruning)
    for item in items:
        status = str(item.get("status", "todo")).strip().lower()
        if status.startswith(SUSPENDED_PLAN_STATUS_PREFIX):
            continue
        if status in COMPLETED_PLAN_STATUSES:
            continue
        updated = int(item.get("updated_cycle") or item.get("created_cycle") or 1)
        if cycle - updated >= max_stale_cycles:
            if status != "stale":
                item["status"] = "stale"
                item["updated_cycle"] = cycle
                actions.append(f"Marked stale {item.get('id')}: '{item.get('goal', '')}' (no progress for {cycle - updated} cycles)")
                changed = True

    # 3. Consolidation over max_items (suspended goals are exempt)
    non_suspended_count = sum(
        1 for it in items
        if not str(it.get("status", "")).strip().lower().startswith(SUSPENDED_PLAN_STATUS_PREFIX)
    )
    if non_suspended_count > max_items or len(items) > max_items:
        items = consolidate_plan_items(items, max_items=max_items)
        actions.append("Consolidated excess plan items to maintain size bound")
        changed = True

    return items, purged_records, actions, changed
