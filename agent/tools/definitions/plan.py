"""Plan management and environment mapping tool schemas."""
from __future__ import annotations

from typing import Any

UPDATE_ENVIRONMENT_MAP_DEFINITION: dict[str, Any] = {
        "name": "update_environment_map",
        "description": "Record verified environment observations in persistent state. Each entry needs key, value, confidence (unknown/low/medium/high), and optional evidence. Do this after observing OS, packages, CPU, RAM, disk, network, limits, or tools.",
        "input_schema": {
            "type": "object",
            "properties": {
                "entries": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "key": {"type": "string"},
                            "value": {},
                            "confidence": {"type": "string", "enum": ["unknown", "low", "medium", "high"]},
                            "evidence": {"type": "string"},
                        },
                        "required": ["key", "value", "confidence"],
                    },
                },
            },
            "required": ["entries"],
        },
    }

READ_PLAN_DEFINITION: dict[str, Any] = {
        "name": "read_plan",
        "description": "Read the current persistent plan, including all goals, status, evidence, next steps, and plan version.",
        "input_schema": {
            "type": "object",
            "properties": {
                "include_history": {
                    "type": "boolean",
                    "description": "If true, include historical completed and dropped goals from plan archive.",
                },
            },
            "additionalProperties": False,
        },
    }

UPDATE_PLAN_DEFINITION: dict[str, Any] = {
        "name": "update_plan",
        "description": (
            "Update the persistent plan. Requires an action ('add', 'edit', 'drop', 'mark_done', 'reorder', 'unchanged', 'decide_human_input') "
            "and a required 'reason' citing evidence. Use this to track goals, mark progress, evaluate human input with decisions, "
            "add self-improvement goals (e.g. 'improve tool X', 'evaluate model Y', 'fix a failing tool'), or adjust next steps."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["add", "edit", "drop", "mark_done", "reorder", "unchanged", "decide_human_input"],
                    "description": "Plan modification action to perform.",
                },
                "reason": {
                    "type": "string",
                    "description": "Required reason citing evidence (observations, tool results, errors) for this change.",
                },
                "goal": {"type": "string", "description": "Goal or step description (for add/edit)."},
                "id": {"type": "string", "description": "Target goal id (e.g. 'goal-1') to edit, drop, or mark done."},
                "evidence": {"type": "string", "description": "Evidence reference or observation supporting this update."},
                "next_steps": {"type": "string", "description": "Specific actionable next steps for this goal."},
                "priority": {"type": "integer", "description": "Priority (1=high, 2=medium, 3=low).", "default": 2},
                "status": {
                    "type": "string",
                    "enum": ["todo", "in_progress", "done", "dropped", "blocked", "stale"],
                    "description": "Status for the goal (for edit).",
                },
                "order": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of goal IDs in new order (for reorder).",
                },
                "input": {
                    "type": "string",
                    "description": "Human input text being evaluated (for decide_human_input).",
                },
                "decision": {
                    "type": "string",
                    "enum": ["accepted", "modified", "declined", "deferred", "noted"],
                    "description": "Decision on human input (for decide_human_input).",
                },
                "source": {
                    "type": "string",
                    "enum": ["agent", "human"],
                    "description": "Origin of the plan goal (default 'agent', or 'human' when adopting human input).",
                },
            },
            "required": ["action", "reason"],
        },
    }
