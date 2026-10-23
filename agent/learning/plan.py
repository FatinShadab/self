"""Persistent, agent-owned autonomous plan store for SELF."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.infra.event_log import EventLogger

COMPLETED_PLAN_STATUSES = frozenset({
    "done", "complete", "completed", "achieved", "finished", "closed",
    "cancelled", "canceled", "dropped",
})

ACTIVE_PLAN_STATUSES = frozenset({
    "todo", "in_progress", "in-progress", "blocked", "stale",
})

SUSPENDED_PLAN_STATUS_PREFIX = "suspended"
SUSPENDED_PLUGIN_STATUS = "suspended: plugin disabled"

WORD = re.compile(r"[a-zA-Z0-9_.-]{2,}")

from agent.prompts.system import SEED_STANDING_GOAL


def now_utc() -> str:
    """Return the current UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


def visible_plan_items(plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return only active plan items for live display and execution."""
    return [
        item for item in plan
        if isinstance(item, dict)
        and str(item.get("status", "todo")).strip().lower() not in COMPLETED_PLAN_STATUSES
        and not str(item.get("status", "")).strip().lower().startswith(SUSPENDED_PLAN_STATUS_PREFIX)
    ]


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

    # If active items alone exceed max_items, preserve top priority/early active items
    # and consolidate remaining lower-priority active items into a background objective
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
        if not records:
            return
        self.state_dir.mkdir(parents=True, exist_ok=True)
        with self.archive_path.open("a", encoding="utf-8") as f:
            for rec in records:
                safe_rec = self.logger.redactor.value(rec)
                f.write(json.dumps(safe_rec, ensure_ascii=False) + "\n")

    def get_archived_items(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Return historical completed/dropped plan goals from plan_archive.jsonl."""
        if not self.archive_path.exists():
            return []
        items: list[dict[str, Any]] = []
        try:
            for line in self.archive_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    try:
                        items.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except OSError:
            return []
        if limit is not None and limit > 0:
            return items[-limit:]
        return items

    def initialize(self, seed_task: str = "", default_step: str = "") -> None:
        """Load durable plan, or seed an initial plan goal if empty."""
        self.state_dir.mkdir(parents=True, exist_ok=True)
        loaded = self.load()
        if loaded:
            return

        seed_content = seed_task.strip() or default_step.strip() or SEED_STANDING_GOAL
        initial_goal = {
            "id": "goal-1",
            "goal": seed_content,
            "step": seed_content,
            "status": "todo",
            "why": "Initial exploration and environment verification",
            "priority": 2,
            "evidence": "Seed goal from harness startup",
            "next_steps": "Inspect environment facts and proceed with verified discoveries.",
            "created_cycle": 1,
            "updated_cycle": 1,
            "plugin": "core",
            "body": "container",
        }
        self.items = [initial_goal]
        self.human_input_decisions = []
        self.plugin_project_decisions = []
        self.plan_version = 1
        self._next_id = 2
        self._save_atomic(diff=f"Seeded plan with goal: {seed_content[:100]}", reason="Harness initialization", cycle=1)

    def load(self) -> bool:
        """Load plan from disk if present."""
        if not self.plan_path.exists():
            return False
        try:
            data = json.loads(self.plan_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return False
            self.plan_version = int(data.get("plan_version", 1))
            self.human_input_decisions = list(data.get("human_input_decisions", []))
            self.plugin_project_decisions = list(data.get("plugin_project_decisions", []))
            raw_items = data.get("items", [])
            self.items = []
            max_id_num = 0
            for item in raw_items:
                if not isinstance(item, dict):
                    continue
                normalized = dict(item)
                # Keep goal and step in sync
                goal_text = str(normalized.get("goal") or normalized.get("step", "")).strip()
                normalized["goal"] = goal_text
                normalized["step"] = goal_text
                normalized.setdefault("plugin", "core")
                normalized.setdefault("body", "container")
                # Track max id number
                item_id = str(normalized.get("id", ""))
                match = re.search(r"(\d+)", item_id)
                if match:
                    max_id_num = max(max_id_num, int(match.group(1)))
                self.items.append(normalized)
            self._next_id = max_id_num + 1 if max_id_num > 0 else len(self.items) + 1
            return True
        except (OSError, json.JSONDecodeError):
            return False

    def _save_atomic(self, diff: str, reason: str, cycle: int = 0) -> None:
        """Atomically persist plan to disk."""
        data = {
            "schema_version": 2,
            "plan_version": self.plan_version,
            "updated_at": now_utc(),
            "cycle": cycle,
            "last_diff": diff,
            "last_reason": reason,
            "items": self.logger.redactor.value(self.items),
            "human_input_decisions": self.logger.redactor.value(self.human_input_decisions),
            "plugin_project_decisions": self.logger.redactor.value(self.plugin_project_decisions),
        }
        temp_path = self.plan_path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temp_path, self.plan_path)

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
        if target is None:
            return None, None
        target_str = str(target).strip()
        # Match by exact id
        for idx, item in enumerate(self.items):
            if str(item.get("id", "")).strip() == target_str:
                return idx, item
        # Match by 1-based index
        if target_str.isdigit():
            idx = int(target_str) - 1
            if 0 <= idx < len(self.items):
                return idx, self.items[idx]
        # Match by goal substring
        target_lower = target_str.lower()
        for idx, item in enumerate(self.items):
            goal = str(item.get("goal", "")).lower()
            if target_lower in goal or goal in target_lower:
                return idx, item
        return None, None

    def update_plan(
        self,
        action: str,
        reason: str,
        goal: str = "",
        id: str = "",
        evidence: str = "",
        next_steps: str = "",
        priority: int = 2,
        status: str = "todo",
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
        diff = ""
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

        if action == "add":
            goal_text = str(goal or extra.get("step", "")).strip()
            if not goal_text:
                return {"ok": False, "error": "Goal text is required for action 'add'."}
            new_id = f"goal-{self._next_id}"
            self._next_id += 1
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
                "why": extra.get("why") or clean_reason,
                "evidence": evidence_ref,
                "next_steps": next_steps.strip() or f"Execute investigation for {goal_text}",
                "created_cycle": cycle or 1,
                "updated_cycle": cycle or 1,
                "plugin": p_tag,
                "body": b_tag,
            }
            # Add to top if high priority (priority 1), else append
            if item["priority"] == 1:
                self.items.insert(0, item)
            else:
                self.items.append(item)
            diff = f"Added {new_id}: '{goal_text}' (priority={item['priority']}, status={item['status']}, source={item['source']}, plugin={item['plugin']})"

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
            idx, item = self._find_item(target_key)
            if item is None:
                return {"ok": False, "error": f"Target item '{target_key}' not found."}
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
            if evidence_ref:
                item["evidence"] = evidence_ref
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

        elif action in {"drop", "remove", "delete"}:
            target_key = id or extra.get("target") or goal
            idx, item = self._find_item(target_key)
            if item is None:
                return {"ok": False, "error": f"Target item '{target_key}' not found."}
            item["status"] = "dropped"
            item["updated_cycle"] = cycle or item.get("updated_cycle", 1)
            item["evidence"] = evidence_ref
            diff = f"Dropped {item.get('id', idx)}: '{item.get('goal', '')}'"

        elif action in {"mark_done", "done", "complete"}:
            target_key = id or extra.get("target") or goal
            idx, item = self._find_item(target_key)
            if item is None:
                return {"ok": False, "error": f"Target item '{target_key}' not found."}
            item["status"] = "done"
            item["updated_cycle"] = cycle or item.get("updated_cycle", 1)
            if evidence_ref:
                item["evidence"] = evidence_ref
            diff = f"Marked done {item.get('id', idx)}: '{item.get('goal', '')}'"

        elif action == "reorder":
            if not isinstance(order, list) or not order:
                return {"ok": False, "error": "List of goal IDs required for action 'reorder'."}
            order_map = {item_id.strip(): idx for idx, item_id in enumerate(order)}
            self.items.sort(key=lambda it: order_map.get(str(it.get("id", "")).strip(), 999))
            diff = f"Reordered plan goals: {', '.join(order)}"

        elif action in {"decide_plugin_review", "plugin_project_review"}:
            proj_name = str(extra.get("project") or id or goal or "").strip()
            dec = str(extra.get("decision") or status or "continue").strip().lower()
            if dec not in {"continue", "reduce_scope", "abandon"}:
                return {"ok": False, "error": f"Invalid stop-loss decision '{dec}'. Must be continue, reduce_scope, or abandon."}
            diff = f"Stop-loss review for '{proj_name}': decision={dec}, reason={clean_reason}"
            self.plugin_project_decisions.append({
                "project": proj_name,
                "decision": dec,
                "reason": clean_reason,
                "cycle": cycle,
                "at": now_utc(),
            })
            self.plugin_project_decisions = self.plugin_project_decisions[-32:]

        else:
            return {"ok": False, "error": f"Unknown plan action '{action}'. Valid actions: add, edit, drop, mark_done, reorder, unchanged, decide_plugin_review."}

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
        clean_input = str(input_text).strip()
        clean_decision = str(decision).strip().lower()
        clean_reason = str(reason).strip()
        if not clean_input:
            return {"ok": False, "error": "Human input text is required."}
        if clean_decision not in {"accepted", "modified", "declined", "deferred", "noted"}:
            return {
                "ok": False,
                "error": f"Invalid decision '{clean_decision}'. Must be one of: accepted, modified, declined, deferred, noted.",
            }
        if not clean_reason:
            return {"ok": False, "error": "A non-empty reason explaining the decision is required."}

        goal_id = None
        p_val = int(priority) if isinstance(priority, (int, float)) and 1 <= priority <= 3 else 2
        diff = f"Human input decision: [{clean_decision}] '{clean_input[:60]}' - {clean_reason[:80]}"

        if clean_decision in {"accepted", "modified"}:
            goal_text = modified_goal if (clean_decision == "modified" and modified_goal) else clean_input
            new_id = f"goal-{self._next_id}"
            self._next_id += 1
            goal_id = new_id
            item = {
                "id": new_id,
                "goal": goal_text,
                "step": goal_text,
                "status": "todo",
                "priority": p_val,
                "source": "human",
                "why": clean_reason,
                "evidence": f"Human input: {clean_input}",
                "next_steps": f"Autonomous execution for {goal_text}",
                "created_cycle": cycle or 1,
                "updated_cycle": cycle or 1,
            }
            if p_val == 1:
                self.items.insert(0, item)
            else:
                self.items.append(item)
            diff += f" -> added {new_id} (source=human, priority={p_val})"

        record = {
            "input": clean_input,
            "decision": clean_decision,
            "reason": clean_reason,
            "priority": p_val if clean_decision in {"accepted", "modified"} else None,
            "goal_id": goal_id,
            "timestamp": now_utc(),
            "cycle": cycle,
        }
        self.human_input_decisions.append(record)
        self.human_input_decisions = self.human_input_decisions[-32:]

        self.logger.log(
            "human_input_decision",
            input=clean_input,
            decision=clean_decision,
            reason=clean_reason,
            priority=p_val if clean_decision in {"accepted", "modified"} else None,
            goal_id=goal_id,
            cycle=cycle,
        )

        self.plan_version += 1
        self._save_atomic(diff=diff, reason=clean_reason, cycle=cycle)
        return {
            "ok": True,
            "decision": clean_decision,
            "input": clean_input,
            "reason": clean_reason,
            "priority": p_val if clean_decision in {"accepted", "modified"} else None,
            "goal_id": goal_id,
            "plan_version": self.plan_version,
            "diff": diff,
            "plan": list(self.items),
        }

    def top_items(self, limit: int = 3, active_plugins: Any = None) -> list[dict[str, Any]]:
        """Return active plan items sorted by priority and position."""
        active = []
        for item in self.items:
            status = str(item.get("status", "todo")).strip().lower()
            if status in COMPLETED_PLAN_STATUSES or status.startswith(SUSPENDED_PLAN_STATUS_PREFIX):
                continue
            plugin = item.get("plugin", "core")
            if active_plugins is not None and plugin != "core" and plugin not in active_plugins:
                continue
            active.append(item)
        # Sort by priority (1 is highest), preserving relative order within priority
        return sorted(active, key=lambda it: int(it.get("priority", 2)))[:limit]

    def retrieval_query(self) -> str:
        """Build retrieval text from top active plan items rather than fixed task string."""
        top = self.top_items(limit=3)
        if not top:
            return "Explore container environment and record discoveries."
        parts: list[str] = []
        for it in top:
            goal = str(it.get("goal") or it.get("step", "")).strip()
            next_steps = str(it.get("next_steps", "")).strip()
            parts.append(f"{goal} {next_steps}".strip())
        return "\n".join(parts)

    def prompt_summary(self, active_plugins: Any = None) -> str:
        """Format the active plan items for inclusion in cycle prompts."""
        active = self.top_items(limit=10, active_plugins=active_plugins)
        lines: list[str] = []
        if not active:
            lines.append("No active plan goals. Use update_plan to add a new exploration or self-improvement goal.")
        else:
            for idx, item in enumerate(active, 1):
                goal = str(item.get("goal") or item.get("step", "")).strip()
                status = str(item.get("status", "todo")).strip()
                priority = item.get("priority", 2)
                item_id = item.get("id", f"goal-{idx}")
                source = str(item.get("source", "agent"))
                next_steps = str(item.get("next_steps", "")).strip()
                evidence = str(item.get("evidence", "")).strip()
                entry = f"{idx}. [{item_id}] (priority={priority}, status={status}, source={source}) {goal}"
                if next_steps:
                    entry += f"\n   Next step: {next_steps}"
                if evidence:
                    entry += f"\n   Evidence: {evidence}"
                lines.append(entry)

        archived = self.get_archived_items(limit=3)
        if archived:
            lines.append("\nRecently archived goals:")
            for arc in archived:
                outcome = arc.get("outcome", "done")
                goal = arc.get("goal", "")
                cycle_num = arc.get("cycle", 1)
                lines.append(f"- [{outcome}] (cycle {cycle_num}) {goal}")

        if self.human_input_decisions:
            lines.append("\nRecent human input decisions:")
            for dec in self.human_input_decisions[-4:]:
                lines.append(f"- [{dec.get('decision')}] \"{dec.get('input', '')[:80]}\": {dec.get('reason', '')[:120]}")

        return "\n".join(lines)

    def hygiene(self, cycle: int, max_stale_cycles: int = 5) -> list[str]:
        """Purge completed/dropped items to archive, mark stale items, and cap size."""
        actions: list[str] = []
        changed = False

        # 1. Purge completed and dropped goals to plan_archive.jsonl
        # Suspended goals are exempt from archive purging.
        purged_records: list[dict[str, Any]] = []
        retained_items: list[dict[str, Any]] = []
        for item in self.items:
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
            self._append_archive(purged_records)
            self.items = retained_items
            actions.append(f"Archived and purged {len(purged_records)} completed/dropped goal(s) to plan_archive.jsonl")
            changed = True

        # 2. Mark stale items (suspended goals are exempt from stale-item pruning)
        for item in self.items:
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
            1 for it in self.items
            if not str(it.get("status", "")).strip().lower().startswith(SUSPENDED_PLAN_STATUS_PREFIX)
        )
        if non_suspended_count > self.max_items or len(self.items) > self.max_items:
            self.items = consolidate_plan_items(self.items, max_items=self.max_items)
            actions.append("Consolidated excess plan items to maintain size bound")
            changed = True

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
        """Suspend all active goals associated with a disabled plugin.
        
        Suspended goals get status 'suspended: plugin disabled' and are kept, never deleted.
        """
        suspended_ids: list[str] = []
        for item in self.items:
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

        if suspended_ids:
            self.plan_version += 1
            diff = f"Suspended goals for disabled plugin '{plugin_name}': {', '.join(suspended_ids)}"
            self._save_atomic(diff=diff, reason=f"Plugin '{plugin_name}' disabled", cycle=cycle)
            self.logger.log("plan_goals_suspended", plugin=plugin_name, goal_ids=suspended_ids)
        return suspended_ids

    def resume_plugin_goals(self, plugin_name: str, cycle: int = 0) -> list[str]:
        """Resume suspended goals when a plugin is re-enabled successfully.
        
        Suspended goals return with a note 're-verify: plugin was disabled'.
        """
        resumed_ids: list[str] = []
        for item in self.items:
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

        if resumed_ids:
            self.plan_version += 1
            diff = f"Resumed goals for re-enabled plugin '{plugin_name}': {', '.join(resumed_ids)}"
            self._save_atomic(diff=diff, reason=f"Plugin '{plugin_name}' re-enabled", cycle=cycle)
            self.logger.log("plan_goals_resumed", plugin=plugin_name, goal_ids=resumed_ids)
        return resumed_ids
