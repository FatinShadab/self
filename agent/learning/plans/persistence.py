"""Atomic persistence and serialization for plan state."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.prompts.system import SEED_STANDING_GOAL


def now_utc() -> str:
    """Return the current UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


def build_seed_goal(seed_task: str = "", default_step: str = "") -> dict[str, Any]:
    """Construct the initial seed goal dictionary."""
    seed_content = seed_task.strip() or default_step.strip() or SEED_STANDING_GOAL
    return {
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


def load_plan_data(plan_path: Path) -> dict[str, Any] | None:
    """Load plan state from disk, normalizing items and extracting max ID."""
    if not plan_path.exists():
        return None
    try:
        data = json.loads(plan_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        plan_version = int(data.get("plan_version", 1))
        human_input_decisions = list(data.get("human_input_decisions", []))
        plugin_project_decisions = list(data.get("plugin_project_decisions", []))
        raw_items = data.get("items", [])
        items: list[dict[str, Any]] = []
        max_id_num = 0
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            normalized = dict(item)
            goal_text = str(normalized.get("goal") or normalized.get("step", "")).strip()
            normalized["goal"] = goal_text
            normalized["step"] = goal_text
            normalized.setdefault("plugin", "core")
            normalized.setdefault("body", "container")
            item_id = str(normalized.get("id", ""))
            match = re.search(r"(\d+)", item_id)
            if match:
                max_id_num = max(max_id_num, int(match.group(1)))
            items.append(normalized)
        next_id = max_id_num + 1 if max_id_num > 0 else len(items) + 1
        return {
            "plan_version": plan_version,
            "human_input_decisions": human_input_decisions,
            "plugin_project_decisions": plugin_project_decisions,
            "items": items,
            "next_id": next_id,
        }
    except (OSError, json.JSONDecodeError):
        return None


def save_plan_atomic(
    plan_path: Path,
    redactor: Any,
    plan_version: int,
    diff: str,
    reason: str,
    items: list[dict[str, Any]],
    human_input_decisions: list[dict[str, Any]],
    plugin_project_decisions: list[dict[str, Any]],
    cycle: int = 0,
) -> None:
    """Atomically persist plan state to disk."""
    safe_items = redactor.value(items) if hasattr(redactor, "value") else items
    safe_human = redactor.value(human_input_decisions) if hasattr(redactor, "value") else human_input_decisions
    safe_projects = redactor.value(plugin_project_decisions) if hasattr(redactor, "value") else plugin_project_decisions
    data = {
        "schema_version": 2,
        "plan_version": plan_version,
        "updated_at": now_utc(),
        "cycle": cycle,
        "last_diff": diff,
        "last_reason": reason,
        "items": safe_items,
        "human_input_decisions": safe_human,
        "plugin_project_decisions": safe_projects,
    }
    temp_path = plan_path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp_path, plan_path)
