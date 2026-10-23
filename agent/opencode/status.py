"""Opencode availability status, health tracking, and provider failure classification.

Manages persistent status in state/opencode_status.json with cross-process locking.
Tracks per-provider states: available, throttled, invalid, not_configured, unknown.
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any, Callable

from agent.infra.file_lock import locked_file
from agent.opencode.provider_status import (
    BACKOFF_SCHEDULE,
    PROVIDER_ENV_VARS,
    PROVIDER_STANDARD_ENV,
    _hash_key,
    _iso_now,
    _now_utc,
    blank_provider_state,
    classify_failure,
    compute_usability,
    ensure_initialized,
    execute_probe,
    initial_state,
    load_config,
    parse_reset_time,
    read_state,
    record_provider_failure,
    record_provider_success,
    sync_environment_keys,
    write_state,
)

logger = logging.getLogger("agent.opencode.status")


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
        return load_config(self.config_path)

    def _blank_provider_state(self, provider: str) -> dict[str, Any]:
        """Generate default initial state for a provider."""
        return blank_provider_state(provider)

    def _ensure_initialized(self) -> None:
        """Create initial state file if absent."""
        ensure_initialized(self.state_path)

    def _initial_state(self) -> dict[str, Any]:
        """Construct full initial state dictionary."""
        return initial_state()

    def _read_state(self) -> dict[str, Any]:
        """Read state under lock. Callers should hold the file lock."""
        return read_state(self.state_path)

    def _write_state(self, data: dict[str, Any]) -> None:
        """Atomically persist state data under lock."""
        write_state(self.state_path, data)

    def sync_keys_with_environment(self) -> None:
        """Inspect environment for key additions or changes; update state accordingly."""
        with locked_file(self.lock_path):
            state = self._read_state()
            if sync_environment_keys(state):
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
            record_provider_success(state, provider)
            self._write_state(state)

    def record_failure(
        self,
        provider: str,
        category: str,
        error_text: str,
        reset_seconds: float | None = None,
    ) -> None:
        """Update provider state after a classified failure."""
        with locked_file(self.lock_path):
            state = self._read_state()
            record_provider_failure(state, provider, category, error_text, reset_seconds=reset_seconds)
            self._write_state(state)

    def usability(self) -> dict[str, Any]:
        """Compute system usability across all providers."""
        self.sync_keys_with_environment()
        with locked_file(self.lock_path):
            state = self._read_state()
            return compute_usability(state)

    def probe(self, provider: str) -> bool:
        """Run a trivial headless opencode probe for *provider*."""
        return execute_probe(
            provider=provider,
            binary_path=self.binary_path,
            config_path=self.config_path,
            runner_fn=self.runner_fn,
            on_success=self.record_success,
            on_failure=self.record_failure,
        )


__all__ = [
    "BACKOFF_SCHEDULE",
    "OpencodeStatusTracker",
    "PROVIDER_ENV_VARS",
    "PROVIDER_STANDARD_ENV",
    "_hash_key",
    "_iso_now",
    "_now_utc",
    "classify_failure",
    "parse_reset_time",
]
