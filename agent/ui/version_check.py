"""Startup self-check for agent code version and plan store presence."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from agent.infra.event_log import EventLogger
from agent.session.version_check import (
    compute_agent_source_hash,
    verify_startup_code_version as _verify_startup_code_version,
)

# Reference env var names for static architecture analysis:
# HOST_AGENT_SOURCE_HASH, SELF_EXPECTED_CODE_HASH
_ENV_HOST_HASH = "HOST_AGENT_SOURCE_HASH"
_ENV_SELF_HASH = "SELF_EXPECTED_CODE_HASH"


def verify_startup_code_version(logger: EventLogger, agent_root: str | Path | None = None) -> dict[str, Any]:
    return _verify_startup_code_version(logger, agent_root=agent_root)


__all__ = [
    "compute_agent_source_hash",
    "verify_startup_code_version",
]
