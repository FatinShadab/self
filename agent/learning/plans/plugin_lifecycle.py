"""Goal suspension and resumption linked to plugin activation lifecycles."""
from __future__ import annotations

from typing import Any

from agent.learning.plan_statuses import COMPLETED_PLAN_STATUSES, SUSPENDED_PLAN_STATUS_PREFIX

SUSPENDED_PLUGIN_STATUS = "suspended: plugin disabled"


def suspend_plugin_goals(
    items: list[dict[str, Any]],
    plugin_name: str,
    cycle: int = 0,
) -> tuple[list[str], str]:
    """Suspend all active goals associated with a disabled plugin.

    Suspended goals get status 'suspended: plugin disabled' and are kept, never deleted.
    """
    suspended_ids: list[str] = []
    for item in items:
        status = str(item.get("status", "todo")).strip().lower()
        p = item.get("plugin", "core")
        src = str(item.get("source", ""))
        is_match = (p == plugin_name) or src == f"plugin:{plugin_name}"
        if is_match and status not in COMPLETED_PLAN_STATUSES and not status.startswith(SUSPENDED_PLAN_STATUS_PREFIX):
            item["_prev_status"] = item.get("status", "todo")
            item["status"] = SUSPENDED_PLUGIN_STATUS
            if cycle:
                item["updated_cycle"] = cycle
            suspended_ids.append(str(item.get("id")))

    diff = (
        f"Suspended goals for disabled plugin '{plugin_name}': {', '.join(suspended_ids)}"
        if suspended_ids
        else ""
    )
    return suspended_ids, diff


def resume_plugin_goals(
    items: list[dict[str, Any]],
    plugin_name: str,
    cycle: int = 0,
) -> tuple[list[str], str]:
    """Resume suspended goals when a plugin is re-enabled successfully.

    Suspended goals return with a note 're-verify: plugin was disabled'.
    """
    resumed_ids: list[str] = []
    for item in items:
        status = str(item.get("status", "")).strip().lower()
        p = item.get("plugin", "core")
        src = str(item.get("source", ""))
        is_match = (p == plugin_name) or src == f"plugin:{plugin_name}"
        if is_match and status.startswith(SUSPENDED_PLAN_STATUS_PREFIX):
            prev = item.pop("_prev_status", "todo")
            item["status"] = prev if prev not in COMPLETED_PLAN_STATUSES else "todo"
            item["note"] = "re-verify: plugin was disabled"
            why = str(item.get("why", "")).strip()
            if "re-verify: plugin was disabled" not in why:
                item["why"] = f"{why} (re-verify: plugin was disabled)".strip()
            if cycle:
                item["updated_cycle"] = cycle
            resumed_ids.append(str(item.get("id")))

    diff = (
        f"Resumed goals for re-enabled plugin '{plugin_name}': {', '.join(resumed_ids)}"
        if resumed_ids
        else ""
    )
    return resumed_ids, diff
