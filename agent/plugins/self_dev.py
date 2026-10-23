"""Plugin self-development subsystem: proposing, scaffolding, validating, testing, and reviewing (facade)."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from agent.infra.cost_ledger import CostLedger
from agent.infra.event_log import EventLogger
from agent.infra.process_runner import run_process
from agent.plugins.dev.environment import (
    SECRET_NAME_MARKERS,
    child_env,
    now_utc,
)
from agent.plugins.dev.promotion import promote_draft_by_human
from agent.plugins.dev.proposals import (
    get_proposal,
    list_proposals,
    validate_and_record_proposal,
)
from agent.plugins.dev.review import execute_plugin_review
from agent.plugins.dev.scaffolding import scaffold_plugin_draft
from agent.plugins.dev.stop_loss import (
    get_pending_stop_loss,
    record_review_decision,
)
from agent.plugins.dev.testing import execute_isolated_test
from agent.plugins.dev.validation import (
    NETWORK_MODULES,
    PROMPT_INJECTION_PATTERNS,
    SUBPROCESS_MODULES,
    validate_draft_plugin,
)
from agent.prompts.critics import PLUGIN_CRITIC_PROMPT

_child_env = child_env


class PluginDevManager:
    """Manages the lifecycle of self-developed plugins in workspace/plugin_dev/."""

    def __init__(
        self,
        workspace: Path | str,
        logger: EventLogger | None = None,
        cost_ledger: CostLedger | None = None,
        review_call: Callable[..., Any] | None = None,
    ) -> None:
        self.workspace = Path(workspace).resolve()
        self.dev_dir = self.workspace / "plugin_dev"
        self.plugins_dir = self.workspace / "plugins"
        self.state_dir = self.workspace / "state"
        self.proposals_file = self.state_dir / "plugin_proposals.jsonl"
        self.logger = logger or EventLogger(self.workspace)
        self.cost_ledger = cost_ledger or CostLedger(self.workspace)
        self.review_call = review_call
        self.reviewed_thresholds: dict[str, set[int]] = {}

    def get_proposal(self, name: str) -> dict[str, Any] | None:
        """Fetch proposal by name from state/plugin_proposals.jsonl."""
        return get_proposal(self.proposals_file, name)

    def get_pending_stop_loss(self, name: str) -> list[int]:
        """Check if any stop-loss review threshold (25, 50, 100) is reached but unacknowledged."""
        return get_pending_stop_loss(self.proposals_file, self.cost_ledger, self.reviewed_thresholds, name)

    def record_review_decision(self, name: str, threshold: int) -> None:
        """Mark a stop-loss review threshold as acknowledged and reviewed."""
        record_review_decision(self.reviewed_thresholds, name, threshold)

    def ensure_directories(self) -> None:
        """Ensure necessary directories exist."""
        self.dev_dir.mkdir(parents=True, exist_ok=True)
        self.plugins_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def propose_plugin(
        self,
        name: str,
        need: str,
        evidence: str,
        alternatives_considered: Any,
        estimate: dict[str, Any] | str,
        expected_benefit: str,
        actions_needed_with_risk_levels: Any,
        maintenance_burden: str,
        stop_loss: Any,
        rollback: str,
        plan_store: Any | None = None,
        cycle: int = 1,
    ) -> dict[str, Any]:
        """Validate and record a plugin proposal with required cost derivation."""
        self.ensure_directories()
        return validate_and_record_proposal(
            proposals_file=self.proposals_file,
            cost_ledger=self.cost_ledger,
            logger=self.logger,
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
            cycle=cycle,
        )

    def scaffold_plugin(
        self,
        name: str,
        kind: str = "skill",
        description: str = "",
    ) -> dict[str, Any]:
        """Scaffold a plugin draft in workspace/plugin_dev/<name>/ from template."""
        self.ensure_directories()
        return scaffold_plugin_draft(
            dev_dir=self.dev_dir,
            logger=self.logger,
            name=name,
            kind=kind,
            description=description,
        )

    def validate_plugin(self, name: str) -> dict[str, Any]:
        """Perform strict static validation on a draft plugin in workspace/plugin_dev/<name>/."""
        return validate_draft_plugin(
            dev_dir=self.dev_dir,
            logger=self.logger,
            pending_reviews=self.get_pending_stop_loss(name),
            name=name,
        )

    def test_plugin(
        self,
        name: str,
        test_type: str = "unit",
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Execute unittests for a draft plugin in isolation without touching real resources."""
        return execute_isolated_test(
            dev_dir=self.dev_dir,
            workspace=self.workspace,
            logger=self.logger,
            pending_reviews=self.get_pending_stop_loss(name),
            run_process_fn=run_process,
            name=name,
            test_type=test_type,
            timeout=timeout,
        )

    def request_plugin_review(self, name: str) -> dict[str, Any]:
        """Run validation, isolated tests, and strict plugin critic LLM review."""
        return execute_plugin_review(
            dev_dir=self.dev_dir,
            logger=self.logger,
            validate_fn=self.validate_plugin,
            test_fn=self.test_plugin,
            review_call=self.review_call,
            pending_reviews=self.get_pending_stop_loss(name),
            name=name,
        )

    def promote_draft_by_human(self, name: str) -> dict[str, Any]:
        """Human-only promotion: copies validated draft to workspace/plugins/ as DISABLED."""
        return promote_draft_by_human(
            dev_dir=self.dev_dir,
            plugins_dir=self.plugins_dir,
            workspace=self.workspace,
            logger=self.logger,
            validate_fn=self.validate_plugin,
            name=name,
        )

    def list_proposals(self) -> list[dict[str, Any]]:
        """Return all proposals from state/plugin_proposals.jsonl."""
        return list_proposals(self.proposals_file)


__all__ = [
    "PluginDevManager",
    "SECRET_NAME_MARKERS",
    "PROMPT_INJECTION_PATTERNS",
    "NETWORK_MODULES",
    "SUBPROCESS_MODULES",
    "PLUGIN_CRITIC_PROMPT",
    "now_utc",
    "_child_env",
    "run_process",
]
