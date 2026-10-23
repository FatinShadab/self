"""Autonomous cycle loop execution and state accounting."""
from __future__ import annotations

import json
import time
import uuid
from typing import Any

from agent.infra.untrusted import wrap_untrusted
from agent.llm.llm import BudgetExceeded
from agent.prompts.cycle import (
    RECORD_DELEGATION_OUTCOME_REMINDER,
    build_cycle_helper_prompt,
    build_cycle_user_message,
    build_mid_cycle_human_input_message,
)
from agent.prompts.system import STANDING_GOAL
from agent.runtime.config import RunSummary
from agent.runtime.context_retrieval import WORD, retrieve_context
from agent.runtime.tool_round import execute_tool_round
from agent.tools.base_tools import HELPER_TOOL_NAMES, TOOL_DEFINITIONS
from agent.tools.tool_registry import CREATE_TOOL_DEFINITION


def run_agent_loop(loop: Any) -> RunSummary:
    """Run autonomous cycles until a limit, stop request, or task completion."""
    loop.config.workspace.mkdir(parents=True, exist_ok=True)
    (loop.config.workspace / "memory").mkdir(exist_ok=True)
    (loop.config.workspace / "tools").mkdir(exist_ok=True)
    loop.learning.initialize()
    loop.brain_router.registry.initialize()
    prior_checkpoint = loop.checkpoint.load()
    loop._refresh_learning_runtime()
    active_task = loop.config.task
    if (
        not active_task.strip()
        and loop.config.resume_checkpoint_task
        and prior_checkpoint.get("status") == "running"
    ):
        active_task = str(prior_checkpoint.get("task", ""))
    if loop.config.curriculum and not active_task.strip():
        active_task = loop.learning.propose_curriculum()
        loop.logger.narrate(f"Idle curriculum selected: {active_task}")
    loop.plan_store.initialize(seed_task=active_task or STANDING_GOAL)
    completed_iterations = 0
    seen_tool_actions: set[str] = set()
    last_report = (
        str(prior_checkpoint.get("last_report", "No previous cycle report."))
        if prior_checkpoint.get("status") == "running"
        else "No previous cycle report."
    )
    last_actions: list[dict[str, Any]] = []
    reason = "max_iterations"
    loop.logger.log(
        "run_started",
        goal=STANDING_GOAL,
        max_iterations=loop.config.max_iterations,
        token_budget=loop.config.token_budget,
        daily_token_budget=loop.daily_ledger.cap,
        task=active_task,
        curriculum=loop.config.curriculum,
        max_wall_clock_seconds=loop.config.max_wall_clock_seconds,
        resumed_from_checkpoint=bool(prior_checkpoint),
    )
    started_at = time.monotonic()
    task_id = uuid.uuid4().hex
    ask_model_followed = False
    tool_error_count = 0
    provider_error_count = 0
    if loop.model_decisions is not None:
        loop.model_decisions.start_task(task_id)

    cycle = 1
    primary_goal = active_task or STANDING_GOAL
    while loop.config.max_iterations is None or cycle <= loop.config.max_iterations:
        if not loop._wait_while_paused():
            reason = "stop_file"
            break
        if (
            loop.config.max_wall_clock_seconds is not None
            and time.monotonic() - started_at >= loop.config.max_wall_clock_seconds
        ):
            loop.logger.narrate("Run wall-clock budget reached; saving checkpoint and stopping cleanly.")
            reason = "wall_clock_budget"
            break
        if loop._stopped():
            reason = "stop_file"
            break
        if loop.human_request.exists():
            loop.logger.narrate("A human request is pending; waiting for it to be resolved.")
            loop.logger.log("run_stopped", reason="human_request_pending")
            reason = "human_request_pending"
            break

        loop.tools.current_cycle = cycle
        if loop.plugins is not None:
            loop.plugins.sync_at_cycle_boundary(
                plan_store=loop.plan_store,
                learning_store=loop.learning,
            )
            for p_name, active_p in loop.plugins.active_plugins.items():
                for seed in active_p.manifest.starting_goal_seeds:
                    existing_goals = [item.get("goal") for item in loop.plan_store.items]
                    if seed not in existing_goals:
                        loop.plan_store.update_plan(
                            action="add",
                            goal=seed,
                            priority=2,
                            reason=f"Plugin {p_name} starting seed",
                            cycle=cycle,
                            source=f"plugin:{p_name}",
                        )
        active_plugins_set = set(loop.plugins.active_plugins.keys()) if loop.plugins else set()
        top_items = loop.plan_store.top_items(limit=3, active_plugins=active_plugins_set)
        primary_goal = top_items[0]["goal"] if top_items else (active_task or STANDING_GOAL)
        plan_query = loop.plan_store.retrieval_query()
        loop.logger.narrate(f"Cycle {cycle}: retrieving relevant tools and memories for plan...")
        query = f"{plan_query}\nPrevious report: {last_report}"
        human_messages = loop.config.input_provider() if loop.config.input_provider else []
        if cycle == 1 and loop.config.initial_context.strip():
            human_messages = [loop.config.initial_context.strip(), *human_messages]
        human_context = "\n".join(f"- {loop.logger.redactor.text(message)}" for message in human_messages)
        if loop.config.retrieve_memories:
            legacy_context = retrieve_context(loop.config.workspace, query, loop.logger)
            context = (
                "## Self notes\n"
                + wrap_untrusted(loop.learning.load_notes(active_plugins=active_plugins_set), source="notes")
                + "\n\n## Verified environment map\n"
                + wrap_untrusted(
                    loop.learning.map_context(active_plugins=active_plugins_set),
                    source="environment_map",
                )
                + "\n\n## Relevant persistent memories\n"
                + wrap_untrusted(
                    loop.learning.retrieve_memories(query, active_plugins=active_plugins_set),
                    source="memories",
                )
                + "\n\n## Legacy lessons\n"
                + wrap_untrusted(legacy_context, source="legacy_context")
            )
        else:
            context = "This focused test has no prior memories."
        helper_prompt = ""
        if cycle == 1 and loop.model_registry is not None:
            needing = loop.model_registry.helpers_needing_evaluation()
            helper_prompt = build_cycle_helper_prompt(needing)
        failure_context = loop.registry.recent_failure_context()
        plan_summary = loop.plan_store.prompt_summary(active_plugins=active_plugins_set)
        actions_summary = loop._format_actions(last_actions)
        plugin_notes = (
            loop.plugins.get_goal_notes_prompt().strip()
            if (loop.plugins and loop.plugins.get_goal_notes_prompt())
            else ""
        )
        plugin_section = (
            f"{wrap_untrusted(plugin_notes, source='plugins:notes')}\n\n" if plugin_notes else ""
        )
        plugin_projects_section = loop._check_active_plugin_projects(cycle)
        messages: list[dict[str, Any]] = [
            {
                "role": "user",
                "content": build_cycle_user_message(
                    cycle=cycle,
                    helper_prompt=helper_prompt,
                    plan_version=loop.plan_store.plan_version,
                    plan_summary=plan_summary,
                    primary_goal=primary_goal,
                    last_report=last_report,
                    actions_summary=actions_summary,
                    context=context,
                    plugin_section=plugin_section,
                    plugin_projects_section=plugin_projects_section,
                    human_context=human_context,
                    failure_context=failure_context,
                ),
            }
        ]
        cycle_report = ""
        cycle_actions: list[dict[str, Any]] = []
        loop.checkpoint.save(
            status="running",
            task=primary_goal,
            cycle=cycle,
            last_report=last_report,
            tokens_used=loop.llm.tokens_used,
        )
        plan_version_before = loop.plan_store.plan_version

        # Inner tool loop
        while True:
            if not loop._wait_while_paused():
                reason = "stop_file"
                break
            if loop._stopped():
                reason = "stop_file"
                break
            if (
                loop.config.max_wall_clock_seconds is not None
                and time.monotonic() - started_at >= loop.config.max_wall_clock_seconds
            ):
                reason = "wall_clock_budget"
                break
            new_human_messages = loop.config.input_provider() if loop.config.input_provider else []
            if new_human_messages:
                messages.append(
                    {
                        "role": "user",
                        "content": build_mid_cycle_human_input_message(
                            [loop.logger.redactor.text(message) for message in new_human_messages]
                        ),
                    }
                )
            loop._refresh_learning_runtime()
            selected = loop.registry.retrieve(
                f"{plan_query}\n{cycle_report or last_report}",
                loop.config.top_k_tools,
                active_plugins=active_plugins_set,
            )
            base = [
                tool
                for tool in TOOL_DEFINITIONS
                if (loop.config.base_tool_names is None or tool["name"] in loop.config.base_tool_names)
                and (loop.helper_mode or tool["name"] not in HELPER_TOOL_NAMES)
            ]
            plugin_tools = loop.plugins.get_active_tool_definitions() if loop.plugins else []
            opencode_tools = getattr(loop.tools, "get_opencode_tool_definitions", lambda: [])()
            definitions = base + [CREATE_TOOL_DEFINITION] + selected + plugin_tools + opencode_tools
            try:
                result = loop.llm.call(
                    system=loop._system_prompt(),
                    messages=messages,
                    tools=definitions,
                    max_tokens=loop.max_tokens_per_call,
                )
            except BudgetExceeded:
                loop._pause_until_daily_reset()
                if loop._stopped():
                    reason = "stop_file"
                    break
                continue
            except Exception as exc:
                provider_error_count += 1
                loop.logger.log("run_failed", error_type=type(exc).__name__, provider_error=True)
                loop.logger.narrate(
                    f"The AI provider failed with {type(exc).__name__}. I paused this session safely and will retry automatically."
                )
                reason = "provider_error"
                break

            safe_content = json.loads(loop.logger.redactor.known(json.dumps(result.content)))
            report_text = loop._narrate_content(safe_content)
            if report_text:
                cycle_report = loop.logger.redactor.text(report_text)
            tool_uses = [block for block in safe_content if block.get("type") == "tool_use"]
            if not tool_uses:
                break

            messages.append({"role": "assistant", "content": safe_content})

            tool_results, stop_reason, remind_outcome, round_errors, asked = execute_tool_round(
                loop=loop,
                tool_uses=tool_uses,
                definitions=definitions,
                seen_tool_actions=seen_tool_actions,
                cycle_actions=cycle_actions,
            )
            tool_error_count += round_errors
            if asked:
                ask_model_followed = True

            if stop_reason is not None:
                reason = stop_reason
                break

            messages.append({"role": "user", "content": tool_results})
            if remind_outcome:
                messages.append(
                    {
                        "role": "user",
                        "content": RECORD_DELEGATION_OUTCOME_REMINDER,
                    }
                )

        if reason in {
            "stop_file",
            "token_budget",
            "human_request_pending",
            "wall_clock_budget",
            "provider_error",
            "broker_panic",
            "stop_watcher",
        }:
            break
        completed_iterations += 1
        last_report = cycle_report or "Cycle completed without a textual report."
        loop.logger.log(
            "cycle_completed",
            cycle=cycle,
            tokens_used=loop.llm.tokens_used,
            report=last_report,
            actions=cycle_actions,
        )
        if loop.plan_store.plan_version == plan_version_before:
            unchanged_reason = (
                cycle_report[:300]
                if cycle_report and cycle_report != "Cycle completed without a textual report."
                else f"Plan remains valid; continuing progress on primary goal: {primary_goal}"
            )
            loop.plan_store.record_unchanged(
                cycle=cycle,
                reason=unchanged_reason,
                evidence=f"Cycle {cycle} observations and report",
            )
        loop.plan_store.hygiene(cycle=cycle)
        last_actions = list(cycle_actions)
        loop.learning.record_cycle(primary_goal, cycle, cycle_actions, last_report)
        loop.checkpoint.save(
            status="running",
            task=primary_goal,
            cycle=cycle + 1,
            last_report=last_report,
            tokens_used=loop.llm.tokens_used,
        )
        if loop.config.on_cycle is not None:
            loop.config.on_cycle(cycle, last_report, loop.llm.tokens_used)

        if loop.human_request.exists():
            loop.logger.narrate("A human request was created; pausing further cycles.")
            reason = "human_request_pending"
            break

        cycle += 1

    loop.logger.log(
        "run_completed",
        iterations=completed_iterations,
        tokens_used=loop.llm.tokens_used,
        reason=reason,
    )
    if loop.model_decisions is not None:
        loop.model_decisions.record_task_observation(task_id, primary_goal, ask_model_followed)
        loop.model_decisions.record_task_outcomes(
            task_id,
            completed=completed_iterations > 0 and reason not in {"provider_error", "stop_file"},
            iterations=completed_iterations,
            tool_errors=tool_error_count,
            provider_errors=provider_error_count + loop.model_decisions.task_provider_errors(),
        )
    loop.checkpoint.save(
        status="completed",
        task=primary_goal,
        completed_iterations=completed_iterations,
        last_report=last_report,
        tokens_used=loop.llm.tokens_used,
        reason=reason,
    )
    if completed_iterations == 0:
        loop.learning.append_memory(
            f"Run task: {primary_goal}",
            reason,
            "The run stopped before completing a cycle; inspect the action log and resume when appropriate.",
            list(WORD.findall(primary_goal)),
        )
    loop.logger.narrate(
        f"Run finished after {completed_iterations} cycle(s), using {loop.llm.tokens_used} tokens; reason: {reason}."
    )
    return RunSummary(completed_iterations, loop.llm.tokens_used, reason)
