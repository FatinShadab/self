"""Failure classification and reset time extraction for opencode processes."""
from __future__ import annotations

import re


def parse_reset_time(output_text: str) -> float | None:
    """Extract a retry delay in seconds from failure text if present."""
    if not output_text:
        return None
    text = output_text.lower()

    # Pattern: Retry-After: <seconds>
    m = re.search(r"retry-after:\s*(\d+(?:\.\d+)?)", text)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass

    # Pattern: retry in 30s, try again in 2m, retry after 1h
    m = re.search(
        r"(?:retry|try again|wait)\s+(?:in|after)\s+(\d+(?:\.\d+)?)\s*(s|sec|seconds?|m|min|minutes?|h|hr|hours?)",
        text,
    )
    if m:
        val = float(m.group(1))
        unit = m.group(2)
        if unit.startswith("s"):
            return val
        if unit.startswith("m"):
            return val * 60.0
        if unit.startswith("h"):
            return val * 3600.0

    # Pattern: \d+s remaining / until retry
    m = re.search(r"(\d+(?:\.\d+)?)\s*s(?:econds)?\s*(?:remaining|until retry)", text)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass

    return None


def classify_failure(exit_code: int, output_text: str) -> str:
    """Classify process exit and output text into a failure category.

    Returns one of: 'ok', 'throttled', 'quota_daily', 'invalid_key', 'transient'.
    """
    if exit_code == 0:
        return "ok"

    text = (output_text or "").lower()

    # 1. Invalid API Key / Unauthorized (401, 403, invalid key)
    if any(
        phrase in text
        for phrase in (
            "unauthorized",
            "invalid api key",
            "invalid_api_key",
            "invalid key",
            "invalid token",
            "authentication failed",
            "forbidden",
            "401",
            "403",
        )
    ):
        return "invalid_key"

    # 2. Daily Quota / Billing Exceeded
    if any(
        phrase in text
        for phrase in (
            "daily quota",
            "daily limit",
            "quota exceeded",
            "exceeded your current quota",
            "exceeded your quota",
            "insufficient_quota",
            "out of credits",
            "billing",
        )
    ):
        return "quota_daily"

    # 3. Throttled / Rate Limited (429, too many requests, resource exhausted)
    if any(
        phrase in text
        for phrase in (
            "429",
            "rate limit",
            "ratelimit",
            "rate_limit",
            "too many requests",
            "resource exhausted",
            "resource_exhausted",
            "overloaded",
        )
    ):
        return "throttled"

    # Default to transient error (network, timeouts, server 5xx)
    return "transient"
