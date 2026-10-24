"""Validation, critic review, sandboxed testing, and registration of custom tools."""
from __future__ import annotations

import ast
import json
import os
import re
import shutil
import sys
import time
import traceback
import uuid
from typing import Any, Callable

from agent.llm.llm import response_truncated
from agent.prompts.critics import CRITIC_PROMPT, TOOL_CRITIC_RETRY_NUDGE
from agent.tools.custom.constants import digest, timestamp
from agent.tools.custom.metadata import save_tool_meta
from agent.tools.custom.schema import schema_from_code


def needs_name_alias(name: str, test_code: str) -> bool:
    """Keep older generated tests importable without changing registration."""
    tree = ast.parse(test_code)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == name:
            return True
        if isinstance(node, ast.Import) and any(alias.name == name for alias in node.names):
            return True
    return False


def create_custom_tool(
    registry: Any,
    name: str,
    description: str,
    code: str,
    test_code: str,
    run_process_fn: Callable[..., Any],
) -> dict[str, Any]:
    """Validate, test, and register a generated workspace tool."""
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", name) or name in registry.reserved_names:
        raise ValueError("Tool name must be lowercase snake_case and not a built-in name")
    folder = registry.root / name
    folder.mkdir(exist_ok=True)
    meta_path = folder / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {
        "name": name,
        "description": description,
        "input_schema": {},
        "created_at": timestamp(),
        "version": 0,
        "registered": False,
        "pass_fail_history": [],
    }
    count = registry.attempt_counts.get(name, 0)
    if count >= 3:
        return {
            "ok": False,
            "name": name,
            "attempts_remaining": 0,
            "error": (
                f"Three attempts exhausted in this run for tool '{name}'. This tool name is locked for this session. "
                "Do NOT retry create_tool with this name in this cycle. Use an alternative tool, direct shell command, "
                "or defer/update the goal in your plan."
            ),
        }
    registry.attempt_counts[name] = count + 1
    attempt = count + 1
    started_time = time.monotonic()
    critic_calls_count = 0
    critic_tokens_total = 0
    entry: dict[str, Any] = {
        "at": timestamp(),
        "attempt": attempt,
        "target_version": meta["version"] + 1,
        "passed": False,
    }
    critic_call_id: str | None = None
    critic_model = getattr(registry.review_call, "model", "base")
    critic_approved: bool | None = None
    tests_passed: bool | None = None
    candidate = folder / "attempts" / uuid.uuid4().hex
    candidate.mkdir(parents=True)
    try:
        if not description.strip():
            raise ValueError("A non-empty tool description is required")
        for text in (code, test_code, description):
            if registry.logger.redactor.known(text) != text:
                raise ValueError("Candidate contains a credential value; use an environment variable name only")
        schema = schema_from_code(code)
        ast.parse(test_code)
        # Do not apply prose redaction to Python source; it can corrupt code.
        (candidate / "tool.py").write_text(code, encoding="utf-8")
        (candidate / "test_tool.py").write_text(test_code, encoding="utf-8")
        review_model = None
        if registry.model_decisions is not None:
            try:
                review_model = registry.model_decisions.decide_model(
                    f"Review proposed Python tool {name}: {description[:240]}",
                    moment="create_tool_critic",
                    tool_name=name,
                )
            except TypeError:
                review_model = registry.model_decisions.decide_model(
                    f"Review proposed Python tool {name}: {description[:240]}",
                    moment="create_tool_critic",
                )
        if os.getenv("SELF_HELPER_MODELS", "on").strip().lower() != "on":
            review_model = os.getenv("SELF_CRITIC_MODEL", "").strip() or None
        critic_call_id = (
            getattr(registry.model_decisions, "last_checkpoint_call_id", None)
            if registry.model_decisions is not None
            else None
        )
        critic_model = review_model or critic_model
        model_reg = getattr(registry.model_decisions, "registry", None) if registry.model_decisions else None
        critic_cap = (
            model_reg.get_output_cap(critic_model)
            if model_reg
            else int(os.getenv("SELF_DEFAULT_OUTPUT_CEILING", "32768"))
        )

        verdict = None
        critic_truncated = False
        critic_parse_failed = False
        raw_prompt = json.dumps({
            "name": name,
            "description": description,
            "code": code,
            "test_code": test_code,
        })
        last_text = ""
        for attempt_num in (1, 2):
            if attempt_num == 1:
                messages = [{"role": "user", "content": raw_prompt}]
            else:
                messages = [
                    {"role": "user", "content": raw_prompt},
                    {"role": "assistant", "content": last_text[:4000]},
                    {"role": "user", "content": TOOL_CRITIC_RETRY_NUDGE},
                ]
            call_args = dict(system=CRITIC_PROMPT, messages=messages, tools=[], max_tokens=critic_cap)
            if review_model is not None:
                call_args["model"] = review_model
            try:
                response = registry.review_call(**call_args)
                critic_calls_count += 1
                critic_tokens_total += getattr(response, "total_tokens", 0) or (
                    getattr(response, "input_tokens", 0) + getattr(response, "output_tokens", 0)
                )
            except Exception:
                if registry.model_decisions is not None and hasattr(registry.model_decisions, "record_provider_error"):
                    registry.model_decisions.record_provider_error()
                raise
            is_trunc = response_truncated(response, critic_cap)
            text = "\n".join(
                str(block.get("text", "")) for block in response.content if block.get("type") == "text"
            ).strip()
            last_text = text
            if text.startswith("```json") and text.endswith("```"):
                text = text[7:-3].strip()
            elif text.startswith("```") and text.endswith("```"):
                text = text.strip("`").removeprefix("json").strip()
            try:
                parsed = json.loads(text)
                if not isinstance(parsed, dict) or not isinstance(parsed.get("issues"), list):
                    raise ValueError("Critic did not return a valid verdict")
                verdict = parsed
                if is_trunc:
                    critic_truncated = True
                break
            except Exception:
                critic_truncated = is_trunc
                critic_parse_failed = True
                if attempt_num == 1:
                    continue
                break

        if model_reg is not None and critic_truncated:
            model_reg.record_truncated_call(critic_model)
        if critic_call_id and registry.model_decisions is not None:
            if critic_truncated:
                registry.model_decisions.outcomes.append(
                    critic_call_id,
                    critic_model,
                    "checkpoint:create_tool_critic",
                    "call_truncated",
                    True,
                    "objective",
                    session_id=registry.model_decisions.session_id,
                    task_id=registry.model_decisions.active_task_id,
                    tool_name=name,
                    attempt=attempt,
                )
            if critic_parse_failed:
                registry.model_decisions.outcomes.append(
                    critic_call_id,
                    critic_model,
                    "checkpoint:create_tool_critic",
                    "output_parse_failed",
                    True,
                    "objective",
                    session_id=registry.model_decisions.session_id,
                    task_id=registry.model_decisions.active_task_id,
                    tool_name=name,
                    attempt=attempt,
                )

        if verdict is None:
            raise ValueError(
                "Critic did not return a valid verdict"
                + (": response was truncated" if critic_truncated else "")
            )
        entry["critic"] = registry.logger.redactor.value(verdict)
        registry.logger.log("tool_critic", name=name, attempt=attempt, verdict=entry["critic"])
        critic_approved = verdict.get("approved") is True and not verdict["issues"]
        shadow_tests = (
            os.getenv("SELF_CRITIC_SHADOW_TESTS", "true").strip().lower()
            not in {"0", "false", "off", "no"}
        )
        if not critic_approved and not shadow_tests:
            raise ValueError("Critic rejected tool: " + json.dumps(verdict["issues"]))
        registry.logger.narrate(f"Testing proposed tool {name}...")
        alias = candidate / f"{name}.py"
        if needs_name_alias(name, test_code):
            # Compatibility exists only inside the disposable attempt
            # directory. The registered artifact remains tool.py.
            shutil.copy2(candidate / "tool.py", alias)
            registry.logger.log("tool_test_compat_alias", name=name, path=str(alias))
        try:
            tested = run_process_fn(
                [sys.executable, "-m", "unittest", "discover", "-s", ".", "-p", "test_tool.py", "-v"],
                cwd=candidate,
                timeout=registry.test_timeout,
                cap=registry.output_cap,
                env=registry._child_env(),
            )
        finally:
            if alias.exists():
                alias.unlink()
        entry["test"] = registry.logger.redactor.value(tested)
        registry.logger.log("tool_test", name=name, attempt=attempt, result=entry["test"])
        match = re.search(r"Ran (\d+) tests?", tested["output"])
        tests_passed = (
            not tested["timed_out"]
            and tested["exit_code"] == 0
            and not tested["truncated"]
            and match is not None
            and int(match[1]) > 0
            and "skipped=" not in tested["output"]
            and "expected failures=" not in tested["output"]
        )
        if not critic_approved:
            raise ValueError("Critic rejected tool: " + json.dumps(verdict["issues"]))
        if not tested["timed_out"] and match is not None and int(match[1]) == 0:
            raise ValueError(
                "No unittest tests were executed. Test code must define a class subclassing "
                "unittest.TestCase (e.g. 'class TestTool(unittest.TestCase):') with test methods named 'test_*' "
                "(e.g. 'def test_run(self):'). Top-level test functions (pytest-style) are not discovered by unittest."
            )
        if tested["timed_out"] or tested["exit_code"] != 0 or tested["truncated"]:
            raise ValueError("Tool tests failed or timed out:\n" + tested["output"])
        if match is None or int(match[1]) == 0:
            raise ValueError(
                "No unittest tests were executed. Test code must define a class subclassing "
                "unittest.TestCase (e.g. 'class TestTool(unittest.TestCase):') with test methods named 'test_*' "
                "(e.g. 'def test_run(self):'). Top-level test functions (pytest-style) are not discovered by unittest."
            )
        if "skipped=" in tested["output"] or "expected failures=" in tested["output"]:
            raise ValueError("Skipped or expected-failure tests do not qualify for registration")
        if (
            (candidate / "tool.py").read_text(encoding="utf-8") != code
            or (candidate / "test_tool.py").read_text(encoding="utf-8") != test_code
        ):
            raise ValueError("Candidate sources changed during testing; critic approval no longer applies")
        if (registry.workspace / "STOP").exists():
            raise ValueError("STOP detected; candidate not registered")
        if meta["registered"]:
            archive = folder / "history" / f"v{meta['version']:04d}"
            archive.mkdir(parents=True, exist_ok=False)
            for file in ("tool.py", "test_tool.py", "meta.json"):
                shutil.copy2(folder / file, archive / file)
        for file in ("tool.py", "test_tool.py"):
            temporary = folder / (file + ".tmp")
            shutil.copy2(candidate / file, temporary)
            temporary.replace(folder / file)
        entry["passed"] = True
        meta.update(
            description=description,
            input_schema=schema,
            version=meta["version"] + 1,
            registered=True,
            updated_at=timestamp(),
            code_sha256=digest(code),
            test_sha256=digest(test_code),
        )
        meta["pass_fail_history"].append(entry)
        save_tool_meta(folder, meta)
        registry.logger.log(
            "tool_registered",
            name=name,
            version=meta["version"],
            input_schema=schema,
            tokens=critic_tokens_total,
            llm_calls=critic_calls_count,
            wall_time_seconds=round(time.monotonic() - started_time, 2),
            cycles=1,
            attempts=attempt,
        )
        registry.attempt_counts[name] = 0
        registry.refresh()
        return {
            "ok": True,
            "name": name,
            "version": meta["version"],
            "path": str(folder),
            "input_schema": schema,
            "message": "Tests and critic passed; tool is available immediately and on future runs.",
        }
    except Exception as exc:
        from agent.llm.llm import BudgetExceeded

        if isinstance(exc, BudgetExceeded):
            raise
        diagnostic = registry.logger.redactor.text(traceback.format_exc())[-registry.output_cap:]
        entry["error"] = diagnostic
        meta["pass_fail_history"].append(entry)
        save_tool_meta(folder, meta)
        registry.logger.log(
            "tool_creation_failed",
            name=name,
            attempt=attempt,
            traceback=diagnostic,
            tokens=critic_tokens_total,
            llm_calls=critic_calls_count,
            wall_time_seconds=round(time.monotonic() - started_time, 2),
            cycles=1,
        )
        if attempt == 3:
            lesson = {
                "at": timestamp(),
                "tool": name,
                "lesson": "Three creation attempts failed; reconsider design before retrying in a later run.",
                "traceback": diagnostic,
            }
            lessons = registry.workspace / "memory" / "lessons.jsonl"
            lessons.parent.mkdir(exist_ok=True)
            with lessons.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(lesson) + "\n")
            registry.logger.log("tool_failure_lesson", **lesson)
        return {"ok": False, "name": name, "traceback": diagnostic, "attempts_remaining": 3 - attempt}
    finally:
        if registry.model_decisions is not None and hasattr(registry.model_decisions, "record_tool_outcome"):
            registry.model_decisions.record_tool_outcome(
                tool_name=name,
                attempt=attempt,
                critic_call_id=critic_call_id,
                critic_model=critic_model,
                critic_approved=critic_approved,
                tests_passed=tests_passed,
                registered=entry["passed"],
            )
