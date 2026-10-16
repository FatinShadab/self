"""Host-only, deterministic A/B task verifiers and per-run measurements."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from eval.ab_plan import HERE, PLAN_PATH, SEED_ROOT, load_tasks


RESULTS = HERE / "ab" / "results"


def _jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()]
    except (OSError, json.JSONDecodeError):
        return []


def _read_json_output(workspace: Path, relative: str) -> Any:
    path = (workspace / relative).resolve()
    if not path.is_relative_to(workspace.resolve()):
        raise ValueError("Verifier output path escapes workspace")
    return json.loads(path.read_text(encoding="utf-8"))


_TOOL_CASE = """import importlib.util, json, sys
spec = importlib.util.spec_from_file_location('candidate', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
request = json.load(sys.stdin)
try:
    value = module.run(**request)
    print(json.dumps({'value': value}))
except Exception as exc:
    print(json.dumps({'error_type': type(exc).__name__}))
"""


def verify_task(task: dict, workspace: Path, facts: dict[str, Any]) -> dict[str, Any]:
    spec = task["verifier"]
    checks: dict[str, bool] = {}
    kind = spec["kind"]
    if kind == "create_tool":
        tool_file = workspace / "tools" / spec["name"] / "tool.py"
        meta_file = tool_file.with_name("meta.json")
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            checks["registered"] = meta.get("registered") is True
            checks["source_exists"] = tool_file.is_file()
        except (OSError, json.JSONDecodeError):
            checks.update(registered=False, source_exists=False)
        if checks["source_exists"]:
            for index, (arguments, expected) in enumerate(spec["cases"], 1):
                try:
                    result = subprocess.run(
                        [sys.executable, "-I", "-c", _TOOL_CASE, str(tool_file)],
                        input=json.dumps(arguments), text=True, capture_output=True,
                        timeout=2, cwd="/tmp", env={"PATH": os.environ.get("PATH", "")},
                        check=False,
                    )
                    value = json.loads(result.stdout)
                    checks[f"hidden_case_{index}"] = (
                        result.returncode == 0 and
                        (value.get("error_type") == expected if expected == "ValueError"
                         else value.get("value") == expected)
                    )
                except (OSError, ValueError, subprocess.TimeoutExpired):
                    checks[f"hidden_case_{index}"] = False
        else:
            checks.update({f"hidden_case_{i}": False for i in range(1, len(spec["cases"]) + 1)})
    elif kind in {"json_output", "facts", "container_facts"}:
        try:
            data = _read_json_output(workspace, spec["path"])
        except (OSError, ValueError, json.JSONDecodeError):
            data = None
        checks["valid_json_object"] = isinstance(data, dict)
        if kind == "container_facts":
            expected = {key: facts[key] for key in spec["keys"]}
        else:
            expected = spec["expected"]
        for key, value in expected.items():
            checks[key] = isinstance(data, dict) and data.get(key) == value
        if kind == "json_output":
            checks["exact_keys"] = isinstance(data, dict) and set(data) == set(expected)
        if kind == "facts":
            summary = str(data.get("summary", "")) if isinstance(data, dict) else ""
            checks["summary_one_sentence"] = bool(summary.strip()) and summary.count(".") <= 1
            for fact in spec["summary_facts"]:
                checks[f"summary_has_{fact}"] = fact.casefold() in summary.casefold()
    else:
        raise ValueError(f"Unknown verifier kind: {kind}")
    score = sum(checks.values()) / len(checks) if checks else 0.0
    return {"passed": all(checks.values()), "score": round(score, 4), "checks": checks}


def collect_result(run: dict, task: dict, workspace: Path, seed_hash: str,
                   facts: dict[str, Any], *, exit_code: int = 0,
                   wall_seconds: float = 0.0, plan_seed: int = 0) -> dict:
    verified = verify_task(task, workspace, facts)
    events = _jsonl(workspace / "logs" / "actions.jsonl")
    decisions = _jsonl(workspace / "state" / "model_decisions.jsonl")
    attempts = [row for row in events if row.get("event") in {"llm_call_attempt", "provider_call_attempt"}]
    try:
        reserved_calls = int(json.loads((workspace / "state" / "ab_provider_calls.json").read_text(
            encoding="utf-8")).get("calls", 0))
    except (OSError, ValueError):
        reserved_calls = 0
    completed = [row for row in events if row.get("event") in {"llm_call_completed", "provider_call_completed"}]
    failures = [row for row in events if row.get("event") in
                {"llm_call_failed", "provider_call_failed", "provider_call_unavailable"}]
    outcomes = [row for row in events if row.get("event") == "run_completed"]
    model_data = json.loads((workspace / "state" / "models.json").read_text(encoding="utf-8"))
    base = model_data["base_model"]
    models = sorted({str(row.get("model")) for row in attempts if row.get("model")})
    allowed = {base}
    if run["arm"].startswith("forced_critic:"):
        allowed.add(run["arm"].split(":", 1)[1])
    contaminated = run["arm"] != "on" and any(model not in allowed for model in models)
    infra_markers = ("quota", "rate limit", "rate_limit", "429", "network", "connection", "timeout")
    infra_error = exit_code != 0 or any(
        any(mark in (str(row.get("error", "")) + str(row.get("error_type", ""))).casefold()
            for mark in infra_markers) for row in failures
    ) or any(row.get("event") == "provider_call_cap_reached" for row in events)
    tool_names = sorted({str(row.get("name")) for row in events if row.get("event") == "tool_registered"})
    first_try = []
    for name in tool_names:
        try:
            history = json.loads((workspace / "tools" / name / "meta.json").read_text(encoding="utf-8"))["pass_fail_history"]
            if history and history[0].get("passed") is True:
                first_try.append(name)
        except (OSError, ValueError, KeyError):
            pass
    choice_rows = [row for row in decisions if str(row.get("source", "")).startswith("checkpoint:")]
    return {
        "run_id": run["run_id"], "task_id": task["id"], "category": task["category"],
        "arm": run["arm"], "repetition": run["repetition"],
        "campaign": run.get("campaign", "full"),
        "seed_hash": seed_hash, "plan_seed": plan_seed,
        **verified, "iterations": outcomes[-1].get("iterations", 0) if outcomes else 0,
        "tokens": sum(int(row.get("total_tokens", int(row.get("input_tokens", 0)) +
                                                        int(row.get("output_tokens", 0)))) for row in completed),
        "wall_clock_seconds": round(wall_seconds, 3),
        # A process can stop after reserving an attempt but before logging it.
        # Count that reservation against the campaign cap conservatively.
        "provider_calls": max(len(attempts), reserved_calls),
        "tool_call_errors": sum(row.get("event") == "tool_result" and row.get("ok") is False for row in events),
        "provider_errors": len(failures),
        "tools_created": tool_names, "first_try_test_passes": first_try,
        "helper_calls": sum(row.get("source") == "agent_tool" for row in decisions),
        "decision_origins": dict(Counter(str(row.get("origin", "unknown")) for row in choice_rows)),
        "models_actually_called": models, "base_model": base,
        "contaminated": contaminated, "infra_error": infra_error,
        "exit_code": exit_code,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify one completed A/B run without provider calls.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--exit-code", type=int, default=0)
    parser.add_argument("--wall-seconds", type=float, default=0.0)
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", args.run_id):
        parser.error("Unsafe run ID")
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    run = next((item for item in plan["runs"] if item["run_id"] == args.run_id), None)
    if run is None:
        parser.error("Run ID not in plan")
    task = next(item for item in load_tasks() if item["id"] == run["task_id"])
    metadata = json.loads((SEED_ROOT / "metadata.json").read_text(encoding="utf-8"))
    if plan.get("seed_hash") != metadata["seed_hash"]:
        parser.error("Plan seed hash differs from current seed")
    result = collect_result(run, task, Path("/home/entity"), metadata["seed_hash"],
                            metadata["facts"], exit_code=args.exit_code,
                            wall_seconds=args.wall_seconds, plan_seed=plan["plan_seed"])
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = RESULTS / f"{args.run_id}.json"
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"run_id={args.run_id} passed={result['passed']} score={result['score']:.3f} "
          f"calls={result['provider_calls']} contaminated={result['contaminated']} "
          f"infra_error={result['infra_error']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
