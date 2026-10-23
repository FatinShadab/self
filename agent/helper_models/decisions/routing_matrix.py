"""Helper delegation execution, checkpoint model routing, and prompt truncation retry."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import re
import time
from typing import Any
import uuid

from agent.helper_models.decisions.summary_entry import build_summary_entry
from agent.llm.llm import BudgetExceeded, call_with_minimum, response_truncated
from agent.prompts.model_selection import (
    ASK_MODEL_RETRY_NUDGE,
    ASK_MODEL_SYSTEM_PROMPT,
    DECIDE_MODEL_BASE_SYSTEM,
    DECIDE_MODEL_RETRY_NUDGE,
    DECIDE_MODEL_RETRY_SYSTEM,
)

MAX_DELEGATION_PROMPT_CHARS = 4_000
MAX_RETURN_CHARS = 4_000
CHECKPOINT_CONTEXT_CHARS = 600
CHECKPOINT_SUMMARY_CHARS = 10_000
RAW_RESPONSE_CAP = 4_000
FAILURE_COOLDOWN_SECONDS = 600


def _text(response: Any) -> str:
    return "\n".join(
        str(block.get("text", "")) for block in response.content if block.get("type") == "text"
    ).strip()


def _first_json_object(raw: str) -> dict[str, Any] | None:
    """Find the first complete JSON object inside prose or a code fence."""
    text = re.sub(r"```(?:json)?", "", raw, flags=re.I)
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char == "{":
            try:
                value, _ = decoder.raw_decode(text[index:])
                if isinstance(value, dict):
                    return value
            except json.JSONDecodeError:
                continue
    return None


def get_available_models(registry: Any, failure_cooldown_seconds: int) -> dict[str, dict[str, Any]]:
    """Return eligible models filtered by status and transient failure cooldown."""
    now = time.time()
    return {
        entry["name"]: entry
        for entry in registry.list_models()["models"]
        if entry["status"] not in {"not_found", "disabled"}
        and (
            entry["status"] != "last_call_failed"
            or not entry.get("last_failure_at")
            or now - float(entry["last_failure_at"]) >= failure_cooldown_seconds
        )
    }


def execute_ask_model(
    decisions: Any,
    model: str,
    prompt: str,
    task_type: str,
    reason: str,
    expected_benefit: str,
) -> dict[str, Any]:
    """Delegate a task to an eligible helper and persist the decision."""
    available = decisions._available()
    if model not in available or model == decisions.registry.base_model:
        raise ValueError("Model must be an enabled configured helper")
    for label, value in (
        ("prompt", prompt),
        ("task_type", task_type),
        ("reason", reason),
        ("expected_benefit", expected_benefit),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{label} must be non-empty")
    if len(prompt) > MAX_DELEGATION_PROMPT_CHARS or any(
        len(value) > 300 for value in (task_type, reason, expected_benefit)
    ):
        raise ValueError("Delegation input exceeds its size limit")

    call_id = uuid.uuid4().hex
    started = time.monotonic()
    status = "completed"
    origin = "model_choice"
    used_model = model
    helper_error = None
    tokens = 0
    attempt_rows: list[dict[str, Any]] = []
    budget_start = int(getattr(decisions.llm, "tokens_used", 0))
    system = ASK_MODEL_SYSTEM_PROMPT
    messages = [{"role": "user", "content": prompt}]
    helper_cap = decisions.registry.get_output_cap(model)
    base_cap = decisions.registry.get_output_cap(decisions.registry.base_model)
    try:
        for number in (1, 2):
            call_started = time.monotonic()
            call_messages = (
                messages
                if number == 1
                else [
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": attempt_rows[-1].get("raw_response", "")[:RAW_RESPONSE_CAP]},
                    {"role": "user", "content": ASK_MODEL_RETRY_NUDGE},
                ]
            )
            try:
                response = call_with_minimum(
                    decisions.llm,
                    helper_cap,
                    system=system,
                    messages=call_messages,
                    tools=[],
                    max_tokens=helper_cap,
                    model=model,
                )
            except BudgetExceeded:
                status = "skipped_budget"
                origin = "skipped_budget"
                attempt_rows.append({
                    "model": model,
                    "attempt": number,
                    "effective_cap": None,
                    "requested_cap": helper_cap,
                    "status": "skipped_budget",
                })
                return {
                    "ok": False,
                    "call_id": call_id,
                    "model": model,
                    "status": status,
                    "origin": origin,
                    "output": "",
                }
            except Exception as exc:
                helper_error = type(exc).__name__
                origin = "default_after_error"
                attempt_rows.append({
                    "model": model,
                    "attempt": number,
                    "error_type": helper_error,
                    "max_output_tokens": helper_cap,
                    "effective_cap": None,
                })
                if not decisions._client_records_stats:
                    decisions.registry.record_call(
                        model,
                        failed=True,
                        latency_ms=round((time.monotonic() - call_started) * 1000),
                        not_found=(
                            getattr(exc, "status_code", None) in {404, "404"}
                            or type(exc).__name__ == "NotFoundError"
                        ),
                    )
                break
            raw = decisions.logger.redactor.text(_text(response))
            cap_used = response.max_output_tokens or helper_cap
            truncated = response_truncated(response, helper_cap) or len(raw) > MAX_RETURN_CHARS
            attempt_rows.append({
                "model": model,
                "attempt": number,
                "raw_response": raw[:RAW_RESPONSE_CAP],
                "stop_reason": response.stop_reason,
                "output_tokens": response.output_tokens,
                "max_output_tokens": cap_used,
                "effective_cap": cap_used,
                "truncated": truncated,
            })
            if not decisions._client_records_stats:
                decisions.registry.record_call(
                    model,
                    failed=not raw or truncated,
                    latency_ms=round((time.monotonic() - call_started) * 1000),
                )
            elif not raw or truncated:
                decisions.registry.record_output_failure(model)
            if raw and not truncated:
                tokens = max(
                    response.total_tokens,
                    int(getattr(decisions.llm, "tokens_used", budget_start)) - budget_start,
                )
                return {
                    "ok": True,
                    "call_id": call_id,
                    "model": model,
                    "status": "completed",
                    "origin": "model_choice",
                    "output": raw,
                    "truncated": False,
                    "untrusted": True,
                    "tokens": tokens,
                }
            helper_error = "truncated_output" if truncated else "empty_output"
            origin = "default_after_truncation" if truncated else "default_after_error"

        status = "fallback"
        used_model = decisions.registry.base_model
        call_started = time.monotonic()
        response = call_with_minimum(
            decisions.llm,
            base_cap,
            system=system,
            messages=messages,
            tools=[],
            max_tokens=base_cap,
            model=used_model,
        )
        raw = decisions.logger.redactor.text(_text(response))
        truncated = response_truncated(response, base_cap) or len(raw) > MAX_RETURN_CHARS
        attempt_rows.append({
            "model": used_model,
            "attempt": 1,
            "raw_response": raw[:RAW_RESPONSE_CAP],
            "stop_reason": response.stop_reason,
            "output_tokens": response.output_tokens,
            "max_output_tokens": response.max_output_tokens or base_cap,
            "effective_cap": response.max_output_tokens or base_cap,
            "truncated": truncated,
        })
        if not decisions._client_records_stats:
            decisions.registry.record_call(
                used_model,
                failed=not raw or truncated,
                latency_ms=round((time.monotonic() - call_started) * 1000),
            )
        elif not raw or truncated:
            decisions.registry.record_output_failure(used_model)
        if not raw or truncated:
            status = "fallback_failed"
        tokens = max(
            response.total_tokens,
            int(getattr(decisions.llm, "tokens_used", budget_start)) - budget_start,
        )
        return {
            "ok": status == "fallback",
            "call_id": call_id,
            "model": used_model,
            "status": status,
            "origin": origin,
            "helper_error_type": helper_error,
            "output": raw[:MAX_RETURN_CHARS],
            "truncated": truncated,
            "untrusted": True,
            "tokens": tokens,
        }
    except BudgetExceeded:
        status = "skipped_budget"
        origin = "skipped_budget"
        attempt_rows.append({
            "model": used_model,
            "effective_cap": None,
            "requested_cap": base_cap,
            "status": "skipped_budget",
        })
        return {
            "ok": False,
            "call_id": call_id,
            "model": used_model,
            "status": status,
            "origin": origin,
            "output": "",
        }
    except Exception as exc:
        if status == "fallback":
            attempt_rows.append({
                "model": used_model,
                "attempt": 1,
                "error_type": type(exc).__name__,
                "effective_cap": None,
            })
        status = "failed" if status == "completed" else "fallback_failed"
        origin = "default_after_error" if status == "failed" and origin == "model_choice" else origin
        if status == "fallback_failed" and not decisions._client_records_stats and not isinstance(exc, BudgetExceeded):
            decisions.registry.record_call(
                decisions.registry.base_model,
                failed=True,
                latency_ms=round((time.monotonic() - started) * 1000),
            )
        raise
    finally:
        tokens = max(tokens, int(getattr(decisions.llm, "tokens_used", budget_start)) - budget_start)
        decisions._append({
            "call_id": call_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": decisions.session_id,
            "task_id": decisions.active_task_id,
            "model": model,
            "task_type": task_type,
            "reason": reason,
            "expected_benefit": expected_benefit,
            "source": "agent_tool",
            "status": status,
            "result_model": used_model,
            "origin": origin,
            "attempts": attempt_rows,
            "effective_cap": attempt_rows[-1].get("effective_cap") if attempt_rows else None,
            "helper_error_type": helper_error,
            "latency_ms": round((time.monotonic() - started) * 1000),
            "tokens": tokens,
            "outcome": None,
        })
        decisions.outcomes.append(
            call_id,
            model,
            "agent_tool",
            "helper_response_usable",
            status == "completed",
            "objective",
            session_id=decisions.session_id,
            task_id=decisions.active_task_id,
        )
        if any(att.get("truncated") for att in attempt_rows):
            decisions.outcomes.append(
                call_id,
                model,
                "agent_tool",
                "call_truncated",
                True,
                "objective",
                session_id=decisions.session_id,
                task_id=decisions.active_task_id,
            )
            decisions.registry.record_truncated_call(model)
        if status == "completed":
            decisions.successful_helper_calls.add(call_id)
        decisions._track_call(call_id, model, "agent_tool")


def execute_decide_model(
    decisions: Any,
    context: str,
    options: list[str] | None = None,
    *,
    moment: str,
    tool_name: str | None = None,
) -> str:
    """Choose a model for a checkpoint and record the choice origin."""
    if tool_name is not None and tool_name != decisions._last_tool_name:
        decisions._cached_choices.clear()
        decisions._last_tool_name = tool_name

    available = decisions._available()
    allowed = set(options if options is not None else available.keys()) & set(available)
    allowed.add(decisions.registry.base_model)
    helpers = sorted(name for name in allowed if name != decisions.registry.base_model)
    status = "default"
    origin = "default_after_error"
    default_reason = ""
    choice = decisions.registry.base_model
    reason = ""

    if not helpers:
        default_reason = "no_eligible_helpers"

    if helpers and moment in decisions._cached_choices:
        cached_model, cached_reason = decisions._cached_choices[moment]
        choice = cached_model
        reason = f"Reused choice from deliberate checkpoint for moment '{moment}': {cached_reason}"
        origin = "model_choice"
        status = "selected"
        default_reason = ""
        decision_id = uuid.uuid4().hex
        decisions.last_checkpoint_call_id = decision_id
        summary = [build_summary_entry(decisions.registry.get_model(decisions.registry.base_model))]
        summary.extend(build_summary_entry(available[name]) for name in helpers)
        cap = decisions.registry.get_output_cap(decisions.registry.base_model)
        decisions._append({
            "call_id": decision_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": decisions.session_id,
            "task_id": decisions.active_task_id,
            "model": choice,
            "task_type": moment,
            "reason": reason,
            "expected_benefit": "",
            "source": f"checkpoint:{moment}",
            "status": status,
            "origin": origin,
            "default_reason": default_reason,
            "options": ["base", *helpers],
            "registry_summary": summary,
            "raw_response": None,
            "stop_reason": None,
            "effective_cap": cap,
            "latency_ms": 0,
            "tokens": 0,
            "attempts": [],
            "outcome": None,
        })
        decisions.outcomes.append(
            decision_id,
            choice,
            f"checkpoint:{moment}",
            "choice_was_helper",
            choice != decisions.registry.base_model,
            "objective",
            session_id=decisions.session_id,
            task_id=decisions.active_task_id,
        )
        decisions._track_call(decision_id, choice, f"checkpoint:{moment}")
        return choice

    cap = decisions.registry.get_output_cap(decisions.registry.base_model)
    tokens = 0
    attempts: list[dict[str, Any]] = []
    started = time.monotonic()
    budget_start = int(getattr(decisions.llm, "tokens_used", 0))
    summary = [build_summary_entry(decisions.registry.get_model(decisions.registry.base_model))]
    summary.extend(build_summary_entry(available[name]) for name in helpers)
    offered = ["base", *helpers]
    if helpers:
        compact = {
            "context": decisions.logger.redactor.text(str(context)[:CHECKPOINT_CONTEXT_CHARS]),
            "models": summary,
        }
        prompt = json.dumps(compact, ensure_ascii=False)
        if len(prompt) > CHECKPOINT_SUMMARY_CHARS:
            for entry in summary:
                entry["assessment"] = ""
            prompt = json.dumps(compact, ensure_ascii=False)

        base_system = DECIDE_MODEL_BASE_SYSTEM
        retry_system = DECIDE_MODEL_RETRY_SYSTEM

        messages = [{"role": "user", "content": prompt}]
        for attempt_number in (1, 2):
            system = base_system if attempt_number == 1 else retry_system
            if attempt_number == 2:
                messages = [
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": attempts[-1].get("raw_response", "")[:RAW_RESPONSE_CAP]},
                    {"role": "user", "content": DECIDE_MODEL_RETRY_NUDGE},
                ]
            try:
                response = call_with_minimum(
                    decisions.llm,
                    cap,
                    system=system,
                    messages=messages,
                    tools=[],
                    max_tokens=cap,
                    model=decisions.registry.base_model,
                )
                tokens += response.total_tokens
            except BudgetExceeded:
                origin = "skipped_budget"
                default_reason = "minimum_output_cap_unavailable"
                attempts.append({
                    "attempt": attempt_number,
                    "requested_cap": cap,
                    "effective_cap": None,
                    "status": "skipped_budget",
                })
                decisions._cached_choices.clear()
                break
            except Exception as exc:
                origin = "default_after_error"
                default_reason = type(exc).__name__
                attempts.append({
                    "attempt": attempt_number,
                    "error_type": type(exc).__name__,
                    "max_output_tokens": cap,
                    "effective_cap": None,
                })
                decisions._cached_choices.clear()
                break

            raw = decisions.logger.redactor.text(_text(response))
            truncated = response_truncated(response, cap) or len(raw) > RAW_RESPONSE_CAP
            attempts.append({
                "attempt": attempt_number,
                "raw_response": raw[:RAW_RESPONSE_CAP],
                "stop_reason": response.stop_reason,
                "output_tokens": response.output_tokens,
                "max_output_tokens": response.max_output_tokens or cap,
                "effective_cap": response.max_output_tokens or cap,
                "truncated": truncated,
            })
            if truncated:
                origin = "default_after_truncation"
                default_reason = "truncated_response"
                decisions.registry.record_truncated_call(decisions.registry.base_model)
                decisions._cached_choices.clear()
                continue

            value = _first_json_object(raw)
            proposed = value.get("choice") if value else None
            rationale = value.get("reason") if value else None
            if proposed == "base":
                proposed = decisions.registry.base_model
            if proposed in allowed:
                choice = proposed
                reason = decisions.logger.redactor.text(rationale.strip())[:300] if isinstance(rationale, str) else ""
                origin = "model_choice"
                status = "selected"
                default_reason = ""
                decisions._cached_choices[moment] = (choice, reason)
                break

            origin = "default_after_parse_failure"
            default_reason = "invalid_json_or_choice"
            decisions._cached_choices.clear()

    tokens = max(tokens, int(getattr(decisions.llm, "tokens_used", budget_start)) - budget_start)
    last = attempts[-1] if attempts else {}
    decision_id = uuid.uuid4().hex
    decisions.last_checkpoint_call_id = decision_id
    decisions._append({
        "call_id": decision_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_id": decisions.session_id,
        "task_id": decisions.active_task_id,
        "model": choice,
        "task_type": moment,
        "reason": reason,
        "expected_benefit": "",
        "source": f"checkpoint:{moment}",
        "status": status,
        "origin": origin,
        "default_reason": default_reason,
        "options": offered,
        "registry_summary": summary,
        "raw_response": last.get("raw_response"),
        "stop_reason": last.get("stop_reason"),
        "effective_cap": last.get("effective_cap"),
        "latency_ms": round((time.monotonic() - started) * 1000),
        "tokens": tokens,
        "attempts": attempts,
        "outcome": None,
    })
    decisions.outcomes.append(
        decision_id,
        choice,
        f"checkpoint:{moment}",
        "choice_was_helper",
        choice != decisions.registry.base_model,
        "objective",
        session_id=decisions.session_id,
        task_id=decisions.active_task_id,
    )
    if any(att.get("truncated") for att in attempts):
        decisions.outcomes.append(
            decision_id,
            choice,
            f"checkpoint:{moment}",
            "call_truncated",
            True,
            "objective",
            session_id=decisions.session_id,
            task_id=decisions.active_task_id,
        )
    if origin in {"default_after_parse_failure", "default_after_truncation"}:
        decisions.outcomes.append(
            decision_id,
            choice,
            f"checkpoint:{moment}",
            "output_parse_failed",
            True,
            "objective",
            session_id=decisions.session_id,
            task_id=decisions.active_task_id,
        )
    decisions._track_call(decision_id, choice, f"checkpoint:{moment}")
    return choice


__all__ = [
    "MAX_DELEGATION_PROMPT_CHARS",
    "MAX_RETURN_CHARS",
    "CHECKPOINT_CONTEXT_CHARS",
    "CHECKPOINT_SUMMARY_CHARS",
    "RAW_RESPONSE_CAP",
    "FAILURE_COOLDOWN_SECONDS",
    "_text",
    "_first_json_object",
    "get_available_models",
    "execute_ask_model",
    "execute_decide_model",
]
