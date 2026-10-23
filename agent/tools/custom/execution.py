"""Execution of registered custom workspace tools via worker subprocess."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable


def execute_custom_tool(
    registry: Any,
    name: str,
    arguments: dict[str, Any],
    run_process_fn: Callable[..., Any],
) -> dict[str, Any]:
    """Execute a registered tool through the isolated worker."""
    registry.refresh()
    if name not in registry.tools:
        raise ValueError(f"Tool {name} is not registered with passing tests and critic")
    meta = registry.tools[name]
    from jsonschema import validate

    validate(arguments, meta["input_schema"])
    worker = Path(__file__).resolve().parent.parent / "tool_worker.py"
    result = run_process_fn(
        [sys.executable, str(worker)],
        cwd=registry.root / name,
        timeout=registry.execution_timeout,
        cap=registry.output_cap,
        env=registry._child_env(),
        stdin=json.dumps(arguments),
    )
    result = registry.logger.redactor.value(result)
    registry.logger.log(
        "custom_tool_executed",
        name=name,
        version=meta["version"],
        exit_code=result["exit_code"],
        timed_out=result["timed_out"],
    )
    if result["exit_code"] != 0 or result["timed_out"] or result["truncated"]:
        return {"ok": False, "error": "Custom tool failed, timed out, or exceeded output cap", **result}
    lines = result["output"].splitlines()
    if not lines or not lines[-1].startswith("SELF_TOOL_RESULT="):
        return {"ok": False, "error": "Custom tool returned no JSON result", **result}
    return {
        "ok": True,
        "result": json.loads(lines[-1].split("=", 1)[1]),
        "output": "\n".join(lines[:-1]),
        "version": meta["version"],
    }
