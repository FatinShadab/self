"""Session execution lifecycle, loop orchestration, and post-session handoffs."""
from __future__ import annotations

import re
from typing import Any

from agent.infra.file_lock import locked_file
from agent.llm.llm import LLMClient
from agent.prompts.reflection import build_startup_eval_instructions
from agent.prompts.system import ORIENTATION_TASK
from agent.runtime.loop import AgentConfig, AgentLoop, STANDING_GOAL
from agent.session.handoff_builder import _read_json
from agent.session.plan_recovery import normalized_plan, visible_plan_items
from agent.tools.base_tools import ToolRunner


def _compute_end_reason(reason: str, stop_requested: bool) -> str:
    if reason == "broker_panic":
        return "broker_panic"
    if reason in {"stop_file", "stop_watcher"}:
        return "stop_file"
    if stop_requested or reason == "max_iterations":
        return "clean_shutdown"
    if reason in {"token_budget", "wall_clock_budget"}:
        return "budget_exhausted"
    if reason == "provider_error":
        return "provider_error"
    if reason == "no_progress":
        return "needs_attention"
    return "clean_shutdown"


def run_session_with_lock(coordinator: Any) -> Any:
    """Run the current wake session under an advisory shared evaluation lock."""
    with locked_file(coordinator.workspace / "state" / "eval_session.lock", shared=True):
        return run_session(coordinator)


def run_session(coordinator: Any) -> Any:
    """Execute the core wake session lifecycle around the autonomous agent loop."""
    greeting = coordinator.boot() if not coordinator._session_info else ""
    if (coordinator.workspace / "STOP").exists():
        return None
    if coordinator.max_iterations != 0:
        coordinator.revise_plan()
    startup_context = ""
    if coordinator._llm is None:
        coordinator._llm = LLMClient(coordinator.logger)
    model_reg = getattr(coordinator._llm, "model_registry", None)
    needing_eval = model_reg.helpers_needing_evaluation() if model_reg is not None else []
    if needing_eval:
        coordinator.logger.narrate(f"Startup priority: helper models needing evaluation: {', '.join(needing_eval)}")
        eval_instructions = build_startup_eval_instructions(needing_eval)
        startup_context = eval_instructions

    package_entry = coordinator.learning._load_map().get("entries", {}).get("packages", {})
    package_value = package_entry.get("value")
    if package_value is None or package_value == "not yet inventoried":
        coordinator.logger.narrate("Startup priority: I will immediately inventory installed Python packages before broader exploration.")
        package_instructions = (
            coordinator.body.initial_orientation_task()
            if coordinator.body and hasattr(coordinator.body, "initial_orientation_task")
            else ORIENTATION_TASK
        )
        if startup_context:
            startup_context = f"{startup_context}\n\n{package_instructions}"
        else:
            startup_context = package_instructions

    checkpoint = _read_json(coordinator.workspace / "state" / "run_checkpoint.json")
    initial_orientation = (
        coordinator.body.initial_orientation_task()
        if coordinator.body and hasattr(coordinator.body, "initial_orientation_task")
        else ORIENTATION_TASK
    )
    initial_task_prefix = initial_orientation[:40]
    stale_startup_task = (
        (bool(initial_task_prefix) and str(checkpoint.get("task", "")).startswith(initial_task_prefix))
        or str(checkpoint.get("task", "")).startswith("Helper models needing evaluation")
    )

    resume_checkpoint_task = not stale_startup_task
    runner = ToolRunner(coordinator.logger, coordinator.workspace, body=coordinator.body, broker=coordinator.broker)
    runner.identity = coordinator.identity
    runner.plan_store = coordinator.plan_store
    runner.plugins = coordinator.plugins
    loop = AgentLoop(
        AgentConfig(
            workspace=coordinator.workspace,
            max_iterations=coordinator.max_iterations,
            token_budget=coordinator.token_budget,
            max_wall_clock_seconds=coordinator.max_wall_clock_seconds,
            initial_context=startup_context,
            resume_checkpoint_task=resume_checkpoint_task,
            input_provider=coordinator.inbox.consume,
            pause_provider=coordinator.paused.is_set,
            on_cycle=coordinator._checkpoint_cycle,
            identity_context_provider=coordinator.identity.prompt_context,
            daily_ledger=coordinator.daily_ledger,
            session_id=coordinator.status.session_id,
            body=coordinator.body,
            plugins=coordinator.plugins,
            broker=coordinator.broker,
            audit_trail=coordinator.audit_trail,
            stop_watcher=coordinator.stop_watcher,
        ),
        coordinator.logger,
        coordinator._llm,
        runner,
    )
    coordinator.status.active_model = getattr(loop.llm.client, "model", "unknown")
    coordinator.status.active_provider = getattr(loop.llm.client, "provider", "unknown")
    try:
        summary = loop.run()
        if summary.iterations == 0:
            end_reason = _compute_end_reason(summary.reason, coordinator.stop_requested)
            coordinator.sessions.finish(
                coordinator.status.session_id,
                coordinator.handoff,
                0,
                summary.tokens_used,
                end_reason,
            )
            coordinator.logger.log(
                "zero_cycle_session_preserved",
                session_id=coordinator.status.session_id,
                end_reason=end_reason,
            )
            coordinator._session_info = {}
            return summary

        session_attempt = startup_context or STANDING_GOAL
        if summary.reason == "no_progress":
            reflection = {
                "attempted": session_attempt,
                "achieved": "No new durable progress; repeated cycle reports while plan and map writes were unavailable.",
                "plan": loop.plan_store.items or coordinator.plan,
                "summary": "Paused after repeated results; review permissions or choose another goal.",
                "failures_and_lessons": [],
            }
        elif coordinator.stop_requested or summary.reason in {"stop_file", "stop_watcher", "broker_panic"}:
            reflection = {
                "attempted": session_attempt,
                "achieved": coordinator.handoff.get("summary", "The session stopped at a safe boundary."),
                "plan": loop.plan_store.items or coordinator.plan,
                "summary": coordinator.handoff.get("summary", "Run stopped at a safe boundary."),
                "failures_and_lessons": [],
            }
        else:
            reflection = coordinator._reflection(
                "shutdown reflection",
                f"Loop ended with reason={summary.reason}; intended session work: {session_attempt}; last report={coordinator.handoff.get('summary', '')}",
            )
        agent_plan = loop.plan_store.items if loop.plan_store and loop.plan_store.items else []
        coordinator.plan = normalized_plan(list(agent_plan or reflection.get("plan") or coordinator.plan))
        coordinator._recover_budget_blocked_plan()
        achieved = str(reflection.get("achieved") or reflection.get("summary") or "No textual achievement report was returned.")
        achieved = re.sub(r"Session complete after \d+ cycle\(s\)\.?\s*", "", achieved).strip() or "Session work completed without an LLM reflection."
        attempted = str(reflection.get("attempted") or session_attempt)
        active_plan = visible_plan_items(coordinator.plan)
        next_plan = "; ".join(
            str(item.get("goal") or item.get("step", "")).strip()
            for item in active_plan
            if (item.get("goal") or item.get("step"))
        ) or "No active plan items remain; the next wake will review the environment again."
        session_report = (
            f"Session complete after {summary.iterations} cycle(s).\n"
            f"Trying to do: {attempted}\n"
            f"Achieved: {achieved}\n"
            f"Updated plan: {next_plan}"
        )
        coordinator.logger.log("session_summary", message=session_report)
        coordinator.identity.reflect_session(
            coordinator.status.session_id,
            coordinator._session_start,
            achieved,
        )
        handoff = coordinator._make_handoff(session_report, summary.reason)
        handoff["failures_and_lessons"] = list(handoff["failures_and_lessons"]) + list(reflection.get("failures_and_lessons", []))
        end_reason = _compute_end_reason(summary.reason, coordinator.stop_requested)
        coordinator.sessions.finish(
            coordinator.status.session_id,
            handoff,
            summary.iterations,
            summary.tokens_used,
            end_reason,
        )
        coordinator._session_info = {}
        return summary
    except Exception:
        coordinator.logger.log("session_unexpected_exception")
        raise


__all__ = [
    "run_session_with_lock",
    "run_session",
]
