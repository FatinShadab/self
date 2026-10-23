"""Constants and string sanitization helpers for identity management."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

IDENTITY_MAX_BYTES = 12_000
IDENTITY_CONTEXT_MAX_CHARS = 6_000
NAME_MAX_CHARS = 80


def now() -> str:
    """Return the current UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


def clean_line(value: Any, limit: int = 2_000) -> str:
    """Make a safe, bounded single-line value for a Markdown state file."""
    return " ".join(str(value).replace("\x00", "").split())[:limit]
