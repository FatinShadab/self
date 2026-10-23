"""Constants and hashing helpers for opencode provider status."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

# Standard backoff intervals in seconds: 1m, 5m, 15m, 1h, 6h (cap 6h).
BACKOFF_SCHEDULE = [60, 300, 900, 3600, 21600]

# Mapping of provider names to their namespaced environment variable.
PROVIDER_ENV_VARS: dict[str, str] = {
    "groq": "OPENCODE_GROQ_API_KEY",
    "google": "OPENCODE_GOOGLE_API_KEY",
    "huggingface": "OPENCODE_HF_TOKEN",
}

# Standard mapping of opencode provider names to standard env vars inside opencode.
PROVIDER_STANDARD_ENV: dict[str, str] = {
    "groq": "GROQ_API_KEY",
    "google": "GEMINI_API_KEY",
    "huggingface": "HF_TOKEN",
}


def _now_utc() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(timezone.utc)


def _iso_now() -> str:
    """Return ISO format string of current UTC time."""
    return _now_utc().isoformat()


def _hash_key(key: str) -> str:
    """Return SHA-256 digest of key string (never store raw key)."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()
