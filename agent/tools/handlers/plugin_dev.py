"""Plugin self-development lifecycle and cost ledger tool handlers."""
from __future__ import annotations

from typing import Any


def handle_read_cost_ledger(cost_ledger: Any) -> dict[str, Any]:
    """Read measured cost ledger baselines and plugin project totals."""
    return cost_ledger.get_summary()


def handle_propose_plugin(
    plugin_dev: Any,
    plan_store: Any,
    current_cycle: int,
    name: str,
    need: str,
    evidence: str,
    alternatives_considered: Any,
    estimate: Any,
    expected_benefit: str,
    actions_needed_with_risk_levels: Any,
    maintenance_burden: str,
    stop_loss: Any,
    rollback: str,
) -> dict[str, Any]:
    """Propose developing a specialization plugin."""
    if plugin_dev is None:
        return {"ok": False, "error": "Plugin development is not configured on ToolRunner."}
    return plugin_dev.propose_plugin(
        name=name,
        need=need,
        evidence=evidence,
        alternatives_considered=alternatives_considered,
        estimate=estimate,
        expected_benefit=expected_benefit,
        actions_needed_with_risk_levels=actions_needed_with_risk_levels,
        maintenance_burden=maintenance_burden,
        stop_loss=stop_loss,
        rollback=rollback,
        plan_store=plan_store,
        cycle=current_cycle,
    )


def handle_scaffold_plugin(plugin_dev: Any, name: str, kind: str = "skill", description: str = "") -> dict[str, Any]:
    """Scaffold a plugin draft in workspace/plugin_dev/<name>/."""
    if plugin_dev is None:
        return {"ok": False, "error": "Plugin development is not configured on ToolRunner."}
    return plugin_dev.scaffold_plugin(name=name, kind=kind, description=description)


def handle_validate_plugin(plugin_dev: Any, name: str) -> dict[str, Any]:
    """Run static validation on a plugin draft in workspace/plugin_dev/<name>/."""
    if plugin_dev is None:
        return {"ok": False, "error": "Plugin development is not configured on ToolRunner."}
    return plugin_dev.validate_plugin(name=name)


def handle_test_plugin(plugin_dev: Any, name: str, test_type: str = "unit") -> dict[str, Any]:
    """Execute unittests for a plugin draft in workspace/plugin_dev/<name>/."""
    if plugin_dev is None:
        return {"ok": False, "error": "Plugin development is not configured on ToolRunner."}
    return plugin_dev.test_plugin(name=name, test_type=test_type)


def handle_request_plugin_review(plugin_dev: Any, name: str) -> dict[str, Any]:
    """Request strict critic review of a validated plugin draft."""
    if plugin_dev is None:
        return {"ok": False, "error": "Plugin development is not configured on ToolRunner."}
    return plugin_dev.request_plugin_review(name=name)
