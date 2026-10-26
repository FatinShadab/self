"""Inner tool-round execution: repeated-action guard, plugin vanished check, and tool invocation."""
from __future__ import annotations

import json
from typing import Any

from agent.infra.untrusted import wrap_untrusted
from agent.llm.llm import BudgetExceeded


def execute_tool_round(
    loop: Any,
    tool_uses: list[dict[str, Any]],
    definitions: list[dict[str, Any]],
    seen_tool_actions: set[str],
    cycle_actions: list[dict[str, Any]],
    primary_goal: str = "",
) -> tuple[list[dict[str, Any]], str | None, bool, int, bool]:
    """Execute a batch of tool_use blocks from a model turn.

    Returns:
        (tool_results, stop_reason, remind_outcome, tool_errors, ask_model_followed)
    """
    tool_results: list[dict[str, Any]] = []
    stop_reason: str | None = None
    remind_outcome = False
    tool_error_count = 0
    ask_model_followed = False

    offered_names = {tool["name"] for tool in definitions}

    for tool_use in tool_uses:
        if loop._stopped():
            stop_reason = (
                "broker_panic"
                if (loop.broker is not None and getattr(loop.broker, "in_panic", False))
                else "stop_file"
            )
            break

        name = str(tool_use.get("name", ""))
        arguments = tool_use.get("input", {})
        if not isinstance(arguments, dict):
            arguments = {}

        loop.logger.narrate(loop._tool_narration(name, arguments))
        action_key = json.dumps({"name": name, "arguments": arguments}, ensure_ascii=False, sort_keys=True)

        if action_key in seen_tool_actions:
            observation = {
                "ok": False,
                "error": "This exact tool action already ran earlier in this run; choose a different investigation or finish with a report.",
            }
            loop.logger.log("repeated_tool_action_blocked", tool=name)
        else:
            seen_tool_actions.add(action_key)
            try:
                if loop.plugins is not None and loop.plugins.is_vanished_or_disabled_tool(name):
                    p_name = loop.plugins.get_plugin_for_tool(name)
                    observation = {"ok": False, "error": f"tool no longer available: plugin {p_name} disabled"}
                elif name not in offered_names:
                    observation = {
                        "ok": False,
                        "error": "Tool not offered in this step; use task keywords to retrieve it.",
                    }
                else:
                    observation = loop.tools.execute(name, arguments)
                    if name == "update_plan":
                        act = str(arguments.get("action", "")).lower()
                        dec = str(arguments.get("decision", "")).lower()
                        proj = str(arguments.get("project") or arguments.get("id") or arguments.get("goal") or "").strip()
                        reason_text = str(arguments.get("reason", ""))
                        if act in {"decide_plugin_review", "plugin_project_review"} or (dec in {"continue", "reduce_scope", "abandon"} and proj):
                            reviewed_set = loop.reviewed_thresholds.setdefault(proj, set())
                            thresh = 25 if 25 not in reviewed_set else (50 if 50 not in reviewed_set else 100)
                            reviewed_set.add(thresh)
                            if hasattr(loop.plugin_dev, "record_review_decision"):
                                loop.plugin_dev.record_review_decision(proj, thresh)
                            ledger_summary = loop.tools.cost_ledger.get_summary()
                            pdata = ledger_summary.get("plugin_projects", {}).get(proj, {})
                            loop.logger.log(
                                "plugin_project_review",
                                project=proj,
                                threshold=thresh,
                                decision=dec or "continue",
                                reason=reason_text,
                                tokens_spent=pdata.get("tokens", 0),
                                cycles_spent=pdata.get("cycles", 0),
                                token_estimate=pdata.get("token_estimate", 0),
                                cycle_estimate=pdata.get("cycle_estimate", 0),
                            )
            except BudgetExceeded:
                loop._pause_until_daily_reset()
                if loop._stopped():
                    stop_reason = (
                        "broker_panic"
                        if (loop.broker is not None and getattr(loop.broker, "in_panic", False))
                        else "stop_file"
                    )
                    break
                continue

        is_err = not observation.get("ok", False)
        tool_results.append(
            {
                "type": "tool_result",
                "tool_use_id": tool_use.get("id", ""),
                "content": wrap_untrusted(json.dumps(observation, ensure_ascii=False), source=f"tool:{name}"),
                "is_error": is_err,
            }
        )
        cycle_actions.append({"name": name, "ok": bool(observation.get("ok", False))})
        tool_error_count += int(is_err)

        if name == "create_tool" and observation.get("attempts_remaining") == 0:
            try:
                from agent.runtime.task_reporter import write_human_report
                tool_target = str(arguments.get("name", "custom_tool"))
                write_human_report(
                    workspace=loop.config.workspace,
                    goal=primary_goal or f"Create tool {tool_target}",
                    tool_name="create_tool",
                    error_details=str(observation.get("error", "Three attempts exhausted for tool")),
                    why_explanation=(
                        f"Generation of tool '{tool_target}' exhausted the 3-attempt limit for this session. "
                        "The tool's tests or critic review failed on all attempts."
                    ),
                    suggestions=[
                        f"Review the generated tool files under workspace/tools/{tool_target}/.",
                        "Inspect tool.py and tests to fix any logic or syntax errors.",
                        "When ready, you can unblock or re-add the tool creation task via /goal.",
                    ],
                    logger=loop.logger,
                )
            except Exception:
                pass

        if loop._stopped():
            stop_reason = (
                "broker_panic"
                if (loop.broker is not None and getattr(loop.broker, "in_panic", False))
                else "stop_file"
            )
            break
        if name == "ask_model":
            ask_model_followed = True
            remind_outcome = bool(observation.get("call_id"))
        if loop.has_pending_human_request():
            loop.logger.narrate("A human request was created; pausing immediately.")
            stop_reason = "human_request_pending"
            break

    return tool_results, stop_reason, remind_outcome, tool_error_count, ask_model_followed
