"""Persistent, agent-owned autonomous plan store for SELF (facade)."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from agent.infra.event_log import EventLogger
from agent.learning.plan_statuses import (
    ACTIVE_PLAN_STATUSES,
    COMPLETED_PLAN_STATUSES,
    SUSPENDED_PLAN_STATUS_PREFIX,
    visible_plan_items,
)
from agent.learning.plans.actions import (
    apply_add_action,
    apply_drop_action,
    apply_edit_action,
    apply_mark_done_action,
    apply_plugin_review_action,
    apply_reorder_action,
    find_plan_item,
)
from agent.learning.plans.archive import append_archive_records, read_archived_items
from agent.learning.plans.consolidation import consolidate_plan_items
from agent.learning.plans.human_decisions import process_human_input_decision
from agent.learning.plans.hygiene import apply_plan_hygiene
from agent.learning.plans.persistence import (
    build_seed_goal,
    load_plan_data,
    now_utc,
    save_plan_atomic,
)
from agent.learning.plans.plugin_lifecycle import (
    SUSPENDED_PLUGIN_STATUS,
    resume_plugin_goals,
    suspend_plugin_goals,
)
from agent.learning.plans.queries import (
    build_retrieval_query,
    filter_top_items,
    format_prompt_summary,
)
from agent.prompts.system import SEED_STANDING_GOAL

WORD = re.compile(r"[a-zA-Z0-9_.-]{2,}")


class PlanStore:
    """Agent-writable persistent plan store.

    Guarantees:
    - Persistent state under state/plan.json.
    - Plan versioning with diffs and required evidence-backed reasons.
    - Agent tools: read_plan, update_plan (add, edit, drop, reorder, mark_done, unchanged).
    - Top-item query and summary generation for cycle prompt and tool retrieval.
    - Plan hygiene: mark/drop stale items, size cap by consolidation (never truncation).
    """

    def __init__(self, workspace: str | Path, logger: EventLogger, max_items: int = 12) -> None:
        self.workspace = Path(workspace)
        self.logger = logger
        self.state_dir = self.workspace / "state"
        self.plan_path = self.state_dir / "plan.json"
        self.archive_path = self.state_dir / "plan_archive.jsonl"
        self.max_items = max(4, max_items)
        self.plan_version = 1
        self.items: list[dict[str, Any]] = []
        self.human_input_decisions: list[dict[str, Any]] = []
        self.plugin_project_decisions: list[dict[str, Any]] = []
        self._next_id = 1

    def _append_archive(self, records: list[dict[str, Any]]) -> None:
        """Append archived goals to state/plan_archive.jsonl."""
        append_archive_records(self.archive_path, self.state_dir, self.logger.redactor, records)

    def get_archived_items(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Return historical completed/dropped plan goals from plan_archive.jsonl."""
        return read_archived_items(self.archive_path, limit=limit)

    def initialize(self, seed_task: str = "", default_step: str = "") -> None:
        """Load durable plan, or seed an initial plan goal if empty."""
        self.state_dir.mkdir(parents=True, exist_ok=True)
        if self.load():
            return
        initial_goal = build_seed_goal(seed_task=seed_task, default_step=default_step)
        self.items = [initial_goal]
        self.human_input_decisions = []
        self.plugin_project_decisions = []
        self.plan_version = 1
        self._next_id = 2
        self._save_atomic(
            diff=f"Seeded plan with goal: {initial_goal['goal'][:100]}",
            reason="Harness initialization",
            cycle=1,
        )

    def load(self) -> bool:
        """Load plan from disk if present."""
        data = load_plan_data(self.plan_path)
        if data is None:
            return False
        self.plan_version = data["plan_version"]
        self.human_input_decisions = data["human_input_decisions"]
        self.plugin_project_decisions = data["plugin_project_decisions"]
        self.items = data["items"]
        self._next_id = data["next_id"]
        return True

    def _save_atomic(self, diff: str, reason: str, cycle: int = 0) -> None:
        """Atomically persist plan to disk."""
        save_plan_atomic(
            plan_path=self.plan_path,
            redactor=self.logger.redactor,
            plan_version=self.plan_version,
            diff=diff,
            reason=reason,
            items=self.items,
            human_input_decisions=self.human_input_decisions,
            plugin_project_decisions=self.plugin_project_decisions,
            cycle=cycle,
        )

    def read_plan(self, include_history: bool = False, **extra: Any) -> dict[str, Any]:
        """Tool implementation for reading current plan state."""
        active = self.top_items(limit=100)
        res = {
            "ok": True,
            "plan_version": self.plan_version,
            "total_goals": len(self.items),
            "active_goals": len(active),
            "top_goal": active[0] if active else None,
            "items": list(self.items),
            "human_input_decisions": list(self.human_input_decisions),
            "plugin_project_decisions": list(self.plugin_project_decisions),
        }
        if include_history or extra.get("history", False):
            res["history"] = self.get_archived_items()
        return res

    def _find_item(self, target: Any) -> tuple[int, dict[str, Any]] | tuple[None, None]:
        """Locate an item by ID, index, or substring."""
        return find_plan_item(self.items, target)

    def update_plan(
        self,
        action: str,
        reason: str,
        goal: str = "",
        id: str = "",
        evidence: str = "",
        next_steps: str = "",
        priority: int = 2,
        status: str = "",
        order: list[str] | None = None,
        cycle: int = 0,
        **extra: Any,
    ) -> dict[str, Any]:
        """Update plan with a required reason citing evidence."""
        clean_reason = str(reason).strip()
        if not clean_reason:
            return {
                "ok": False,
                "error": "A non-empty 'reason' citing evidence is required to update the plan.",
            }

        action = str(action).strip().lower()
        evidence_ref = str(evidence).strip() or clean_reason

        if action == "unchanged":
            self.logger.log(
                "plan_unchanged",
                cycle=cycle,
                plan_version=self.plan_version,
                diff="",
                reason=clean_reason,
                evidence=evidence_ref,
                source="agent",
            )
            return {
                "ok": True,
                "action": "unchanged",
                "plan_version": self.plan_version,
                "diff": "Plan unchanged",
                "reason": clean_reason,
                "source": "agent",
                "plan": list(self.items),
            }

        diff = ""
        if action == "add":
            ok, msg, evidence_ref, self._next_id, _ = apply_add_action(
                items=self.items,
                next_id=self._next_id,
                goal=goal,
                reason=clean_reason,
                evidence=evidence_ref,
                next_steps=next_steps,
                priority=priority,
                status=status or "todo",
                cycle=cycle,
                extra=extra,
            )
            if not ok:
                return {"ok": False, "error": msg}
            diff = msg

        elif action in {"decide_human_input", "human_input"}:
            input_text = str(extra.get("input") or goal or extra.get("text", "")).strip()
            decision = str(extra.get("decision") or status or "accepted").strip().lower()
            modified_goal = str(extra.get("modified_goal") or goal or "").strip()
            return self.record_human_input_decision(
                input_text=input_text,
                decision=decision,
                reason=clean_reason,
                priority=int(priority) if isinstance(priority, (int, float)) else 2,
                modified_goal=modified_goal,
                cycle=cycle,
            )

        elif action in {"edit", "update"}:
            target_key = id or extra.get("target") or goal
            ok, msg, evidence_ref = apply_edit_action(
                items=self.items,
                target_key=target_key,
                goal=goal,
                status=status,
                next_steps=next_steps,
                evidence=evidence_ref,
                priority=priority,
                cycle=cycle,
                extra=extra,
            )
            if not ok:
                return {"ok": False, "error": msg}
            diff = msg

        elif action in {"drop", "remove", "delete"}:
            target_key = id or extra.get("target") or goal
            ok, msg = apply_drop_action(
                items=self.items,
                target_key=target_key,
                evidence=evidence_ref,
                cycle=cycle,
            )
            if not ok:
                return {"ok": False, "error": msg}
            diff = msg

        elif action in {"mark_done", "done", "complete"}:
            target_key = id or extra.get("target") or goal
            ok, msg = apply_mark_done_action(
                items=self.items,
                target_key=target_key,
                evidence=evidence_ref,
                cycle=cycle,
            )
            if not ok:
                return {"ok": False, "error": msg}
            diff = msg

        elif action == "reorder":
            ok, msg = apply_reorder_action(items=self.items, order=order)
            if not ok:
                return {"ok": False, "error": msg}
            diff = msg

        elif action in {"decide_plugin_review", "plugin_project_review"}:
            proj_name = str(extra.get("project") or id or goal or "").strip()
            dec = str(extra.get("decision") or status or "continue").strip().lower()
            ok, msg = apply_plugin_review_action(
                plugin_project_decisions=self.plugin_project_decisions,
                proj_name=proj_name,
                decision=dec,
                reason=clean_reason,
                cycle=cycle,
            )
            if not ok:
                return {"ok": False, "error": msg}
            del self.plugin_project_decisions[:-32]
            diff = msg

        else:
            return {
                "ok": False,
                "error": f"Unknown plan action '{action}'. Valid actions: add, edit, drop, mark_done, reorder, unchanged, decide_plugin_review.",
            }

        # Apply hygiene consolidation if item count exceeds max_items
        if len(self.items) > self.max_items:
            self.items = consolidate_plan_items(self.items, max_items=self.max_items)
            diff += f" [Consolidated plan to {len(self.items)} items]"

        self.plan_version += 1
        self._save_atomic(diff=diff, reason=clean_reason, cycle=cycle)
        self.logger.log(
            "plan_updated",
            cycle=cycle,
            plan_version=self.plan_version,
            diff=diff,
            reason=clean_reason,
            evidence=evidence_ref,
        )
        return {
            "ok": True,
            "action": action,
            "plan_version": self.plan_version,
            "diff": diff,
            "reason": clean_reason,
            "plan": list(self.items),
        }

    def record_unchanged(self, cycle: int, reason: str, evidence: str = "", source: str = "harness_auto") -> None:
        """Log a plan_unchanged review event when no edits occurred in a cycle."""
        clean_reason = str(reason).strip() or "Plan remains valid; continuing execution of active goals."
        evidence_ref = str(evidence).strip() or "Cycle observation"
        self.logger.log(
            "plan_unchanged",
            cycle=cycle,
            plan_version=self.plan_version,
            diff="",
            reason=clean_reason,
            evidence=evidence_ref,
            source=source,
        )

    def record_human_input_decision(
        self,
        input_text: str,
        decision: str,
        reason: str,
        priority: int = 2,
        modified_goal: str = "",
        cycle: int = 0,
    ) -> dict[str, Any]:
        """Record an autonomous decision on a human input with a required reason."""
        clean_reason = str(reason).strip()
        ok, res, self._next_id, diff = process_human_input_decision(
            items=self.items,
            human_input_decisions=self.human_input_decisions,
            next_id=self._next_id,
            input_text=input_text,
            decision=decision,
            reason=reason,
            priority=priority,
            modified_goal=modified_goal,
            cycle=cycle,
        )
        if not ok:
            return res

        self.logger.log(
            "human_input_decision",
            input=res["input"],
            decision=res["decision"],
            reason=res["reason"],
            priority=res["priority"],
            goal_id=res["goal_id"],
            cycle=cycle,
        )

        self.plan_version += 1
        self._save_atomic(diff=diff, reason=clean_reason, cycle=cycle)
        res["plan_version"] = self.plan_version
        res["diff"] = diff
        res["plan"] = list(self.items)
        return res

    def top_items(self, limit: int = 3, active_plugins: Any = None) -> list[dict[str, Any]]:
        """Return active plan items sorted by priority and position."""
        return filter_top_items(self.items, limit=limit, active_plugins=active_plugins)

    def retrieval_query(self) -> str:
        """Build retrieval text from top active plan items rather than fixed task string."""
        return build_retrieval_query(self.top_items(limit=3))

    def prompt_summary(self, active_plugins: Any = None) -> str:
        """Format the active plan items for inclusion in cycle prompts."""
        return format_prompt_summary(
            active=self.top_items(limit=10, active_plugins=active_plugins),
            archived=self.get_archived_items(limit=3),
            human_input_decisions=self.human_input_decisions,
        )

    def hygiene(self, cycle: int, max_stale_cycles: int = 5) -> list[str]:
        """Purge completed/dropped items to archive, mark stale items, and cap size."""
        self.items, purged_records, actions, changed = apply_plan_hygiene(
            items=self.items,
            max_items=self.max_items,
            cycle=cycle,
            max_stale_cycles=max_stale_cycles,
        )
        if purged_records:
            self._append_archive(purged_records)

        if changed:
            self.plan_version += 1
            diff_text = "; ".join(actions)
            self._save_atomic(diff=diff_text, reason="Plan hygiene maintenance", cycle=cycle)
            self.logger.log(
                "plan_hygiene_applied",
                cycle=cycle,
                plan_version=self.plan_version,
                diff=diff_text,
            )
        return actions

    def suspend_plugin_goals(self, plugin_name: str, cycle: int = 0) -> list[str]:
        """Suspend all active goals associated with a disabled plugin."""
        suspended_ids, diff = suspend_plugin_goals(self.items, plugin_name, cycle=cycle)
        if suspended_ids:
            self.plan_version += 1
            self._save_atomic(diff=diff, reason=f"Plugin '{plugin_name}' disabled", cycle=cycle)
            self.logger.log("plan_goals_suspended", plugin=plugin_name, goal_ids=suspended_ids)
        return suspended_ids

    def resume_plugin_goals(self, plugin_name: str, cycle: int = 0) -> list[str]:
        """Resume suspended goals when a plugin is re-enabled successfully."""
        resumed_ids, diff = resume_plugin_goals(self.items, plugin_name, cycle=cycle)
        if resumed_ids:
            self.plan_version += 1
            self._save_atomic(diff=diff, reason=f"Plugin '{plugin_name}' re-enabled", cycle=cycle)
            self.logger.log("plan_goals_resumed", plugin=plugin_name, goal_ids=resumed_ids)
        return resumed_ids


__all__ = [
    "COMPLETED_PLAN_STATUSES",
    "ACTIVE_PLAN_STATUSES",
    "SUSPENDED_PLAN_STATUS_PREFIX",
    "SUSPENDED_PLUGIN_STATUS",
    "WORD",
    "SEED_STANDING_GOAL",
    "now_utc",
    "visible_plan_items",
    "consolidate_plan_items",
    "PlanStore",
]
