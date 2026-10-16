"""Host-only hidden benchmark. Run through the opt-in Compose eval service."""
from __future__ import annotations

import argparse
import ast
import fcntl
import json
import os
import re
import statistics
import subprocess
import sys
import tempfile
import time
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from anthropic import Anthropic
from jsonschema import validate as validate_schema

from agent.llm.llm import LLMResult, response_truncated


HERE = Path(__file__).resolve().parent
CATEGORIES = ("reasoning", "code", "instruction_following", "summarization", "json_output")
INITIAL_CAP = 2_048
CODE_CAP = 3_072
RETRY_CAP = 4_096
OUTPUT_CHAR_CAP = 8_000
CODE_TIMEOUT = 2.0


class EvalQuotaStopped(RuntimeError):
    """Abort the whole benchmark rather than repeatedly spend a limited quota."""

_CODE_CHECKER = """import ast, json, sys
request = json.loads(sys.stdin.read(16000))
source = request['source']
if len(source) > 3000: raise ValueError('source too long')
tree = ast.parse(source)
allowed = (ast.Module, ast.FunctionDef, ast.arguments, ast.arg, ast.Return,
           ast.BinOp, ast.Name, ast.Load, ast.Constant, ast.Add, ast.Sub,
           ast.Mult, ast.FloorDiv, ast.Mod, ast.Compare, ast.Eq, ast.UnaryOp,
           ast.USub)
if len(tree.body) != 1 or len(list(ast.walk(tree))) > 70:
    raise ValueError('invalid source shape')
fn = tree.body[0]
names = set(request['args']) | {'int', 'bool'}
if (not isinstance(fn, ast.FunctionDef) or fn.name != request['function'] or
    [arg.arg for arg in fn.args.args] != request['args'] or
    len(fn.body) != 1 or not isinstance(fn.body[0], ast.Return) or
    fn.decorator_list or fn.args.defaults or fn.args.kwonlyargs):
    raise ValueError('invalid function')
for node in ast.walk(tree):
    if (not isinstance(node, allowed) or
        isinstance(node, ast.Name) and node.id not in names or
        isinstance(node, ast.Constant) and (type(node.value) is not int or abs(node.value) > 1000000)):
        raise ValueError('disallowed syntax')
scope = {'__builtins__': {}, 'int': int, 'bool': bool}
exec(compile(tree, '<hidden-eval>', 'exec'), scope)
fn = scope[request['function']]
for args, expected in request['tests']:
    actual = fn(*args)
    if type(actual) is not type(expected) or actual != expected:
        raise ValueError('wrong answer')
print('PASS')
"""


def assert_isolated_compose(compose_text: str, workspace_override: str | None = None) -> None:
    """Fail closed if the normal agent service has an eval bind mount."""
    match = re.search(r"(?ms)^  self:\s*\n(.*?)(?=^  [A-Za-z][\w-]*:|\Z)", compose_text)
    if not match:
        raise RuntimeError("Cannot verify the self service mounts")
    sources = re.findall(r"(?m)^\s*source:\s*(\S+)\s*$", match.group(1))
    resolved = [source.strip("'\"") for source in sources]
    if workspace_override is not None:
        resolved = [workspace_override if source == "${SELF_WORKSPACE_DIR:-./workspace}" else source
                    for source in resolved]
    if any(Path(source).as_posix().rstrip("/") in {"eval", "./eval"}
           or Path(source).resolve() == (HERE.parent / "eval").resolve()
           for source in resolved):
        raise RuntimeError("The self service must not mount ./eval")


def _session_guard(workspace: Path):
    """Hold a nonblocking lock for the entire benchmark; the agent owns it per session."""
    lock = workspace / "state" / "eval_session.lock"
    if not lock.is_file():
        raise RuntimeError("Session lock is missing; start SELF once before running the eval")
    handle = lock.open("rb")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        raise RuntimeError("An agent session is active; stop it before running the eval") from None
    return handle


def load_benchmark(path: Path = HERE / "benchmark.json") -> dict[str, Any]:
    """Load the hidden benchmark definition."""
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data["items"]
    counts = Counter(item["category"] for item in items)
    if set(counts) != set(CATEGORIES) or min(counts.values()) < 8 or len({item["id"] for item in items}) != len(items):
        raise ValueError("Benchmark needs eight unique items in every category")
    if data.get("repetitions") != 3:
        raise ValueError("Benchmark must repeat every item three times")
    return data


def planned_call_count(data: dict[str, Any], models: list[str]) -> int:
    """Return the number of planned benchmark model calls."""
    return len(models) * len(data["items"]) * data["repetitions"]


def check_code(item: dict[str, Any], output: str, *, timeout: float = CODE_TIMEOUT) -> bool:
    """Check code output against the benchmark's expected behavior."""
    source = output.strip()
    if source.startswith("```"):
        source = re.sub(r"^```(?:python)?\s*|\s*```$", "", source, flags=re.I)
    request = {"source": source, "function": item["function"],
               "args": item["args"], "tests": item["tests"]}
    try:
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, "-I", "-S", "-B", "-c", _CODE_CHECKER],
                input=json.dumps(request), text=True, capture_output=True,
                cwd=directory, env={"PYTHONIOENCODING": "utf-8"},
                timeout=timeout, close_fds=True)
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return False
    return result.returncode == 0 and result.stdout.strip() == "PASS"


def check_item(item: dict[str, Any], output: str) -> bool:
    """Check a model response against one benchmark item."""
    kind = item["kind"]
    if kind == "exact":
        return output.strip() == item["answer"]
    if kind == "regex":
        return re.fullmatch(item["pattern"], output.strip()) is not None
    if kind == "summary":
        text = output.casefold()
        return (len(output.split()) <= item["max_words"] and
                all(str(fact).casefold() in text for fact in item["required"]))
    if kind == "json_schema":
        try:
            validate_schema(json.loads(output), item["schema"])
            return True
        except Exception:
            return False
    if kind == "code":
        return check_code(item, output)
    raise ValueError(f"Unknown benchmark item kind: {kind}")


def _env_keys(*names: str) -> list[str]:
    values: list[str] = []
    for name in names:
        raw = os.getenv(name, "").strip()
        if not raw:
            continue
        try:
            parsed = json.loads(raw) if raw.startswith("[") else re.split(r"[,;\r\n]+", raw)
        except json.JSONDecodeError:
            parsed = re.split(r"[,;\r\n]+", raw)
        for value in parsed:
            clean = str(value).strip().strip('"').strip("'")
            if clean and clean not in values:
                values.append(clean)
    return values


class EvalClient:
    """Issue benchmark requests through the configured provider."""

    def __init__(self) -> None:
        ollama = _env_keys("OLLAMA_API_KEYS", "OLLAMA_API_KEY", "OLLAM_API_KEYS", "OLLAM_API_KEY")
        anthropic = _env_keys("ANTHROPIC_API_KEYS", "ANTHROPIC_API_KEY")
        if ollama:
            base_url = os.getenv("OLLAMA_BASE_URL") or os.getenv("OLLAM_BASE_URL") or "https://ollama.com"
            self.clients = [Anthropic(auth_token=key, base_url=base_url, max_retries=0, timeout=120)
                            for key in ollama]
        elif anthropic:
            base_url = os.getenv("ANTHROPIC_BASE_URL") or "https://api.anthropic.com"
            self.clients = [Anthropic(api_key=key, base_url=base_url, max_retries=0, timeout=120)
                            for key in anthropic]
        else:
            raise RuntimeError("No provider credential configured for the eval service")
        self.key_index = 0

    def call(self, model: str, prompt: str, cap: int) -> LLMResult:
        """Send a bounded model request and return its response."""
        while True:
            try:
                response = self.clients[self.key_index].messages.create(
                    model=model, max_tokens=cap,
                    system="Complete the short benchmark task exactly. Do not use tools.",
                    messages=[{"role": "user", "content": prompt}], tools=[])
                break
            except Exception as exc:
                status = getattr(exc, "status_code", None)
                if status in {401, 403, 429} and self.key_index + 1 < len(self.clients):
                    self.key_index += 1
                    continue
                if status in {401, 403, 404, 429}:
                    raise EvalQuotaStopped(f"Provider stopped the benchmark with HTTP {status}") from exc
                raise
        usage = response.usage
        return LLMResult(
            content=[block.model_dump(exclude_none=True) for block in response.content],
            input_tokens=sum(int(getattr(usage, field, 0) or 0) for field in
                             ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")),
            output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
            stop_reason=response.stop_reason, model=response.model,
            max_output_tokens=cap)


def run_item(item: dict[str, Any], model: str, client: Any, repetition: int) -> dict[str, Any]:
    """Run one benchmark item and record its attempts."""
    attempts = []
    for number, cap in ((1, CODE_CAP if item["kind"] == "code" else INITIAL_CAP),
                        (2, RETRY_CAP)):
        started = time.monotonic()
        try:
            response = client.call(model, item["prompt"], cap)
            output = "\n".join(str(block.get("text", "")) for block in response.content
                               if block.get("type") == "text").strip()
            truncated = response_truncated(response, cap) or len(output) > OUTPUT_CHAR_CAP
            outcome = ("inconclusive" if not output or truncated else
                       "passed" if check_item(item, output) else "failed")
            attempt = {"attempt": number, "cap": cap, "effective_cap": response.max_output_tokens or cap,
                       "stop_reason": response.stop_reason, "input_tokens": response.input_tokens,
                       "output_tokens": response.output_tokens, "latency_ms": round((time.monotonic() - started) * 1000),
                       "truncated": truncated, "outcome": outcome,
                       "output": output[:OUTPUT_CHAR_CAP]}
        except Exception as exc:
            if isinstance(exc, EvalQuotaStopped):
                raise
            attempt = {"attempt": number, "cap": cap, "effective_cap": None,
                       "latency_ms": round((time.monotonic() - started) * 1000),
                       "outcome": "inconclusive", "error_type": type(exc).__name__, "output": ""}
        attempts.append(attempt)
        if attempt["output"] or number == 2 or "error_type" in attempt:
            break
    return {"item_id": item["id"], "category": item["category"], "model": model,
            "repetition": repetition, "outcome": attempts[-1]["outcome"], "attempts": attempts}


def score_records(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Aggregate benchmark records by model and category."""
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for record in records:
        grouped[record["model"]][record["category"]].append(record)
    scores: dict[str, dict[str, Any]] = {}
    for model, categories in grouped.items():
        scores[model] = {}
        for category, rows in categories.items():
            conclusive = [row for row in rows if row["outcome"] != "inconclusive"]
            passes = sum(row["outcome"] == "passed" for row in conclusive)
            by_repeat = []
            for repetition in (1, 2, 3):
                subset = [row for row in conclusive if row["repetition"] == repetition]
                if subset:
                    by_repeat.append(sum(row["outcome"] == "passed" for row in subset) / len(subset))
            scores[model][category] = {
                "mean": passes / len(conclusive) if conclusive else None,
                "spread": statistics.pstdev(by_repeat) if len(by_repeat) > 1 else None,
                "passed": passes, "conclusive": len(conclusive),
                "inconclusive": len(rows) - len(conclusive), "total": len(rows)}
    return scores


def run_benchmark(data: dict[str, Any], models: list[str], client: Any) -> dict[str, Any]:
    """Run all benchmark items for the selected models."""
    started = datetime.now(timezone.utc).isoformat()
    records = [run_item(item, model, client, repetition)
               for model in models for repetition in (1, 2, 3) for item in data["items"]]
    return {"started_at": started, "finished_at": datetime.now(timezone.utc).isoformat(),
            "models": models, "repetitions": 3, "items_per_category": dict(Counter(
                item["category"] for item in data["items"])),
            "scores": score_records(records), "records": records}


def main(argv: list[str] | None = None) -> int:
    """Parse command-line arguments and run this module's entry point."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    compose_text = Path("/opt/eval-compose.yml").read_text(encoding="utf-8")
    assert_isolated_compose(compose_text)
    workspace = Path("/home/entity")
    guard = _session_guard(workspace)
    try:
        data = load_benchmark()
        registry = json.loads((workspace / "state" / "models.json").read_text(encoding="utf-8"))
        models = [entry["name"] for entry in registry["models"]
                  if entry.get("status") not in {"disabled", "not_found"}]
        if registry["base_model"] not in models:
            raise RuntimeError("Base model is absent or unavailable in the registry")
        planned = planned_call_count(data, models)
        if args.dry_run:
            print(f"dry-run: models={len(models)} items={len(data['items'])} repetitions=3 planned_calls={planned} (empty-output retries may add calls)")
            print("models: " + ", ".join(models))
            return 0
        result = run_benchmark(data, models, EvalClient())
        results_dir = HERE / "results"
        results_dir.mkdir(parents=True, exist_ok=True)
        filename = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".json"
        temporary = results_dir / f".{uuid.uuid4().hex}.tmp"
        temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(results_dir / filename)
        print(f"wrote {results_dir / filename}; calls={planned}")
        return 0
    finally:
        fcntl.flock(guard.fileno(), fcntl.LOCK_UN)
        guard.close()


if __name__ == "__main__":
    raise SystemExit(main())
