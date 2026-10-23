"""Tool execution event logging with argument redaction and output hashing."""
from __future__ import annotations

import hashlib
import json
import time
import urllib.parse
from typing import Any

from agent.infra.event_log import EventLogger


def prepare_logged_arguments(name: str, arguments: dict[str, Any], logger: EventLogger) -> dict[str, Any]:
    """Sanitize and hash sensitive tool call arguments for audit logging."""
    logged_arguments = dict(arguments)
    if name == "http_get" and "url" in logged_arguments:
        parsed = urllib.parse.urlsplit(str(logged_arguments["url"]))
        logged_arguments["url"] = {
            "host": parsed.hostname or "",
            "path": parsed.path or "/",
        }
    for key in ("content", "code", "test_code", "prompt"):
        if key in logged_arguments:
            content = logger.redactor.known(str(logged_arguments.pop(key)))
            logged_arguments[key + "_chars"] = len(content)
            logged_arguments[key + "_sha256"] = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return logged_arguments


def log_tool_call(logger: EventLogger, name: str, logged_arguments: dict[str, Any]) -> None:
    """Record a structured tool_call event."""
    logger.log("tool_call", tool=name, arguments=logged_arguments)


def log_tool_result(logger: EventLogger, name: str, safe_result: dict[str, Any], started: float) -> None:
    """Record a structured tool_result event with timing and digest metadata."""
    serialized = json.dumps(safe_result, ensure_ascii=False)
    logger.log(
        "tool_result",
        tool=name,
        ok=bool(safe_result.get("ok")),
        duration_ms=round((time.monotonic() - started) * 1000, 2),
        result_chars=len(serialized),
        result_sha256=hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
        preview=serialized[:2_000],
    )
