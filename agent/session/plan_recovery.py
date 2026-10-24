"""Plan recovery, normalization, and display formatting for wake sessions."""
from __future__ import annotations

from typing import Any

from agent.learning.plan_statuses import (
    COMPLETED_PLAN_STATUSES,
    visible_plan_items_incl_suspended,
)
from agent.session.session import default_plan


def visible_plan_items(plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return active plan items for the live panel (including suspended plugin items)."""
    return visible_plan_items_incl_suspended(plan)


def normalized_plan(plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only actionable plan entries in durable state."""
    active = visible_plan_items(plan)
    for it in active:
        g = str(it.get("goal") or it.get("step", "")).strip()
        it["goal"] = g
        it["step"] = g
    return active if active else default_plan()


def format_starting_plan(starting_plan: list[dict[str, Any]], session_id: str = "") -> str:
    """Render the session starting plan as clean markdown."""
    if not starting_plan:
        return "No starting plan recorded for this session yet."

    session_label = f" (Session `{session_id[:12]}`)" if session_id else ""
    lines = [
        f"**Starting Plan / Targets{session_label}**",
        "",
        "*This was the plan when this session started:*",
        "",
    ]
    for idx, item in enumerate(starting_plan, 1):
        if not isinstance(item, dict):
            continue
        step = str(item.get("goal") or item.get("step", "")).strip()
        status = str(item.get("status", "todo")).strip().lower()
        lines.append(f"{idx}. ({status}) {step}")
        why = str(item.get("why", "")).strip()
        if why:
            lines.append(f"   *Why:* {why}")
    return "\n".join(lines)


def recover_budget_blocked_plan(
    plan: list[dict[str, Any]],
    daily_ledger: Any,
    learning_store: Any,
    token_budget: int | None,
    logger: Any,
) -> tuple[list[dict[str, Any]], bool]:
    """Clear stale budget blockers once the daily ledger has room again."""
    if daily_ledger.available_tokens() < 2_048:
        return plan, False

    entries = learning_store._load_map().get("entries", {})
    packages_value = entries.get("packages", {}).get("value")
    packages_known = bool(packages_value) and packages_value != "not yet inventoried"
    environment_known = any(
        bool(entries.get(key, {}).get("value"))
        for key in ("disk", "network_reachability", "network_ping_google")
    )
    changed = False
    retained: list[dict[str, Any]] = []
    for item in plan:
        if not isinstance(item, dict):
            continue
        if str(item.get("status", "")).strip().lower().startswith("suspended"):
            retained.append(item)
            continue
        details = f"{item.get('step', '')} {item.get('why', '')}".lower()
        token_item = any(marker in details for marker in ("token", "budget", "limit"))
        package_item = "installed python packages" in details or "python package inventory" in details
        environment_item = "free disk" in details or "network reachability" in details

        if token_item and token_budget is None:
            changed = True
            continue
        if package_item and packages_known:
            changed = True
            continue
        if environment_item and environment_known:
            changed = True
            continue
        if token_item and str(item.get("status", "")).lower() in {"blocked", "stuck"}:
            item["status"] = "todo"
            item["why"] = "The previous token-budget blocker is cleared; continue using the remaining daily allowance."
            changed = True
        retained.append(item)

    new_plan = retained or default_plan()
    if changed:
        logger.log("stale_budget_plan_recovered", available_daily_tokens=daily_ledger.available_tokens())
        logger.narrate("I removed stale plan items and will continue using the available daily allowance.")
    return new_plan, changed


def revise_session_plan(
    coordinator: Any,
) -> None:
    """Use the durable plan as the only source for the session's visible goals."""
    coordinator.plan_store.load()
    coordinator.plan = list(coordinator.plan_store.items or default_plan())
    coordinator.logger.narrate("I loaded the persistent goals and will review them during this cycle.")
    with coordinator.lock:
        coordinator.starting_plan = [dict(it) for it in coordinator.plan]
        coordinator.starting_session_id = coordinator.status.session_id


__all__ = [
    "COMPLETED_PLAN_STATUSES",
    "visible_plan_items",
    "normalized_plan",
    "format_starting_plan",
    "recover_budget_blocked_plan",
    "revise_session_plan",
]
