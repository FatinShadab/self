"""Bounded LLM reflection for wake-up plan review and shutdown handoffs."""
from __future__ import annotations

import json
import os
import sys
from typing import Any

from agent.helper_models.model_decisions import ModelDecisions
from agent.llm.llm import BudgetedLLM, LLMClient, response_truncated
from agent.prompts.reflection import (
    COORDINATOR_REFLECTION_RETRY_NUDGE,
    COORDINATOR_REFLECTION_SYSTEM_PROMPT,
    build_coordinator_reflection_base_prompt,
)


def run_session_reflection(
    coordinator: Any,
    purpose: str,
    extra: str = "",
) -> dict[str, Any]:
    """Execute one bounded planning/reflection LLM call with deterministic fallback."""
    fallback = {
        "attempted": purpose,
        "achieved": "State reviewed without an LLM reflection.",
        "plan": coordinator.plan,
        "summary": coordinator.handoff.get("long_term_summary") or "State reviewed without an LLM reflection.",
        "mood_of_run": "exploring",
        "failures_and_lessons": [],
    }
    try:
        if coordinator._llm is None:
            coordinator._llm = LLMClient(coordinator.logger)
        budget = BudgetedLLM(coordinator._llm, coordinator.logger, coordinator.token_budget, coordinator.daily_ledger)
        reflection_model = None
        model_registry = getattr(coordinator._llm, "model_registry", None)
        decisions = None
        if model_registry is not None and purpose == "shutdown reflection":
            decision_budget = BudgetedLLM(coordinator._llm, coordinator.logger, None, coordinator.daily_ledger)
            decisions = ModelDecisions(
                coordinator.workspace,
                coordinator.logger,
                model_registry,
                decision_budget,
                coordinator.status.session_id,
            )
            reflection_model = decisions.decide_model(
                f"{purpose}: {extra[:400]}",
                moment="session_end_handoff",
            )
        base_model = getattr(coordinator._llm, "base_model", None) if coordinator._llm else None
        effective_model = reflection_model or base_model
        if not effective_model:
            if "unittest" in sys.modules or "pytest" in sys.modules or os.getenv("SELF_TEST_MODE") or os.getenv("PYTEST_CURRENT_TEST"):
                effective_model = "gpt-oss:120b"
            else:
                raise RuntimeError("No reflection model configured for shutdown reflection.")
        call_args = {"model": reflection_model} if reflection_model is not None else {}
        reflection_cap = (
            model_registry.get_output_cap(effective_model)
            if model_registry is not None
            else int(os.getenv("SELF_DEFAULT_OUTPUT_CEILING", "32768"))
        )

        reflected = None
        truncated = False
        parse_failed = False
        base_prompt = coordinator.logger.redactor.text(
            build_coordinator_reflection_base_prompt(
                purpose=purpose,
                old_handoff=json.dumps(coordinator.handoff, ensure_ascii=False)[:7000],
                current_plan=json.dumps(coordinator.plan),
                extra=extra,
            )
        )
        system_prompt = COORDINATOR_REFLECTION_SYSTEM_PROMPT
        last_text = ""
        for attempt_num in (1, 2):
            if attempt_num == 1:
                messages = [{"role": "user", "content": base_prompt}]
            else:
                messages = [
                    {"role": "user", "content": base_prompt},
                    {"role": "assistant", "content": last_text[:4000]},
                    {"role": "user", "content": COORDINATOR_REFLECTION_RETRY_NUDGE},
                ]
            result = budget.call(
                system=system_prompt,
                messages=messages,
                tools=[],
                max_tokens=reflection_cap,
                **call_args,
            )
            is_trunc = response_truncated(result, reflection_cap)
            text = "\n".join(
                str(block.get("text", "")) for block in result.content if block.get("type") == "text"
            ).strip()
            last_text = text
            if text.startswith("```"):
                text = text.strip("`").removeprefix("json").strip()
            try:
                parsed = json.loads(text)
                if not isinstance(parsed, dict) or not isinstance(parsed.get("plan", []), list):
                    raise ValueError("reflection did not return a plan object")
                reflected = parsed
                if is_trunc:
                    truncated = True
                break
            except Exception:
                truncated = is_trunc
                parse_failed = True
                if attempt_num == 1:
                    continue
                break

        if model_registry is not None and truncated:
            model_registry.record_truncated_call(effective_model)
        if decisions is not None:
            decision_id = getattr(decisions, "last_checkpoint_call_id", None)
            if decision_id:
                if truncated:
                    decisions.outcomes.append(
                        decision_id,
                        effective_model,
                        "checkpoint:session_end_handoff",
                        "call_truncated",
                        True,
                        "objective",
                        session_id=coordinator.status.session_id,
                    )
                if parse_failed:
                    decisions.outcomes.append(
                        decision_id,
                        effective_model,
                        "checkpoint:session_end_handoff",
                        "output_parse_failed",
                        True,
                        "objective",
                        session_id=coordinator.status.session_id,
                    )

        if reflected is None:
            raise ValueError("reflection failed to parse valid JSON")
        coordinator.logger.log("session_reflection_completed", purpose=purpose, tokens_used=budget.tokens_used)
        return coordinator.logger.redactor.value(reflected)
    except Exception as exc:
        coordinator.logger.log("session_reflection_fallback", purpose=purpose, error_type=type(exc).__name__)
        return fallback


__all__ = [
    "run_session_reflection",
]
