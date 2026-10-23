"""Child process isolation environment and timestamp utilities."""
from __future__ import annotations

import os
from datetime import datetime, timezone

SECRET_NAME_MARKERS = ("KEY", "SECRET", "TOKEN", "PASSWORD", "CREDENTIAL", "AUTH")


def now_utc() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


def child_env() -> dict[str, str]:
    """Return stripped environment containing no API keys or credentials, with network disabled via dead proxy."""
    env = {
        key: val for key, val in os.environ.items()
        if not any(marker in key.upper() for marker in SECRET_NAME_MARKERS)
    }
    # Block outbound network by routing proxy to dead loopback port
    env["HTTP_PROXY"] = "http://127.0.0.1:0"
    env["HTTPS_PROXY"] = "http://127.0.0.1:0"
    env["ALL_PROXY"] = "http://127.0.0.1:0"
    env["http_proxy"] = "http://127.0.0.1:0"
    env["https_proxy"] = "http://127.0.0.1:0"
    env["all_proxy"] = "http://127.0.0.1:0"
    env["NO_PROXY"] = ""
    env["no_proxy"] = ""
    return env
