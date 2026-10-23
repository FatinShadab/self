"""State transition and usability calculation for opencode providers."""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any

from agent.opencode.provider_status.constants import (
    BACKOFF_SCHEDULE,
    PROVIDER_ENV_VARS,
    _hash_key,
    _iso_now,
)
from agent.opencode.provider_status.storage import blank_provider_state


def sync_environment_keys(state: dict[str, Any]) -> bool:
    """Inspect environment for key additions or changes; return True if changed."""
    providers = state.setdefault("providers", {})
    changed = False

    for provider, env_var in PROVIDER_ENV_VARS.items():
        current_key = os.environ.get(env_var, "").strip()
        pdata = providers.setdefault(provider, blank_provider_state(provider))
        stored_hash = pdata.get("key_hash")

        if not current_key:
            if pdata.get("state") != "not_configured":
                pdata["state"] = "not_configured"
                pdata["until"] = None
                pdata["key_hash"] = None
                changed = True
        else:
            new_hash = _hash_key(current_key)
            if stored_hash != new_hash:
                pdata["state"] = "unknown"
                pdata["until"] = None
                pdata["last_error"] = None
                pdata["consecutive_failures"] = 0
                pdata["key_hash"] = new_hash
                changed = True
    return changed


def record_provider_success(state: dict[str, Any], provider: str) -> None:
    """Update state marking provider as available."""
    pdata = state.setdefault("providers", {}).setdefault(provider, blank_provider_state(provider))
    pdata["state"] = "available"
    pdata["until"] = None
    pdata["last_error"] = None
    pdata["last_checked"] = _iso_now()
    pdata["consecutive_failures"] = 0


def record_provider_failure(
    state: dict[str, Any],
    provider: str,
    category: str,
    error_text: str,
    reset_seconds: float | None = None,
    now_ts: float | None = None,
) -> None:
    """Update state after a classified provider failure."""
    current_ts = time.time() if now_ts is None else now_ts
    pdata = state.setdefault("providers", {}).setdefault(provider, blank_provider_state(provider))
    failures = int(pdata.get("consecutive_failures", 0)) + 1
    pdata["consecutive_failures"] = failures
    pdata["last_error"] = (error_text or "")[:300]
    pdata["last_checked"] = _iso_now()

    if category == "invalid_key":
        pdata["state"] = "invalid"
        pdata["until"] = None

    elif category == "quota_daily":
        pdata["state"] = "throttled"
        delay = reset_seconds if reset_seconds is not None else 3600.0  # 1h fallback
        until_dt = datetime.fromtimestamp(current_ts + delay, timezone.utc)
        pdata["until"] = until_dt.isoformat()

    elif category == "throttled":
        pdata["state"] = "throttled"
        if reset_seconds is not None:
            delay = reset_seconds
        else:
            idx = min(failures - 1, len(BACKOFF_SCHEDULE) - 1)
            delay = float(BACKOFF_SCHEDULE[max(0, idx)])
        until_dt = datetime.fromtimestamp(current_ts + delay, timezone.utc)
        pdata["until"] = until_dt.isoformat()

    else:  # transient
        if failures >= 2:
            pdata["state"] = "throttled"
            until_dt = datetime.fromtimestamp(current_ts + 60.0, timezone.utc)
            pdata["until"] = until_dt.isoformat()


def compute_usability(state: dict[str, Any], now_ts: float | None = None) -> dict[str, Any]:
    """Compute overall usability and transitions expired throttles to probe_due."""
    current_ts = time.time() if now_ts is None else now_ts
    providers = state.setdefault("providers", {})
    computed: dict[str, Any] = {}
    usable_count = 0
    earliest_retry_ts: float | None = None
    earliest_retry_str: str | None = None
    reasons: list[str] = []

    for pname in ("groq", "google", "huggingface"):
        pdata = dict(providers.get(pname, blank_provider_state(pname)))
        st = pdata.get("state", "unknown")
        until_str = pdata.get("until")

        # Check if throttled window has expired -> probe_due
        if st == "throttled" and until_str:
            try:
                until_dt = datetime.fromisoformat(until_str)
                if until_dt.timestamp() <= current_ts:
                    st = "probe_due"
                    pdata["state"] = "probe_due"
                else:
                    ts = until_dt.timestamp()
                    if earliest_retry_ts is None or ts < earliest_retry_ts:
                        earliest_retry_ts = ts
                        earliest_retry_str = until_str
            except (ValueError, TypeError):
                st = "probe_due"
                pdata["state"] = "probe_due"
        elif st == "throttled" and not until_str:
            st = "probe_due"
            pdata["state"] = "probe_due"

        computed[pname] = pdata

        if st in ("available", "probe_due", "unknown"):
            usable_count += 1
        else:
            reasons.append(f"{pname}: {st}")

    is_usable = usable_count > 0
    if is_usable:
        reason = "One or more providers are available or ready for probe."
    else:
        reason = "All configured providers are unusable: " + "; ".join(reasons)

    return {
        "usable": is_usable,
        "reason": reason,
        "earliest_retry": earliest_retry_str,
        "providers": computed,
    }
