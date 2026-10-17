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

WORD = re.compile(r"[a-zA-Z0-9_.-]{2,}")


def now_utc() -> str:
    """Return the current UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


def visible_plan_items(plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return only active plan items for live display and execution."""
    return [
        item for item in plan
        if isinstance(item, dict)
        and str(item.get("status", "todo")).strip().lower() not in COMPLETED_PLAN_STATUSES
    ]


def consolidate_plan_items(plan: list[dict[str, Any]], max_items: int = 8) -> list[dict[str, Any]]:
    """Cap plan size by consolidating older or lower-priority items rather than truncating."""
    if len(plan) <= max_items:
        return plan

    active: list[dict[str, Any]] = []
    completed: list[dict[str, Any]] = []

    for item in plan:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status", "todo")).strip().lower()
        if status in COMPLETED_PLAN_STATUSES:
            completed.append(item)
        else:
            active.append(item)

    # If active items alone fit, keep all active items and consolidate completed items
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
            }
            return active + [consolidated_item]
        return active

    # If active items alone exceed max_items, preserve top priority/early active items
    # and consolidate remaining lower-priority active items into a background objective
    keep_count = max_items - 1
    preserved = active[:keep_count]
    consolidated_active = active[keep_count:]

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
        "created_cycle": active[0].get("created_cycle", 1),
        "updated_cycle": active[0].get("updated_cycle", 1),
    }

    return preserved + [consolidated_item]


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
        self.max_items = max(4, max_items)
        self.plan_version = 1
        self.items: list[dict[str, Any]] = []
        self._next_id = 1

    def initialize(self, seed_task: str = "", default_step: str = "") -> None:
        """Load durable plan, or seed an initial plan goal if empty."""
        self.state_dir.mkdir(parents=True, exist_ok=True)
        loaded = self.load()
        if loaded:
            return

        seed_content = seed_task.strip() or default_step.strip() or "Inspect current state and verify one environment fact."
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
        }
        self.items = [initial_goal]
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
            "schema_version": 1,
            "plan_version": self.plan_version,
            "updated_at": now_utc(),
            "cycle": cycle,
            "last_diff": diff,
            "last_reason": reason,
            "items": self.logger.redactor.value(self.items),
        }
        temp_path = self.plan_path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temp_path, self.plan_path)

    def read_plan(self) -> dict[str, Any]:
        """Tool implementation for reading current plan state."""
        active = self.top_items(limit=100)
        return {
            "ok": True,
            "plan_version": self.plan_version,
            "total_goals": len(self.items),
            "active_goals": len(active),
            "top_goal": active[0] if active else None,
            "items": list(self.items),
        }

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
            )
            return {
                "ok": True,
                "action": "unchanged",
                "plan_version": self.plan_version,
                "diff": "Plan unchanged",
                "reason": clean_reason,
                "plan": list(self.items),
            }

        if action == "add":
            goal_text = str(goal or extra.get("step", "")).strip()
            if not goal_text:
                return {"ok": False, "error": "Goal text is required for action 'add'."}
            new_id = f"goal-{self._next_id}"
            self._next_id += 1
            item = {
                "id": new_id,
                "goal": goal_text,
                "step": goal_text,
                "status": status if status in ACTIVE_PLAN_STATUSES else "todo",
                "priority": int(priority) if isinstance(priority, (int, float)) else 2,
                "why": extra.get("why") or clean_reason,
                "evidence": evidence_ref,
                "next_steps": next_steps.strip() or f"Execute investigation for {goal_text}",
                "created_cycle": cycle or 1,
                "updated_cycle": cycle or 1,
            }
            # Add to top if high priority (priority 1), else append
            if item["priority"] == 1:
                self.items.insert(0, item)
            else:
                self.items.append(item)
            diff = f"Added {new_id}: '{goal_text}' (priority={item['priority']}, status={item['status']})"

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

        else:
            return {"ok": False, "error": f"Unknown plan action '{action}'. Valid actions: add, edit, drop, mark_done, reorder, unchanged."}

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

    def record_unchanged(self, cycle: int, reason: str, evidence: str = "") -> None:
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
        )

    def top_items(self, limit: int = 3) -> list[dict[str, Any]]:
        """Return active plan items sorted by priority and position."""
        active = [
            item for item in self.items
            if str(item.get("status", "todo")).strip().lower() not in COMPLETED_PLAN_STATUSES
        ]
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

    def prompt_summary(self) -> str:
        """Format the active plan items for inclusion in cycle prompts."""
        active = self.top_items(limit=10)
        if not active:
            return "No active plan goals. Use update_plan to add a new exploration or self-improvement goal."
        lines: list[str] = []
        for idx, item in enumerate(active, 1):
            goal = str(item.get("goal") or item.get("step", "")).strip()
            status = str(item.get("status", "todo")).strip()
            priority = item.get("priority", 2)
            item_id = item.get("id", f"goal-{idx}")
            next_steps = str(item.get("next_steps", "")).strip()
            evidence = str(item.get("evidence", "")).strip()
            entry = f"{idx}. [{item_id}] (priority={priority}, status={status}) {goal}"
            if next_steps:
                entry += f"\n   Next step: {next_steps}"
            if evidence:
                entry += f"\n   Evidence: {evidence}"
            lines.append(entry)
        return "\n".join(lines)

    def hygiene(self, cycle: int, max_stale_cycles: int = 5) -> list[str]:
        """Mark or drop stale items with no progress and cap size by consolidation."""
        actions: list[str] = []
        changed = False

        for item in self.items:
            status = str(item.get("status", "todo")).strip().lower()
            if status in COMPLETED_PLAN_STATUSES:
                continue
            updated = int(item.get("updated_cycle") or item.get("created_cycle") or 1)
            if cycle - updated >= max_stale_cycles:
                if status != "stale":
                    item["status"] = "stale"
                    item["updated_cycle"] = cycle
                    actions.append(f"Marked stale {item.get('id')}: '{item.get('goal', '')}' (no progress for {cycle - updated} cycles)")
                    changed = True

        if len(self.items) > self.max_items:
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
