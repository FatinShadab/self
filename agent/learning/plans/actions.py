"""Plan mutation actions (add, edit, drop, mark_done, reorder, review)."""
from __future__ import annotations

from typing import Any

from agent.learning.plan_statuses import ACTIVE_PLAN_STATUSES, SUSPENDED_PLAN_STATUS_PREFIX
from agent.learning.plans.persistence import now_utc


def find_plan_item(
    items: list[dict[str, Any]],
    target: Any,
) -> tuple[int, dict[str, Any]] | tuple[None, None]:
    """Find a plan item by exact ID, 1-based index, or goal substring."""
    if target is None:
        return None, None
    target_str = str(target).strip()
    for idx, item in enumerate(items):
        if str(item.get("id", "")).strip() == target_str:
            return idx, item
    if target_str.isdigit():
        idx = int(target_str) - 1
        if 0 <= idx < len(items):
            return idx, items[idx]
    target_lower = target_str.lower()
    for idx, item in enumerate(items):
        goal = str(item.get("goal", "")).lower()
        if target_lower in goal or goal in target_lower:
            return idx, item
    return None, None


def apply_add_action(
    items: list[dict[str, Any]],
    next_id: int,
    goal: str,
    reason: str,
    evidence: str,
    next_steps: str,
    priority: int,
    status: str,
    cycle: int,
    extra: dict[str, Any],
) -> tuple[bool, str, str, int, dict[str, Any] | None]:
    """Add a new plan item to items list."""
    goal_text = str(goal or extra.get("step", "")).strip()
    if not goal_text:
        return False, "Goal text is required for action 'add'.", "", next_id, None
    new_id = f"goal-{next_id}"
    next_id += 1
    src_str = str(extra.get("source", "agent"))
    p_tag = str(extra.get("plugin") or "").strip()
    if not p_tag:
        if src_str.startswith("plugin:"):
            p_tag = src_str.split(":", 1)[1]
        else:
            p_tag = "core"
    b_tag = str(extra.get("body") or "container").strip() or "container"
    item = {
        "id": new_id,
        "goal": goal_text,
        "step": goal_text,
        "status": status if (status in ACTIVE_PLAN_STATUSES or status.startswith(SUSPENDED_PLAN_STATUS_PREFIX)) else "todo",
        "priority": int(priority) if isinstance(priority, (int, float)) else 2,
        "source": src_str,
        "why": extra.get("why") or reason,
        "evidence": evidence,
        "next_steps": next_steps.strip() or f"Execute investigation for {goal_text}",
        "created_cycle": cycle or 1,
        "updated_cycle": cycle or 1,
        "plugin": p_tag,
        "body": b_tag,
    }
    if item["priority"] == 1:
        items.insert(0, item)
    else:
        items.append(item)
    diff = f"Added {new_id}: '{goal_text}' (priority={item['priority']}, status={item['status']}, source={item['source']}, plugin={item['plugin']})"
    return True, diff, evidence, next_id, item


def apply_edit_action(
    items: list[dict[str, Any]],
    target_key: Any,
    goal: str,
    status: str,
    next_steps: str,
    evidence: str,
    priority: int,
    cycle: int,
    extra: dict[str, Any],
) -> tuple[bool, str, str]:
    """Edit fields on an existing plan item."""
    idx, item = find_plan_item(items, target_key)
    if item is None:
        return False, f"Target item '{target_key}' not found.", ""
    changes: list[str] = []
    if goal and str(goal).strip():
        item["goal"] = str(goal).strip()
        item["step"] = str(goal).strip()
        changes.append(f"goal='{item['goal']}'")
    if status and str(status).strip():
        item["status"] = str(status).strip()
        changes.append(f"status='{item['status']}'")
    if next_steps and str(next_steps).strip():
        item["next_steps"] = str(next_steps).strip()
        changes.append(f"next_steps='{item['next_steps']}'")
    if evidence:
        item["evidence"] = evidence
        changes.append(f"evidence='{item['evidence']}'")
    if "priority" in extra or priority != 2:
        item["priority"] = int(priority)
        changes.append(f"priority={item['priority']}")
    if "plugin" in extra:
        item["plugin"] = str(extra["plugin"])
        changes.append(f"plugin='{item['plugin']}'")
    if "body" in extra:
        item["body"] = str(extra["body"])
        changes.append(f"body='{item['body']}'")
    item["updated_cycle"] = cycle or item.get("updated_cycle", 1)
    diff = f"Edited {item.get('id', idx)}: {', '.join(changes) or 'updated details'}"
    return True, diff, evidence


def apply_drop_action(
    items: list[dict[str, Any]],
    target_key: Any,
    evidence: str,
    cycle: int,
) -> tuple[bool, str]:
    """Mark an existing plan item as dropped."""
    idx, item = find_plan_item(items, target_key)
    if item is None:
        return False, f"Target item '{target_key}' not found."
    item["status"] = "dropped"
    item["updated_cycle"] = cycle or item.get("updated_cycle", 1)
    item["evidence"] = evidence
    diff = f"Dropped {item.get('id', idx)}: '{item.get('goal', '')}'"
    return True, diff


def apply_mark_done_action(
    items: list[dict[str, Any]],
    target_key: Any,
    evidence: str,
    cycle: int,
) -> tuple[bool, str]:
    """Mark an existing plan item as done."""
    idx, item = find_plan_item(items, target_key)
    if item is None:
        return False, f"Target item '{target_key}' not found."
    item["status"] = "done"
    item["updated_cycle"] = cycle or item.get("updated_cycle", 1)
    if evidence:
        item["evidence"] = evidence
    diff = f"Marked done {item.get('id', idx)}: '{item.get('goal', '')}'"
    return True, diff


def apply_reorder_action(
    items: list[dict[str, Any]],
    order: list[str] | None,
) -> tuple[bool, str]:
    """Reorder items list based on provided goal ID order."""
    if not isinstance(order, list) or not order:
        return False, "List of goal IDs required for action 'reorder'."
    order_map = {item_id.strip(): idx for idx, item_id in enumerate(order)}
    items.sort(key=lambda it: order_map.get(str(it.get("id", "")).strip(), 999))
    diff = f"Reordered plan goals: {', '.join(order)}"
    return True, diff


def apply_plugin_review_action(
    plugin_project_decisions: list[dict[str, Any]],
    proj_name: str,
    decision: str,
    reason: str,
    cycle: int,
) -> tuple[bool, str]:
    """Record a stop-loss review decision for a plugin project."""
    dec = str(decision).strip().lower()
    if dec not in {"continue", "reduce_scope", "abandon"}:
        return False, f"Invalid stop-loss decision '{dec}'. Must be continue, reduce_scope, or abandon."
    diff = f"Stop-loss review for '{proj_name}': decision={dec}, reason={reason}"
    plugin_project_decisions.append({
        "project": proj_name,
        "decision": dec,
        "reason": reason,
        "cycle": cycle,
        "at": now_utc(),
    })
    return True, diff
