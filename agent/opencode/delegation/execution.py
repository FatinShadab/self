"""Opencode subprocess execution across candidate providers in an isolated sandbox."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from agent.opencode.sandbox import SandboxManager, build_opencode_env
from agent.opencode.status import (
    OpencodeStatusTracker,
    classify_failure,
    parse_reset_time,
)
from agent.prompts.delegation import build_opencode_prompt

logger = logging.getLogger("agent.opencode.delegation.execution")


def execute_candidate_attempts(
    binary_path: str,
    sandbox_manager: SandboxManager,
    status_tracker: OpencodeStatusTracker,
    sandbox_path: Path,
    candidates: list[tuple[str, str | None]],
    target_dirs: list[str],
    acceptance_check: str,
    spec: str,
    timeout: float,
) -> tuple[bool, str | None, str | None, list[str], str, str, str]:
    """Execute opencode in sandbox, falling back through candidate providers on failure.

    Returns:
        (opencode_success, chosen_provider, chosen_model, providers_tried, opencode_log, isolation_used, last_failure_category)
    """
    providers_tried: list[str] = []
    chosen_provider: str | None = None
    chosen_model: str | None = None
    opencode_log: str = ""
    isolation_used: str = "none"
    opencode_success = False
    last_failure_category = "error"

    for attempt_idx, (pname, mname) in enumerate(candidates):
        providers_tried.append(pname)
        current_prompt = build_opencode_prompt(
            target_dirs=target_dirs,
            acceptance_check=acceptance_check,
            spec=spec,
            is_retry=attempt_idx > 0,
        )

        cmd = [binary_path, "run", "--auto", "--standalone"]
        if mname:
            cmd.extend(["--model", mname])
        cmd.append(current_prompt)

        clean_env = build_opencode_env(provider=pname)

        res, isolation = sandbox_manager.run_in_sandbox(
            cmd,
            sandbox_path=sandbox_path,
            env=clean_env,
            timeout_seconds=timeout,
        )
        isolation_used = isolation
        out = (res.stdout or "") + "\n" + (res.stderr or "")
        opencode_log = out

        if res.returncode == 0:
            status_tracker.record_success(pname)
            chosen_provider = pname
            chosen_model = mname
            opencode_success = True
            break
        elif res.returncode == 124:
            last_failure_category = "timeout"
            logger.warning("opencode timed out after %ds on provider %s", timeout, pname)
            break
        else:
            cat = classify_failure(res.returncode, out)
            last_failure_category = cat
            reset_sec = parse_reset_time(out)
            status_tracker.record_failure(pname, cat, out[:300], reset_sec)
            logger.warning("opencode failed on %s (classified as %s)", pname, cat)
            continue

    return (
        opencode_success,
        chosen_provider,
        chosen_model,
        providers_tried,
        opencode_log,
        isolation_used,
        last_failure_category,
    )
