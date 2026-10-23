"""Plan and environment map tool execution handlers."""
from __future__ import annotations

from typing import Any


def handle_read_plan(plan_store: Any, include_history: bool = False, **arguments: Any) -> dict[str, Any]:
    """Read persistent plan state."""
    if plan_store is None:
        raise RuntimeError("persistent plan store is not configured")
    history = bool(include_history or arguments.get("history", False))
    return plan_store.read_plan(include_history=history)


def handle_update_plan(
    plan_store: Any,
    logger: Any,
    cost_ledger: Any,
    current_cycle: int,
    plugin_dev: Any = None,
    **arguments: Any,
) -> dict[str, Any]:
    """Update persistent plan state and emit audit events for review decisions."""
    if plan_store is None:
        raise RuntimeError("persistent plan store is not configured")
    cycle = arguments.pop("cycle", current_cycle)
    res = plan_store.update_plan(cycle=cycle, **arguments)
    if res.get("ok"):
        act = str(arguments.get("action", "")).lower()
        dec = str(arguments.get("decision", "")).lower()
        proj = str(arguments.get("project") or arguments.get("id") or arguments.get("goal") or "").strip()
        reason_text = str(arguments.get("reason", ""))
        if act in {"decide_plugin_review", "plugin_project_review"} or (dec in {"continue", "reduce_scope", "abandon"} and proj):
            ledger_summary = cost_ledger.get_summary() if cost_ledger is not None else {}
            pdata = ledger_summary.get("plugin_projects", {}).get(proj, {})
            thresh = int(arguments.get("threshold", 25))
            if plugin_dev is not None and hasattr(plugin_dev, "record_review_decision"):
                plugin_dev.record_review_decision(proj, thresh)
            if logger is not None:
                logger.log(
                    "plugin_project_review",
                    project=proj,
                    threshold=thresh,
                    decision=dec or "continue",
                    reason=reason_text,
                    tokens_spent=pdata.get("tokens", 0),
                    cycles_spent=pdata.get("cycles", 0),
                    token_estimate=pdata.get("token_estimate", 0),
                    cycle_estimate=pdata.get("cycle_estimate", 0),
                )
    return res


def handle_update_environment_map(learning: Any, entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Record observed environment facts through the learning store."""
    if learning is None:
        raise RuntimeError("persistent learning store is not configured")
    return learning.update_map(entries, source="agent tool observation")
