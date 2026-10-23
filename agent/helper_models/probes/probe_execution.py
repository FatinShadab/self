"""Case output evaluation, probe cycle execution, and metric reporting."""
from __future__ import annotations

import json
import re
import time
from typing import Any, Callable

from agent.llm.llm import BudgetExceeded, call_with_minimum, response_truncated
from agent.prompts.probes import PROBE_CASES, PROBE_SYSTEM_PROMPT

OUTPUT_CAP = 1_200
INCONCLUSIVE_NOTE = "Treat inconclusive output as unknown, not as a model failure."


def not_found_error(error: Exception) -> bool:
    """Return True if exception indicates model endpoint 404 / NotFound."""
    return (
        getattr(error, "status_code", None) in {404, "404"}
        or type(error).__name__ == "NotFoundError"
    )


def check_case_output(
    kind: str,
    text: str,
    code_checker: Callable[[str], dict[str, Any]],
) -> dict[str, Any]:
    """Validate model output against objective test cases."""
    if kind == "reasoning":
        passed = text.strip() == "9"
        return {"passed": passed, "reason": "exact_answer" if passed else "wrong_answer"}
    if kind == "summarization":
        passed = len(text.split()) <= 20 and "10" in text and "weekday" in text.casefold()
        return {"passed": passed, "reason": "format_and_anchors" if passed else "format_or_anchor_failed"}
    if kind == "json":
        try:
            passed = json.loads(text) == {"status": "ready", "count": 3}
        except (ValueError, TypeError):
            passed = False
        fenced_json = False
        if not passed:
            fenced = re.fullmatch(r"\s*```(?:json)?\s*\n?(.*?)\n?```\s*", text, re.I | re.S)
            if fenced:
                try:
                    json.loads(fenced.group(1))
                    fenced_json = True
                except (ValueError, TypeError):
                    pass
        return {
            "passed": passed,
            "reason": "valid_json" if passed else "invalid_json_or_values",
            "fenced_json": fenced_json,
        }
    return code_checker(text)


def execute_model_probe(prober: Any, name: str) -> dict[str, Any]:
    """Probe a configured model and store observed capability results."""
    if name not in prober.registry.names:
        valid, err = prober.registry.validate_model_name(name)
        raise ValueError(err)
    probe_id = prober.registry.begin_probe(name, prober.session_id, now=prober.clock())
    cases: list[dict[str, Any]] = []
    failed = True
    objective_failed = False
    inconclusive = False
    try:
        cap = prober.registry.get_output_cap(name)
        for case_item in PROBE_CASES:
            kind, prompt = case_item[0], case_item[1]
            attempts: list[dict[str, Any]] = []
            for attempt in (1, 2):
                started = time.monotonic()
                try:
                    response = call_with_minimum(
                        prober.llm,
                        cap,
                        system=PROBE_SYSTEM_PROMPT,
                        messages=[{"role": "user", "content": prompt}],
                        tools=[],
                        max_tokens=cap,
                        model=name,
                    )
                except BudgetExceeded:
                    row = {
                        "case": kind,
                        "attempt": attempt,
                        "outcome": "inconclusive",
                        "origin": "skipped_budget",
                        "passed": None,
                        "check": "budget_unavailable",
                        "latency_ms": round((time.monotonic() - started) * 1000),
                        "input_tokens": None,
                        "output_tokens": None,
                        "max_output_tokens": cap,
                        "effective_cap": None,
                        "stop_reason": None,
                        "raw_output": "",
                        "truncated": False,
                    }
                    attempts.append(row)
                    prober.logger.log("model_probe_case", name=name, probe_id=probe_id, **row)
                    break
                except Exception as exc:
                    elapsed = round((time.monotonic() - started) * 1000)
                    not_found = not_found_error(exc)
                    if not prober.client_records_stats:
                        prober.registry.record_call(name, failed=True, latency_ms=elapsed, not_found=not_found)
                    elif not_found:
                        prober.registry.mark_not_found(name)
                    row = {
                        "case": kind,
                        "attempt": attempt,
                        "outcome": "failed",
                        "passed": False,
                        "error_type": type(exc).__name__,
                        "error_kind": "not_found" if not_found else "call_error",
                        "message": (
                            "The endpoint did not recognize this configured model name."
                            if not_found
                            else "Model call failed."
                        ),
                        "latency_ms": elapsed,
                        "input_tokens": None,
                        "output_tokens": None,
                        "max_output_tokens": cap,
                        "effective_cap": None,
                        "stop_reason": None,
                        "raw_output": "",
                        "truncated": False,
                    }
                    attempts.append(row)
                    prober.logger.log("model_probe_case", name=name, probe_id=probe_id, **row)
                    break
                elapsed = round((time.monotonic() - started) * 1000)
                if not prober.client_records_stats:
                    prober.registry.record_call(name, failed=False, latency_ms=elapsed)
                raw = "\n".join(
                    str(block.get("text", "")) for block in response.content if block.get("type") == "text"
                ).strip()
                text = prober.logger.redactor.text(raw)
                cap_used = response.max_output_tokens or cap
                truncated = response_truncated(response, cap) or len(text) > OUTPUT_CAP
                check = (
                    check_case_output(kind, raw, prober.code_checker)
                    if raw and not truncated
                    else {"passed": None, "reason": "no_complete_output"}
                )
                outcome = (
                    "inconclusive"
                    if not raw or truncated
                    else "passed"
                    if check["passed"]
                    else "failed"
                )
                prober.registry.record_probe_outcome(name, outcome)
                row = {
                    "case": kind,
                    "attempt": attempt,
                    "outcome": outcome,
                    "passed": check["passed"],
                    "check": check["reason"],
                    "fenced_json": bool(check.get("fenced_json", False)),
                    "latency_ms": elapsed,
                    "input_tokens": response.input_tokens,
                    "output_tokens": response.output_tokens,
                    "max_output_tokens": cap_used,
                    "effective_cap": cap_used,
                    "stop_reason": response.stop_reason,
                    "raw_output": text[:OUTPUT_CAP],
                    "truncated": truncated,
                }
                attempts.append(row)
                prober.logger.log("model_probe_case", name=name, probe_id=probe_id, **row)
                if raw or attempt == 2:
                    break
            final = {**attempts[-1], "attempts": attempts}
            cases.append(final)
            if "error_type" in final or final.get("origin") == "skipped_budget":
                break
        failed = any("error_type" in row for row in cases)
        objective_failed = any(row["outcome"] == "failed" for row in cases)
        inconclusive = (
            not failed
            and not objective_failed
            and (
                len(cases) < len(PROBE_CASES)
                or any(row["outcome"] == "inconclusive" for row in cases)
            )
        )
        probe_latencies = [row.get("latency_ms") for row in cases if row.get("latency_ms") is not None]
        probe_avg_latency = round(sum(probe_latencies) / len(probe_latencies)) if probe_latencies else None
        result = {
            "ok": not failed,
            "name": name,
            "probe_id": probe_id,
            "origin": (
                "skipped_budget"
                if any(row.get("origin") == "skipped_budget" for row in cases)
                else "model_probe"
            ),
            "outcome": (
                "failed"
                if failed or objective_failed
                else "inconclusive"
                if inconclusive
                else "passed"
            ),
            "probe_latency_ms": probe_avg_latency,
            "note": INCONCLUSIVE_NOTE,
            "cases": cases,
        }
        prober.logger.log(
            "model_probe_completed",
            name=name,
            probe_id=probe_id,
            completed_cases=len(cases),
            failed=failed,
            inconclusive=inconclusive,
        )
        return result
    finally:
        probe_latencies = [row.get("latency_ms") for row in cases if row.get("latency_ms") is not None]
        probe_avg_latency = round(sum(probe_latencies) / len(probe_latencies)) if probe_latencies else None
        prober.registry.finish_probe(
            name,
            probe_id,
            failed=failed or objective_failed,
            inconclusive=inconclusive,
            latency_ms=probe_avg_latency,
        )
