"""Opencode availability status, health tracking, and provider failure classification.

Manages persistent status in state/opencode_status.json with cross-process locking.
Tracks per-provider states: available, throttled, invalid, not_configured, unknown.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from agent.infra.file_lock import locked_file

logger = logging.getLogger("agent.opencode.status")

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


class OpencodeStatusTracker:
    """Manages persistent availability status for opencode providers."""

    def __init__(
        self,
        workspace: str | Path | None = None,
        config_path: str | Path | None = None,
        binary_path: str = "/usr/local/bin/opencode",
        runner_fn: Callable[..., subprocess.CompletedProcess] | None = None,
    ) -> None:
        self.workspace = Path(workspace) if workspace else Path.cwd()
        # State path: state/opencode_status.json
        state_dir = self.workspace / "state"
        self.state_path = state_dir / "opencode_status.json"
        self.lock_path = self.state_path.with_suffix(".lock")
        self.binary_path = binary_path
        self.config_path = (
            Path(config_path)
            if config_path
            else self.workspace / "scripts" / "opencode" / "config.json"
        )
        self.runner_fn = runner_fn or subprocess.run
        self._ensure_initialized()

    def _load_config(self) -> dict[str, Any]:
        """Load opencode config.json, returning an empty dict on error."""
        if self.config_path and self.config_path.is_file():
            try:
                return json.loads(self.config_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
        return {}

    def _blank_provider_state(self, provider: str) -> dict[str, Any]:
        """Generate default initial state for a provider."""
        env_var = PROVIDER_ENV_VARS.get(provider, "")
        key = os.environ.get(env_var, "").strip() if env_var else ""
        if not key:
            return {
                "state": "not_configured",
                "until": None,
                "last_error": None,
                "last_checked": None,
                "consecutive_failures": 0,
                "key_hash": None,
            }
        return {
            "state": "unknown",
            "until": None,
            "last_error": None,
            "last_checked": None,
            "consecutive_failures": 0,
            "key_hash": _hash_key(key),
        }

    def _ensure_initialized(self) -> None:
        """Create initial state file if absent."""
        if not self.state_path.exists():
            self._write_state(self._initial_state())

    def _initial_state(self) -> dict[str, Any]:
        """Construct full initial state dictionary."""
        providers_state: dict[str, Any] = {}
        for provider in ("groq", "google", "huggingface"):
            providers_state[provider] = self._blank_provider_state(provider)
        return {
            "version": 1,
            "updated_at": _iso_now(),
            "providers": providers_state,
        }

    def _read_state(self) -> dict[str, Any]:
        """Read state under lock. Callers should hold the file lock."""
        try:
            if self.state_path.exists():
                data = json.loads(self.state_path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and "providers" in data:
                    return data
        except (OSError, json.JSONDecodeError):
            pass
        return self._initial_state()

    def _write_state(self, data: dict[str, Any]) -> None:
        """Atomically persist state data under lock."""
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        data["updated_at"] = _iso_now()
        tmp_path = self.state_path.with_suffix(f".tmp.{os.getpid()}")
        try:
            tmp_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            os.replace(tmp_path, self.state_path)
        except BaseException:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def sync_keys_with_environment(self) -> None:
        """Inspect environment for key additions or changes; update state accordingly."""
        with locked_file(self.lock_path):
            state = self._read_state()
            providers = state.setdefault("providers", {})
            changed = False

            for provider, env_var in PROVIDER_ENV_VARS.items():
                current_key = os.environ.get(env_var, "").strip()
                pdata = providers.setdefault(provider, self._blank_provider_state(provider))
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
                        # Key has been set or changed: reset invalid/not_configured to unknown
                        pdata["state"] = "unknown"
                        pdata["until"] = None
                        pdata["last_error"] = None
                        pdata["consecutive_failures"] = 0
                        pdata["key_hash"] = new_hash
                        changed = True

            if changed:
                self._write_state(state)

    def get_provider_state(self, provider: str) -> dict[str, Any]:
        """Return a copy of the recorded state for a provider."""
        self.sync_keys_with_environment()
        with locked_file(self.lock_path):
            state = self._read_state()
            return dict(state.get("providers", {}).get(provider, self._blank_provider_state(provider)))

    def record_success(self, provider: str) -> None:
        """Record successful execution or probe for a provider."""
        with locked_file(self.lock_path):
            state = self._read_state()
            pdata = state.setdefault("providers", {}).setdefault(provider, self._blank_provider_state(provider))
            pdata["state"] = "available"
            pdata["until"] = None
            pdata["last_error"] = None
            pdata["last_checked"] = _iso_now()
            pdata["consecutive_failures"] = 0
            self._write_state(state)

    def record_failure(
        self,
        provider: str,
        category: str,
        error_text: str,
        reset_seconds: float | None = None,
    ) -> None:
        """Update provider state after a classified failure."""
        now_ts = time.time()
        with locked_file(self.lock_path):
            state = self._read_state()
            pdata = state.setdefault("providers", {}).setdefault(provider, self._blank_provider_state(provider))
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
                until_dt = datetime.fromtimestamp(now_ts + delay, timezone.utc)
                pdata["until"] = until_dt.isoformat()

            elif category == "throttled":
                pdata["state"] = "throttled"
                if reset_seconds is not None:
                    delay = reset_seconds
                else:
                    idx = min(failures - 1, len(BACKOFF_SCHEDULE) - 1)
                    delay = float(BACKOFF_SCHEDULE[max(0, idx)])
                until_dt = datetime.fromtimestamp(now_ts + delay, timezone.utc)
                pdata["until"] = until_dt.isoformat()

            else:  # transient
                # For transient failures, mark throttled with short 1m delay if repeated
                if failures >= 2:
                    pdata["state"] = "throttled"
                    until_dt = datetime.fromtimestamp(now_ts + 60.0, timezone.utc)
                    pdata["until"] = until_dt.isoformat()

            self._write_state(state)

    def usability(self) -> dict[str, Any]:
        """Compute system usability across all providers.

        Transitions throttled providers whose until has passed into 'probe_due'.
        Returns {usable: bool, reason: str, earliest_retry: str | None, providers: dict}.
        """
        self.sync_keys_with_environment()
        now_iso = _iso_now()
        now_ts = time.time()

        with locked_file(self.lock_path):
            state = self._read_state()
            providers = state.setdefault("providers", {})
            computed: dict[str, Any] = {}
            usable_count = 0
            earliest_retry_ts: float | None = None
            earliest_retry_str: str | None = None
            reasons: list[str] = []

            for pname in ("groq", "google", "huggingface"):
                pdata = dict(providers.get(pname, self._blank_provider_state(pname)))
                st = pdata.get("state", "unknown")
                until_str = pdata.get("until")

                # Check if throttled window has expired -> probe_due
                if st == "throttled" and until_str:
                    try:
                        until_dt = datetime.fromisoformat(until_str)
                        if until_dt.timestamp() <= now_ts:
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
                    # Throttled with no until is immediately probe_due
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

    def probe(self, provider: str) -> bool:
        """Run a trivial headless opencode probe for *provider*.

        Probes are the ONLY way a throttled provider returns to available.
        Returns True if probe succeeded, False otherwise.
        """
        env_var = PROVIDER_ENV_VARS.get(provider, "")
        key = os.environ.get(env_var, "").strip() if env_var else ""
        if not key:
            self.record_failure(provider, "invalid_key", f"No API key in {env_var}")
            return False

        # Determine model for this provider from config
        config = self._load_config()
        models = config.get("models", [])
        chosen_model = None
        for m in models:
            if isinstance(m, str) and m.startswith(f"{provider}/") and not m.startswith("_PLACEHOLDER"):
                chosen_model = m
                break

        # Build command: opencode run --auto --standalone [<model>] "reply with the single word OK"
        cmd = [self.binary_path, "run", "--auto", "--standalone"]
        if chosen_model:
            cmd.extend(["--model", chosen_model])
        cmd.append("reply with the single word OK")

        # Map environment variables: pass standard expected variable
        env = {
            "PATH": os.environ.get("PATH", ""),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "HOME": os.environ.get("HOME", "/tmp"),
        }
        std_var = PROVIDER_STANDARD_ENV.get(provider)
        if std_var:
            env[std_var] = key

        try:
            res = self.runner_fn(
                cmd,
                capture_output=True,
                text=True,
                timeout=45,
                env=env,
            )
            output = (res.stdout or "") + " " + (res.stderr or "")
            category = classify_failure(res.returncode, output)
            if category == "ok":
                self.record_success(provider)
                return True
            else:
                reset_sec = parse_reset_time(output)
                self.record_failure(provider, category, output[:200], reset_sec)
                return False
        except subprocess.TimeoutExpired:
            self.record_failure(provider, "transient", "Probe timed out after 45s")
            return False
        except (OSError, Exception) as exc:
            self.record_failure(provider, "transient", f"Probe execution error: {exc}")
            return False
