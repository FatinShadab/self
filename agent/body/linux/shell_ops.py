"""Bounded container shell command execution."""
from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Any, Callable

from agent.infra.event_log import EventLogger


def run_container_shell(
    cmd: str,
    timeout: float,
    workspace: Path,
    output_cap: int,
    logger: EventLogger,
    run_process_fn: Callable[..., Any],
) -> dict[str, Any]:
    """Run a bounded shell command inside the container."""
    stream_id = uuid.uuid4().hex[:12]
    safe_command = logger.redactor.text(cmd)
    logger.log(
        "command_started",
        stream_id=stream_id,
        command=safe_command[:2_000],
        timeout=float(timeout),
    )

    def on_output(chunk: str) -> None:
        logger.log(
            "command_output",
            stream_id=stream_id,
            output=logger.redactor.text(chunk)[:4_000],
        )

    def on_complete(result: dict[str, Any]) -> None:
        logger.log(
            "command_finished",
            stream_id=stream_id,
            exit_code=result.get("exit_code"),
            timed_out=bool(result.get("timed_out")),
            output_bytes=result.get("output_bytes", 0),
            truncated=bool(result.get("truncated")),
        )

    shell_bin = "/bin/bash" if Path("/bin/bash").exists() else (shutil.which("bash") or "/bin/bash")
    return run_process_fn(
        [shell_bin, "-lc", cmd],
        cwd=workspace,
        timeout=float(timeout),
        cap=output_cap,
        on_output=on_output,
        on_complete=on_complete,
    )
