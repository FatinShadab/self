"""SELF cycle prompts."""
from __future__ import annotations

from typing import Any

RECORD_DELEGATION_OUTCOME_REMINDER = (
    "If useful, call record_delegation_outcome once for the ask_model call_id. Reporting is optional; judge the result yourself."
)

HELPER_MODELS_AVAILABLE_PROMPT = (
    "Helper models are available. Consider ask_model for sub-tasks it fits, or continue alone.\n\n"
)


def build_helper_eval_hint(needing: list[str] | tuple[str, ...]) -> str:
    """Render the helper-model evaluation instructions for cycle 1."""
    if not needing:
        return ""
    return (
        f"Helper models needing evaluation before other work: {', '.join(needing)}.\n"
        "Evaluate each using exact names from list_models: first probe_model, then research_model, "
        "then record_model_assessment with the probe id as evidence. Write each assessment as one compact, "
        "comparable line with total/active params and context window first (or 'unknown' when not known), "
        "followed by 'status ok', then measured_stats call latency (total / calls) and probe-only latency labeled separately "
        "(e.g. '550B/55B, ctx 262k+, status ok, call latency ~2.1s, probe latency ~1.8s, strong reasoning; probe 4/4 passed') "
        "and explicitly state the origin of each fact (web vs model_knowledge).\n\n"
    )


def build_cycle_helper_prompt(needing: list[str] | tuple[str, ...] | None = None) -> str:
    """Render the full helper-model section for cycle 1."""
    eval_hint = build_helper_eval_hint(needing or []) if needing else ""
    return HELPER_MODELS_AVAILABLE_PROMPT + eval_hint


def build_mid_cycle_human_input_message(messages: list[str]) -> str:
    """Build the mid-cycle user message when new human inputs arrive during execution."""
    return (
        "New human inputs arrived while you were working. Weigh them as inputs to consider in your next decision "
        "(decide whether to accept, modify, decline, or defer with an honest explanation):\n"
        + "\n".join(f"- {message}" for message in messages)
    )


def build_active_plugin_project_part(
    name: str,
    milestone: str,
    spent_tokens: int,
    spent_cycles: int,
    tokens_est: Any,
    cycles_est: Any,
    pending_stop_loss_pct: int | None = None,
) -> str:
    """Render the active plugin project summary block and optional stop-loss review."""
    part = [
        f"## Active Plugin Project: {name}",
        f"- Current milestone: {milestone}",
        f"- Measured spend: {spent_tokens} tokens, {spent_cycles} cycles (estimate: {tokens_est} tokens, {cycles_est} cycles).",
        "- Normal exploration balance nudge: Normal exploration must continue while developing a plugin. Allocate at least ~1 in 3 cycles to other plan goals unless you record an explicit reason in your plan update explaining why consecutive plugin cycles are required.",
    ]
    if pending_stop_loss_pct is not None:
        part.append(
            f"\n[MANDATORY STOP-LOSS REVIEW TRIGGERED at {pending_stop_loss_pct}% of estimate]\n"
            f"Threshold reached by measured spend ({spent_tokens} tokens / {spent_cycles} cycles).\n"
            "You MUST record an explicit stop-loss review decision in your plan update comparing actual progress against your estimate:\n"
            f"  action='decide_plugin_review', project='{name}', decision='continue'|'reduce_scope'|'abandon', reason='<evidence-based comparison vs estimate>'.\n"
            "Continuing is allowed; silence is not."
        )
    return "\n".join(part)


def build_model_context_block(
    provider: str,
    base_model: str,
    summary_json: str,
) -> str:
    """Render the model context block for primary and helper LLMs."""
    return (
        "\n\n## Primary LLM models\n"
        f"Provider: {provider}\n"
        f"Base: {base_model}\n"
        f"Registry (names, status, your assessments): {summary_json}\n"
        "The base handles primary thinking and tool calls. Helpers use the same provider endpoint and API key pool."
    )


def assemble_loop_system_prompt(
    system_prompt: str,
    model_context: str,
    opencode_context: str,
    identity_context: str,
    plugin_embodiment: str,
    untrusted_rule: str,
) -> str:
    """Assemble the final runtime system prompt for a loop cycle."""
    return f"{system_prompt}{model_context}{opencode_context}\n\n{identity_context}{plugin_embodiment}\n\n{untrusted_rule}"


def build_cycle_user_message(
    cycle: int,
    helper_prompt: str,
    plan_version: int,
    plan_summary: str,
    primary_goal: str,
    last_report: str,
    actions_summary: str,
    context: str,
    plugin_section: str,
    plugin_projects_section: str,
    human_context: str,
    failure_context: str,
) -> str:
    """Build the user message starting a loop exploration cycle."""
    human_inputs_display = human_context or "None."
    return (
        f"Begin exploration cycle {cycle}.\n\n"
        f"{helper_prompt}"
        f"Active autonomous plan (version {plan_version}):\n{plan_summary}\n\n"
        f"Primary focus for this cycle: {primary_goal}\n\n"
        "Plan review requirement:\n"
        "Review your plan against previous cycle results. You must either update the plan "
        "(using update_plan to add, edit, drop, reorder, or mark done with a reason citing evidence) "
        "or state why no change is needed in your response.\n\n"
        f"Previous cycle results:\n- Report: {last_report}\n- Actions: {actions_summary}\n\n"
        f"Relevant tools and memories:\n{context}\n\n"
        f"{plugin_section}"
        f"{plugin_projects_section}"
        f"Human inputs to weigh since the prior cycle:\n{human_inputs_display}\n\n"
        "When human inputs are present, weigh each input and record an explicit decision "
        "(accepted, modified, declined, deferred, or noted) with a reason citing evidence or your autonomous priorities.\n\n"
        f"Recent tool-creation diagnostics (repair these instead of renaming the tool):\n{failure_context}\n\n"
        "Execute tools according to your plan, observe results, reflect, and finish with this cycle's report."
    )
