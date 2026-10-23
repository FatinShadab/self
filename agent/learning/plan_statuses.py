"""Plan item status constants and visibility filters.

Preserves distinct filtering behavior between execution planning (which filters
out suspended plugin goals) and UI/session views (which retain suspended goals).
"""
from __future__ import annotations

from typing import Any

COMPLETED_PLAN_STATUSES = frozenset({
    "done", "complete", "completed", "achieved", "finished", "closed",
    "cancelled", "canceled", "dropped",
})

ACTIVE_PLAN_STATUSES = frozenset({
    "todo", "in_progress", "in-progress", "working", "next", "blocked", "stale",
})

SUSPENDED_PLAN_STATUS_PREFIX = "suspended"
SUSPENDED_PLUGIN_STATUS = "suspended:plugin_disabled"


def visible_plan_items(plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return active plan items for execution and learning (excluding completed and suspended)."""
    return [
        item for item in plan
        if isinstance(item, dict)
        and str(item.get("status", "todo")).strip().lower() not in COMPLETED_PLAN_STATUSES
        and not str(item.get("status", "")).strip().lower().startswith(SUSPENDED_PLAN_STATUS_PREFIX)
    ]


def visible_plan_items_incl_suspended(plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return active plan items including suspended plugin goals (for UI and session display)."""
    return [
        item for item in plan
        if isinstance(item, dict)
        and str(item.get("status", "todo")).strip().lower() not in COMPLETED_PLAN_STATUSES
    ]
