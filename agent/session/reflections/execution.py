"""LLM prompt execution, retry loop, and decision tracking for reflections."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Callable

from agent.helper_models.model_decisions import ModelDecisions
from agent.infra.event_log import EventLogger
from agent.infra.hardening import DailyTokenLedger
from agent.llm.llm import BudgetExceeded, BudgetedLLM, LLMClient, response_truncated
from agent.prompts.reflection import (
    BACKGROUND_REFLECTION_RETRY_NUDGE,
    BACKGROUND_REFLECTION_SYSTEM_PROMPT,
)


def execute_reflection_llm(
    candidate: dict[str, Any],
    workspace: Path,
    logger: EventLogger,
    ledger: DailyTokenLedger,
    client: Any | None,
    max_tokens: int | None,
    is_stopped: Callable[[], bool],
) -> tuple[Any | None, Any]:
    """Execute background reflection via LLM with JSON parse retry.

    Returns (parsed_json_dict_or_none, active_client).
    """
    if is_stopped():
        logger.log("reflection_skipped", cycle=candidate["cycle"], reason="stop_requested")
        return None, client

    context = str(candidate["context_provider"](
        candidate["cycle"], candidate["report"], candidate["actions"], candidate["triggers"],
    ))[:8_000]
    system = BACKGROUND_REFLECTION_SYSTEM_PROMPT
    active_client = client or LLMClient(logger)

    payload = json.dumps({"system": system, "messages": [{"role": "user", "content": context}], "tools": []}, ensure_ascii=False)
    input_reservation = (len(payload.encode("utf-8")) + 1) // 2 + 512
    if ledger.available_tokens() - input_reservation < 64:
        logger.log("reflection_skipped", cycle=candidate["cycle"], reason="budget")
        return None, active_client

    model_registry = getattr(active_client, "model_registry", None)
    decisions = None
    reflection_model = None
    if model_registry is not None:
        decision_budget = BudgetedLLM(active_client, logger, None, ledger)
        decisions = ModelDecisions(
            workspace, logger, model_registry, decision_budget,
            candidate["session_id"],
        )
        reflection_model = decisions.decide_model(
            f"Background reflection after cycle {candidate['cycle']}: {context[:400]}",
            moment="background_reflection",
        )

    base_model = getattr(active_client, "base_model", None) or os.getenv("SELF_BASE_MODEL")
    effective_model = reflection_model or base_model
    if not effective_model:
        raise RuntimeError("No reflection model configured.")
    reflection_cap = (
        model_registry.get_output_cap(effective_model)
        if model_registry is not None
        else (max_tokens or int(os.getenv("SELF_DEFAULT_OUTPUT_CEILING", "32768")))
    )
    model_arg = {"model": reflection_model} if reflection_model is not None else {}
    budget = BudgetedLLM(active_client, logger, None, ledger)

    parsed_value = None
    truncated = False
    parse_failed = False
    last_text = ""
    try:
        for attempt_num in (1, 2):
            if attempt_num == 1:
                messages = [{"role": "user", "content": context}]
            else:
                messages = [
                    {"role": "user", "content": context},
                    {"role": "assistant", "content": last_text[:4000]},
                    {"role": "user", "content": BACKGROUND_REFLECTION_RETRY_NUDGE},
                ]
            response = budget.call(
                system=system, messages=messages, tools=[], max_tokens=reflection_cap, **model_arg,
            )
            is_trunc = response_truncated(response, reflection_cap)
            text = "\n".join(
                str(block.get("text", "")).strip()
                for block in response.content
                if block.get("type") == "text" and str(block.get("text", "")).strip()
            ).strip()
            last_text = text
            if text.startswith("```"):
                text = text.strip("`").removeprefix("json").strip()
            try:
                val = json.loads(text)
                if not isinstance(val, dict):
                    raise ValueError("Reflection response is not a dict")
                parsed_value = val
                if is_trunc:
                    truncated = True
                break
            except Exception:
                truncated = is_trunc
                parse_failed = True
                if attempt_num == 1:
                    continue
                break
    except BudgetExceeded:
        logger.log("reflection_skipped", cycle=candidate["cycle"], reason="budget")
        return None, active_client

    if model_registry is not None and truncated:
        model_registry.record_truncated_call(effective_model)
    if decisions is not None:
        decision_id = getattr(decisions, "last_checkpoint_call_id", None)
        if decision_id:
            if truncated:
                decisions.outcomes.append(
                    decision_id, effective_model, "checkpoint:background_reflection",
                    "call_truncated", True, "objective",
                    session_id=candidate["session_id"],
                )
            if parse_failed:
                decisions.outcomes.append(
                    decision_id, effective_model, "checkpoint:background_reflection",
                    "output_parse_failed", True, "objective",
                    session_id=candidate["session_id"],
                )

    return parsed_value, active_client
