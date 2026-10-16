"""Persistent capability requests, daily budgets, and crash-safe checkpoints."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from event_log import EventLogger
from file_lock import locked_file


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CapabilityRequests:
    EXTERNAL_KINDS = {"credential", "host_mount", "port", "email", "money", "third_party_account", "external_service"}

    def __init__(self, workspace: str | Path, logger: EventLogger) -> None:
        self.path = Path(workspace) / "state" / "capability_requests.md"
        self.logger = logger

    def request(self, kind: str, summary: str, reason: str, provider: str = "", env_names: list[str] | None = None, signup_url: str = "") -> dict[str, Any]:
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
            "- Human action required: approve by editing the host .env or docker-compose.yml yourself, then recreate the container.",
            "- SELF cannot create accounts, edit host configuration, open host ports, add mounts, send email, or make financial actions.", "",
        ]
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines))
        self.logger.log("capability_requested", kind=kind, provider=provider, env_names=env_names or [], official_page=signup_url)
        return {"ok": False, "status": "human_approval_required", "path": str(self.path)}


class DailyTokenLedger:
    def __init__(self, workspace: str | Path, logger: EventLogger, cap: int | None = None) -> None:
        self.path = Path(workspace) / "state" / "daily_token_budget.json"
        self.logger = logger
        self.cap = max(1, cap or int(os.getenv("SELF_MAX_TOKENS_PER_DAY", "200000")))
        self.lock_path = self.path.with_suffix(".lock")

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
        temporary = self.path.with_name(f".daily-token-budget-{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def reserve(self, tokens: int) -> bool:
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
        with locked_file(self.lock_path):
            data = self._read()
            data["cap"] = self.cap
            data["reserved_tokens"] = max(0, int(data["reserved_tokens"]) - reserved)
            data["used_tokens"] = int(data["used_tokens"]) + (reserved if actual is None else max(0, actual))
            data["updated_at"] = now()
            self._write(data)
            self.logger.log("daily_token_budget_updated", used=data["used_tokens"], reserved=data["reserved_tokens"], cap=self.cap)


class RunCheckpoint:
    def __init__(self, workspace: str | Path, logger: EventLogger) -> None:
        self.path = Path(workspace) / "state" / "run_checkpoint.json"
        self.logger = logger

    def load(self) -> dict[str, Any]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def save(self, **data: Any) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"updated_at": now(), **self.logger.redactor.value(data)}
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, self.path)

