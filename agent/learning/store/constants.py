"""Constants and text tokenization helpers for learning store."""
from __future__ import annotations

import re
from datetime import datetime, timezone

WORD = re.compile(r"[a-zA-Z0-9_.-]{2,}")
VALID_CONFIDENCE = {"unknown", "low", "medium", "high", "stale"}


def utc_now() -> str:
    """Return the current UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


def _words(value: str) -> set[str]:
    """Tokenize string into lowercase alphanumeric words."""
    return {word.lower() for word in WORD.findall(value)}
