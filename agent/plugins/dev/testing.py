"""Subprocess test execution with audit hook isolation and anti-mutation checks."""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Callable

from agent.infra.event_log import EventLogger
from agent.plugins.dev.environment import child_env


def snapshot_file_hashes(draft_dir: Path) -> dict[str, str]:
    """Capture source text of all candidate python files to detect mutations."""
    hashes = {}
    for p in draft_dir.rglob("*.py"):
        if "__pycache__" not in p.parts:
            hashes[p.as_posix()] = p.read_text(encoding="utf-8", errors="replace")
    return hashes


def execute_isolated_test(
    dev_dir: Path,
    workspace: Path,
    logger: EventLogger,
    pending_reviews: list[int],
    run_process_fn: Callable[..., dict[str, Any]],
    name: str,
    test_type: str = "unit",
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Execute unittests for a draft plugin in isolation without touching real resources."""
    clean_name = str(name).strip()
    if pending_reviews:
        highest_pct = max(pending_reviews)
        return {
            "ok": False,
            "passed": False,
            "error": (
                f"Mandatory stop-loss review at {highest_pct}% of estimate is pending for plugin '{clean_name}'. "
                "You must record an explicit continue / reduce_scope / abandon decision in your plan update before proceeding."
            ),
        }

    draft_dir = dev_dir / clean_name
    if not draft_dir.exists() or not draft_dir.is_dir():
        return {"ok": False, "passed": False, "error": f"Draft '{clean_name}' does not exist."}

    before_hashes = snapshot_file_hashes(draft_dir)
    tests_dir = draft_dir / "tests"
    if not tests_dir.exists():
        return {"ok": False, "passed": False, "error": f"Tests directory '{tests_dir}' not found."}

    audit_bootstrap = (
        "import sys, unittest\n"
        "def _audit(event, args):\n"
        "    if event.startswith('socket.'):\n"
        "        raise PermissionError(f'Network access blocked in test_plugin: {event}')\n"
        "    if event == 'open':\n"
        "        p = str(args[0]).lower()\n"
        "        if any(m in p for m in ('.env', 'credential', 'secret', 'token', 'api_key', 'password', 'auth')):\n"
        "            raise PermissionError(f'Credential file read blocked in test_plugin: {args[0]}')\n"
        "sys.addaudithook(_audit)\n"
        "sys.argv = ['unittest', 'discover', '-s', 'tests', '-v']\n"
        "unittest.main(module=None)\n"
    )
    cmd = [sys.executable, "-c", audit_bootstrap]
    result = run_process_fn(cmd, cwd=draft_dir, timeout=timeout, cap=20000, env=child_env())

    after_hashes = snapshot_file_hashes(draft_dir)
    if before_hashes != after_hashes:
        return {
            "ok": False,
            "passed": False,
            "error": "Candidate files mutated during test execution; tests rejected.",
        }

    if (workspace / "STOP").exists():
        return {"ok": False, "passed": False, "error": "STOP file detected during test execution."}

    output = result.get("output", "")
    timed_out = result.get("timed_out", False)
    exit_code = result.get("exit_code", 1)

    match = re.search(r"Ran (\d+) tests?", output)
    tests_run = int(match.group(1)) if match else 0

    passed = (
        not timed_out
        and exit_code == 0
        and tests_run > 0
        and "FAILED" not in output
        and "skipped=" not in output
    )

    logger.log(
        "plugin_tested",
        name=clean_name,
        passed=passed,
        tests_run=tests_run,
        exit_code=exit_code,
        timed_out=timed_out,
    )

    return {
        "ok": passed,
        "passed": passed,
        "tests_run": tests_run,
        "output": output,
        "timed_out": timed_out,
        "exit_code": exit_code,
    }
