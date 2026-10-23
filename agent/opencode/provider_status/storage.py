"""Atomic persistence and state initialization for opencode providers."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from agent.opencode.provider_status.constants import (
    PROVIDER_ENV_VARS,
    _hash_key,
    _iso_now,
)


def load_config(config_path: Path | None) -> dict[str, Any]:
    """Load opencode config.json, returning an empty dict on error."""
    if config_path and config_path.is_file():
        try:
            return json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return {}


def blank_provider_state(provider: str) -> dict[str, Any]:
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


def initial_state() -> dict[str, Any]:
    """Construct full initial state dictionary."""
    providers_state: dict[str, Any] = {}
    for provider in ("groq", "google", "huggingface"):
        providers_state[provider] = blank_provider_state(provider)
    return {
        "version": 1,
        "updated_at": _iso_now(),
        "providers": providers_state,
    }


def read_state(state_path: Path) -> dict[str, Any]:
    """Read state from disk under lock. Callers should hold the file lock."""
    try:
        if state_path.exists():
            data = json.loads(state_path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "providers" in data:
                return data
    except (OSError, json.JSONDecodeError):
        pass
    return initial_state()


def write_state(state_path: Path, data: dict[str, Any]) -> None:
    """Atomically persist state data under lock."""
    state_path.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = _iso_now()
    tmp_path = state_path.with_suffix(f".tmp.{os.getpid()}")
    try:
        tmp_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp_path, state_path)
    except BaseException:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def ensure_initialized(state_path: Path) -> None:
    """Create initial state file if absent."""
    if not state_path.exists():
        write_state(state_path, initial_state())
