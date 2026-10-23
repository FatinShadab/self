"""Consistent UTC timestamp utility for the SELF harness."""
from __future__ import annotations

from datetime import datetime, timezone


def now() -> str:
    """Return the current UTC timestamp formatted as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()
