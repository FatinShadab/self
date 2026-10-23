"""Structured LLM call helper with single-retry recovery for truncation and invalid JSON."""
from __future__ import annotations

import json
from typing import Any, Callable

from agent.llm.llm import BudgetExceeded, BudgetedLLM, response_truncated


def call_structured_json(
    budget: BudgetedLLM,
    *,
    system: str,
    prompt: str,
    max_tokens: int,
    retry_nudge: str = "Your previous response was truncated or invalid JSON. Please return strictly the JSON object.",
    model_arg: dict[str, Any] | None = None,
    on_truncated: Callable[[str], None] | None = None,
    on_parse_failed: Callable[[str], None] | None = None,
) -> tuple[dict[str, Any] | list[Any] | None, bool, bool]:
    """Execute LLM call expecting JSON; retries once if response is truncated or fails to parse.

    Returns:
        (parsed_json, was_truncated, parse_failed)
    """
    model_kwargs = model_arg or {}
    parsed_value = None
    truncated = False
    parse_failed = False
    last_text = ""

    for attempt in (1, 2):
        if attempt == 1:
            messages = [{"role": "user", "content": prompt}]
        else:
            messages = [
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": last_text[:4000]},
                {"role": "user", "content": retry_nudge},
            ]
        try:
            response = budget.call(system=system, messages=messages, tools=[], max_tokens=max_tokens, **model_kwargs)
        except BudgetExceeded:
            return None, False, False

        is_trunc = response_truncated(response, max_tokens)
        text = "\n".join(
            str(block.get("text", "")).strip()
            for block in response.content
            if block.get("type") == "text" and str(block.get("text", "")).strip()
        ).strip()
        last_text = text

        try:
            start_brace = text.find("{")
            start_bracket = text.find("[")
            if start_brace != -1 and (start_bracket == -1 or start_brace < start_bracket):
                end_brace = text.rfind("}")
                if end_brace != -1:
                    text_to_parse = text[start_brace:end_brace + 1]
                else:
                    text_to_parse = text
            elif start_bracket != -1:
                end_bracket = text.rfind("]")
                if end_bracket != -1:
                    text_to_parse = text[start_bracket:end_bracket + 1]
                else:
                    text_to_parse = text
            else:
                text_to_parse = text

            val = json.loads(text_to_parse)
            parsed_value = val
            if is_trunc:
                truncated = True
            break
        except Exception:
            truncated = is_trunc
            parse_failed = True
            if attempt == 1:
                continue
            break

    effective_model = str(model_kwargs.get("model", ""))
    if truncated and on_truncated and effective_model:
        on_truncated(effective_model)
    if parse_failed and on_parse_failed and effective_model:
        on_parse_failed(effective_model)

    return parsed_value, truncated, parse_failed
