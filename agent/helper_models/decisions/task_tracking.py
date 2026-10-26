"""Task-level outcome recording, tool outcomes, and delegation verification."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any

from agent.helper_models.model_outcomes import SELF_REPORTED_USEFULNESS
from agent.infra.file_lock import locked_file


USEFULNESS_ALIASES: dict[str, str] = {
    "useful": "used",
    "helpful": "used",
    "success": "used",
    "not_useful": "not_used",
    "unhelpful": "not_used",
    "fail": "not_used",
    "failed": "wrong",
    "incorrect": "wrong",
    "partial": "partly_used",
    "partially": "partly_used",
}


def record_delegation_outcome(
    decisions: Any,
    call_id: str,
    usefulness: str,
    note: str,
) -> dict[str, Any]:
    """Persist the observed result of a helper-model delegation."""
    norm_usefulness = USEFULNESS_ALIASES.get(str(usefulness).strip().lower(), str(usefulness).strip().lower())
    if norm_usefulness not in SELF_REPORTED_USEFULNESS:
        raise ValueError(
            f"Invalid delegation usefulness '{usefulness}'. Expected one of: {sorted(SELF_REPORTED_USEFULNESS)}"
        )
    usefulness = norm_usefulness
    if not isinstance(note, str) or len(note) > 1_000:
        raise ValueError("Delegation note exceeds its size limit")
    target = next((row for row in decisions.last_decisions(limit=None) if row.get("call_id") == call_id), None)
    if target is None or target.get("source") != "agent_tool":
        raise ValueError("Unknown ask_model call id")
    decisions.outcomes.append(
        call_id,
        target["model"],
        "agent_tool",
        "usefulness",
        usefulness,
        "self_reported",
        session_id=target["session_id"],
        task_id=target.get("task_id"),
    )
    decisions.outcomes.append(
        call_id,
        target["model"],
        "agent_tool",
        "note",
        note,
        "self_reported",
        session_id=target["session_id"],
        task_id=target.get("task_id"),
    )
    return {"ok": True, "call_id": call_id, "usefulness": usefulness}


def record_task_outcomes(
    decisions: Any,
    task_id: str,
    *,
    completed: bool,
    iterations: int,
    tool_errors: int,
    provider_errors: int,
) -> None:
    """Persist task-level outcome signals after a tracked run."""
    helper_used = bool(decisions.successful_helper_calls)
    helper_used |= any(
        model != decisions.registry.base_model and source.startswith("checkpoint:")
        for _, model, source in decisions.task_calls
    )
    targets = decisions.task_calls or [(task_id, decisions.registry.base_model, "task_baseline")]
    if not helper_used:
        targets = [*decisions.task_calls, (task_id, decisions.registry.base_model, "task_baseline")]
    signals = {
        "cycle_completed": completed,
        "iterations_to_complete": iterations,
        "tool_call_error_count": tool_errors,
        "provider_errors": provider_errors,
        "used_any_helper": helper_used,
    }
    for call_id, model, source in targets:
        for signal, value in signals.items():
            decisions.outcomes.append(
                call_id,
                model,
                source,
                signal,
                value,
                "objective",
                session_id=decisions.session_id,
                task_id=task_id,
            )


def task_provider_errors(decisions: Any) -> int:
    """Return provider errors recorded for an active task."""
    ids = {call_id for call_id, _, _ in decisions.task_calls}
    return decisions.extra_provider_errors + sum(
        1
        for row in decisions.last_decisions(limit=None)
        if row.get("call_id") in ids
        for attempt in row.get("attempts", [])
        if attempt.get("error_type") and attempt["error_type"] != "BudgetExceeded"
    )


def record_tool_outcome(
    decisions: Any,
    *,
    tool_name: str,
    attempt: int,
    critic_call_id: str | None,
    critic_model: str,
    critic_approved: bool | None,
    tests_passed: bool | None,
    registered: bool,
) -> None:
    """Persist an outcome signal for a generated tool."""
    if tests_passed is False or critic_approved is False:
        decisions._cached_choices.clear()
    targets = [
        (call_id, model, source)
        for call_id, model, source in decisions.task_calls
        if source == "agent_tool" and call_id in decisions.successful_helper_calls
    ]
    if critic_call_id:
        targets.append((critic_call_id, critic_model, "checkpoint:create_tool_critic"))
    signals = {
        "tool_first_try_test_pass": tests_passed if attempt == 1 else None,
        "tool_attempts_before_registration": attempt if registered else None,
        "critic_model_used": critic_model,
        "critic_verdict_approved": critic_approved,
        "tool_test_passed": tests_passed,
        "tool_registration_success": registered,
        "critic_flagged_but_tests_passed": (
            tests_passed is True if critic_approved is False and tests_passed is not None else None
        ),
        "critic_approved_but_tests_failed": (
            tests_passed is False if critic_approved is True and tests_passed is not None else None
        ),
    }
    for call_id, model, source in targets:
        for signal, value in signals.items():
            if value is not None:
                decisions.outcomes.append(
                    call_id,
                    model,
                    source,
                    signal,
                    value,
                    "objective",
                    session_id=decisions.session_id,
                    task_id=decisions.active_task_id,
                    tool_name=tool_name,
                    attempt=attempt,
                )


def record_task_observation(
    decisions: Any,
    task_id: str,
    task: str,
    ask_model_followed: bool,
) -> None:
    """Record an objective observation for delegated or baseline work."""
    record = {
        "call_id": task_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_id": decisions.session_id,
        "model": decisions.registry.base_model,
        "task_type": str(task)[:120],
        "reason": "",
        "expected_benefit": "",
        "source": "task_observation",
        "status": "completed",
        "ask_model_followed": ask_model_followed,
        "latency_ms": 0,
        "tokens": 0,
        "outcome": None,
    }
    decisions.task_path.parent.mkdir(parents=True, exist_ok=True)
    with locked_file(decisions.lock_path):
        with decisions.task_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(decisions.logger.redactor.value(record), ensure_ascii=False) + "\n")


__all__ = [
    "record_delegation_outcome",
    "record_task_outcomes",
    "task_provider_errors",
    "record_tool_outcome",
    "record_task_observation",
]
