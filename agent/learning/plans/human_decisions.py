"""Human input decision processing and state tracking."""
from __future__ import annotations

from typing import Any

from agent.learning.plans.persistence import now_utc


def process_human_input_decision(
    items: list[dict[str, Any]],
    human_input_decisions: list[dict[str, Any]],
    next_id: int,
    input_text: str,
    decision: str,
    reason: str,
    priority: int = 2,
    modified_goal: str = "",
    cycle: int = 0,
) -> tuple[bool, dict[str, Any], int, str]:
    """Process an autonomous decision on a human input.

    Returns:
        (ok, response_dict_or_error, updated_next_id, diff)
    """
    clean_input = str(input_text).strip()
    clean_decision = str(decision).strip().lower()
    clean_reason = str(reason).strip()
    if not clean_input:
        return False, {"ok": False, "error": "Human input text is required."}, next_id, ""
    if clean_decision not in {"accepted", "modified", "declined", "deferred", "noted"}:
        return (
            False,
            {
                "ok": False,
                "error": f"Invalid decision '{clean_decision}'. Must be one of: accepted, modified, declined, deferred, noted.",
            },
            next_id,
            "",
        )
    if not clean_reason:
        return False, {"ok": False, "error": "A non-empty reason explaining the decision is required."}, next_id, ""

    goal_id = None
    p_val = int(priority) if isinstance(priority, (int, float)) and 1 <= priority <= 3 else 2
    diff = f"Human input decision: [{clean_decision}] '{clean_input[:60]}' - {clean_reason[:80]}"

    if clean_decision in {"accepted", "modified"}:
        goal_text = modified_goal if (clean_decision == "modified" and modified_goal) else clean_input
        new_id = f"goal-{next_id}"
        next_id += 1
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
            items.insert(0, item)
        else:
            items.append(item)
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
    human_input_decisions.append(record)
    del human_input_decisions[:-32]

    response = {
        "ok": True,
        "decision": clean_decision,
        "input": clean_input,
        "reason": clean_reason,
        "priority": p_val if clean_decision in {"accepted", "modified"} else None,
        "goal_id": goal_id,
    }
    return True, response, next_id, diff
