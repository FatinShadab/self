"""Persistent capability requests, daily budgets, and crash-safe checkpoints."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.infra.event_log import EventLogger
from agent.infra.file_lock import locked_file


def now() -> str:
    """Return the current UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


def get_harness_request_path(workspace: Path | str) -> Path:
    """Return the durable path for pending human request outside the workspace."""
    env_dir = os.environ.get("SELF_HARNESS_STATE_DIR")
    if env_dir:
        return Path(env_dir) / "pending_human_request.json"
    cfg_dir = os.environ.get("SELF_CONFIG_DIR")
    if cfg_dir and Path(cfg_dir).exists():
        return Path(cfg_dir) / "pending_human_request.json"
    ws = Path(workspace).resolve()
    import hashlib
    ws_hash = hashlib.sha256(str(ws).encode("utf-8")).hexdigest()[:12]
    candidate = ws.parent / f".self_harness_{ws_hash}" / "pending_human_request.json"
    try:
        candidate.parent.mkdir(parents=True, exist_ok=True)
        return candidate
    except OSError:
        import tempfile

        fallback = Path(tempfile.gettempdir()) / f".self_harness_{ws_hash}" / "pending_human_request.json"
        fallback.parent.mkdir(parents=True, exist_ok=True)
        return fallback


def clear_pending_human_request(workspace: Path | str) -> None:
    """Clear both workspace HUMAN_REQUEST.md and harness-owned pending request."""
    ws = Path(workspace).resolve()
    hr = ws / "HUMAN_REQUEST.md"
    try:
        hr.unlink(missing_ok=True)
    except OSError:
        pass
    harness_hr = get_harness_request_path(ws)
    try:
        harness_hr.unlink(missing_ok=True)
    except OSError:
        pass


class CapabilityRequests:
    """Record requests for capabilities outside the current environment."""

    EXTERNAL_KINDS = {
        "credential",
        "host_mount",
        "port",
        "email",
        "money",
        "third_party_account",
        "external_service",
        "human_action",
        "other",
        "plugin",
    }

    def __init__(self, workspace: str | Path, logger: EventLogger) -> None:
        self.workspace = Path(workspace)
        self.path = self.workspace / "state" / "capability_requests.md"
        self.human_request = self.workspace / "HUMAN_REQUEST.md"
        self.harness_request = get_harness_request_path(self.workspace)
        self.logger = logger

    def request(
        self,
        kind: str,
        summary: str,
        reason: str,
        provider: str = "",
        env_names: list[str] | None = None,
        signup_url: str = "",
        halt: bool = True,
    ) -> dict[str, Any]:
        """Record a request and return its persisted representation."""
        if kind not in self.EXTERNAL_KINDS:
            raise ValueError(f"kind must be one of: {', '.join(sorted(self.EXTERNAL_KINDS))}")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            f"## Pending capability request — {now()}",
            f"- Kind: {kind}", f"- Summary: {self.logger.redactor.text(summary)[:500]}",
            f"- Reason: {self.logger.redactor.text(reason)[:1_000]}",
            f"- Provider/service: {provider or 'not specified'}",
            f"- Environment variable names: {', '.join(env_names or []) or 'none'}",
            f"- Official page: {signup_url or 'not specified'}",
            "- Note for the human administrator (Human action required): Approve this request by editing host configuration or environment yourself, then restart or resume.",
            "- Notice for the human: SELF cannot create accounts, edit host configuration, open host ports, add mounts, send email, or make financial actions.", "",
        ]
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines))
        self.logger.log("capability_requested", kind=kind, provider=provider, env_names=env_names or [], official_page=signup_url)
        if halt:
            hr_lines = [
                "# Pending Human Action / Capability Request",
                "",
                "SELF has paused work because an external capability or human action is required:",
                f"- Kind: {kind}",
                f"- Summary: {self.logger.redactor.text(summary)[:500]}",
                f"- Reason: {self.logger.redactor.text(reason)[:1_000]}",
                f"- Provider/service: {provider or 'not specified'}",
                f"- Environment variable names: {', '.join(env_names or []) or 'none'}",
                f"- Official page: {signup_url or 'not specified'}",
                "",
                "## How to Resolve and Resume",
                "1. Review the request above or in `state/capability_requests.md`.",
                "2. Perform the required action or update host configuration/credentials.",
                "3. Delete this `HUMAN_REQUEST.md` file (or run `/resume` in the TUI) to allow SELF to resume.",
                "",
            ]
            self.human_request.write_text("\n".join(hr_lines), encoding="utf-8")
            try:
                self.harness_request.parent.mkdir(parents=True, exist_ok=True)
                payload = {
                    "kind": kind,
                    "summary": summary,
                    "reason": reason,
                    "provider": provider,
                    "env_names": env_names or [],
                    "official_page": signup_url,
                    "timestamp": now(),
                    "workspace": str(self.workspace.resolve()),
                }
                self.harness_request.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            except OSError:
                pass
        return {"ok": False, "status": "human_approval_required", "path": str(self.path), "halted": halt}


def _ledger_sleep(duration: float) -> None:
    """Dedicated backoff pause for Windows file lock retries."""
    import time
    time.sleep(duration)


class DailyTokenLedger:
    """Reserve and settle the daily token allowance."""

    def __init__(self, workspace: str | Path, logger: EventLogger, cap: int | None = None, sleeper: Callable[[float], None] = _ledger_sleep) -> None:
        self.path = Path(workspace) / "state" / "daily_token_budget.json"
        self.logger = logger
        self.cap = max(1, cap or int(os.getenv("SELF_MAX_TOKENS_PER_DAY", "200000")))
        self.lock_path = self.path.with_suffix(".lock")
        self.sleeper = sleeper

    def _read(self) -> dict[str, Any]:
        today = datetime.now(timezone.utc).date().isoformat()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data.get("date") == today:
                return data
        except (OSError, json.JSONDecodeError):
            pass
        return {"date": today, "used_tokens": 0, "reserved_tokens": 0, "cap": self.cap, "updated_at": now()}

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        import uuid
        import time

        temporary = self.path.with_name(f".daily-token-budget-{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            # Under Windows, concurrent readers (e.g. TUI or file watchers) holding the file
            # handle cause os.replace to raise PermissionError (WinError 5). Retry with brief backoff.
            for attempt in range(5):
                try:
                    os.replace(temporary, self.path)
                    break
                except PermissionError:
                    if attempt == 4:
                        raise
                    self.sleeper(0.02 * (attempt + 1))
        finally:
            temporary.unlink(missing_ok=True)

    def reserve(self, tokens: int) -> bool:
        """Reserve token capacity before a model call."""
        with locked_file(self.lock_path):
            data = self._read()
            # The configured cap is authoritative even if an older state used a different cap.
            data["cap"] = self.cap
            if int(data["used_tokens"]) + int(data["reserved_tokens"]) + tokens > self.cap:
                self._write(data)
                self.logger.log("daily_token_budget_blocked", requested=tokens, used=data["used_tokens"], reserved=data["reserved_tokens"], cap=self.cap)
                return False
            data["reserved_tokens"] = int(data["reserved_tokens"]) + tokens
            data["updated_at"] = now()
            self._write(data)
            return True

    def available_tokens(self) -> int:
        """Return the remaining daily allowance, including active reservations."""
        with locked_file(self.lock_path):
            data = self._read()
            return max(0, self.cap - int(data.get("used_tokens", 0)) - int(data.get("reserved_tokens", 0)))

    def settle(self, reserved: int, actual: int | None) -> None:
        """Settle a prior reservation against observed usage."""
        with locked_file(self.lock_path):
            data = self._read()
            data["cap"] = self.cap
            data["reserved_tokens"] = max(0, int(data["reserved_tokens"]) - reserved)
            data["used_tokens"] = int(data["used_tokens"]) + (reserved if actual is None else max(0, actual))
            data["updated_at"] = now()
            self._write(data)
            self.logger.log("daily_token_budget_updated", used=data["used_tokens"], reserved=data["reserved_tokens"], cap=self.cap)


class RunCheckpoint:
    """Persist and recover a bounded run's checkpoint."""

    def __init__(self, workspace: str | Path, logger: EventLogger) -> None:
        self.path = Path(workspace) / "state" / "run_checkpoint.json"
        self.logger = logger

    def load(self) -> dict[str, Any]:
        """Load persisted state from the workspace."""
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def save(self, **data: Any) -> None:
        """Persist current state to the workspace."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"updated_at": now(), **self.logger.redactor.value(data)}
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, self.path)

