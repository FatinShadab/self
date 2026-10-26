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


def get_pending_request_payload(workspace: Path | str) -> dict[str, Any] | None:
    """Return the currently pending human request payload if one exists."""
    ws = Path(workspace).resolve()
    harness_hr = get_harness_request_path(ws)
    if harness_hr.exists():
        try:
            return json.loads(harness_hr.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return None


def decline_pending_capability_request(
    workspace: Path | str,
    reason: str = "",
    logger: EventLogger | None = None,
) -> dict[str, Any] | None:
    """Decline pending capability request, record decision, update map, and clear pause locks."""
    ws = Path(workspace).resolve()
    payload = get_pending_request_payload(ws)
    clear_pending_human_request(ws)
    if not payload:
        return None

    kind = str(payload.get("kind") or "other")
    summary = str(payload.get("summary") or "external capability")
    env_names = list(payload.get("env_names") or [])
    provider = str(payload.get("provider") or "")
    dec_reason = reason.strip() or "Declined by human administrator"

    # 1. Append to state/declined_capabilities.json
    declined_path = ws / "state" / "declined_capabilities.json"
    declined_list: list[dict[str, Any]] = []
    if declined_path.exists():
        try:
            raw = json.loads(declined_path.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                declined_list = raw
        except (OSError, json.JSONDecodeError):
            declined_list = []

    record = {
        "kind": kind,
        "summary": summary,
        "env_names": env_names,
        "provider": provider,
        "declined_at": now(),
        "reason": dec_reason,
    }
    declined_list.append(record)
    try:
        declined_path.parent.mkdir(parents=True, exist_ok=True)
        declined_path.write_text(json.dumps(declined_list, indent=2), encoding="utf-8")
    except OSError:
        pass

    # 2. Append resolution to state/capability_requests.md
    cap_md = ws / "state" / "capability_requests.md"
    try:
        cap_md.parent.mkdir(parents=True, exist_ok=True)
        with cap_md.open("a", encoding="utf-8") as handle:
            handle.write(
                f"\n## Capability request declined — {now()}\n"
                f"- Kind: {kind}\n"
                f"- Summary: {summary}\n"
                f"- Reason: {dec_reason}\n"
                f"- Action: Capability is unavailable; proceed without it.\n\n"
            )
    except OSError:
        pass

    # 3. Add to human input inbox so agent prompt weighs this human decision
    try:
        inbox_path = ws / "state" / "human_input.jsonl"
        inbox_path.parent.mkdir(parents=True, exist_ok=True)
        input_record = {
            "timestamp": now(),
            "text": (
                f"Human administrator declined capability request ({kind}: {summary}). "
                f"Reason: {dec_reason}. "
                "Do not request this capability again. Record it as unavailable in your environment map and proceed with other exploration."
            ),
            "kind": "decision",
        }
        with inbox_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(input_record, ensure_ascii=False) + "\n")
    except OSError:
        pass

    # 4. Record negative fact in state/map.json if applicable
    try:
        map_path = ws / "state" / "map.json"
        if map_path.exists():
            map_data = json.loads(map_path.read_text(encoding="utf-8"))
            entries = map_data.get("entries", {})
            inferred_key = None
            if "docker" in summary.lower() or any("docker" in str(e).lower() for e in env_names):
                inferred_key = "docker"
            elif env_names:
                inferred_key = env_names[0]

            if inferred_key:
                entries[inferred_key] = {
                    "value": f"unavailable (declined: {summary})",
                    "confidence": "high",
                    "last_verified": now(),
                    "evidence": f"Human administrator declined capability request: {dec_reason}",
                    "plugin": "core",
                    "body": "container",
                }
                map_data["entries"] = entries
                map_path.write_text(json.dumps(map_data, indent=2), encoding="utf-8")
    except (OSError, json.JSONDecodeError):
        pass

    if logger:
        logger.narrate(f"Capability request declined ({kind}: {summary}): {dec_reason}")

    return record


def approve_pending_capability_request(
    workspace: Path | str,
    reason: str = "",
    logger: Any = None,
) -> dict[str, Any] | None:
    """Approve pending capability request, clear locks, and record decision."""
    ws = Path(workspace).resolve()
    payload = get_pending_request_payload(ws)
    if not payload:
        return None

    req_id = str(payload.get("id") or "")
    kind = str(payload.get("kind") or "other")
    summary = str(payload.get("summary") or "external capability")
    app_reason = reason.strip() or "Approved by human administrator"

    cap_md = ws / "state" / "capability_requests.md"
    try:
        cap_md.parent.mkdir(parents=True, exist_ok=True)
        with cap_md.open("a", encoding="utf-8") as handle:
            handle.write(
                f"\n## Capability request approved [{req_id}] — {now()}\n"
                f"- Request ID: {req_id}\n"
                f"- Kind: {kind}\n"
                f"- Summary: {summary}\n"
                f"- Reason: {app_reason}\n"
                f"- Action: Capability approved and granted by human administrator.\n\n"
            )
    except OSError:
        pass

    try:
        inbox_path = ws / "state" / "human_input.jsonl"
        inbox_path.parent.mkdir(parents=True, exist_ok=True)
        item = {
            "timestamp": now(),
            "text": f"Human approved capability request [{req_id}] '{summary}': {app_reason}",
            "kind": "decision",
            "decision": "accepted",
        }
        with inbox_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    except OSError:
        pass

    clear_pending_human_request(ws)

    if logger and hasattr(logger, "narrate"):
        logger.narrate(f"Capability request approved [{req_id}] ({summary}): {app_reason}")

    return {
        "id": req_id,
        "kind": kind,
        "summary": summary,
        "reason": app_reason,
        "approved": True,
    }


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
        self.declined_path = self.workspace / "state" / "declined_capabilities.json"
        self.logger = logger

    def _is_previously_declined(self, kind: str, summary: str, env_names: list[str] | None) -> bool:
        """Check whether a matching capability request was previously declined."""
        if not self.declined_path.exists():
            return False
        try:
            records = json.loads(self.declined_path.read_text(encoding="utf-8"))
            if not isinstance(records, list):
                return False
            norm_summary = summary.strip().lower()
            for rec in records:
                if rec.get("kind") == kind:
                    if env_names and rec.get("env_names"):
                        if any(e in rec.get("env_names", []) for e in env_names):
                            return True
                    s2 = str(rec.get("summary", "")).strip().lower()
                    if norm_summary and s2 and (norm_summary == s2 or norm_summary in s2 or s2 in norm_summary):
                        return True
        except (OSError, json.JSONDecodeError):
            pass
        return False

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

        if self._is_previously_declined(kind, summary, env_names):
            self.logger.narrate(f"Skipping capability request for '{summary}': previously declined by administrator.")
            return {
                "ok": False,
                "status": "previously_declined",
                "path": str(self.path),
                "halted": False,
                "error": (
                    f"Capability '{summary}' was previously declined by the human administrator. "
                    "Proceed without it and record it as unavailable in your environment map."
                ),
            }

        import uuid
        req_id = f"req-{uuid.uuid4().hex[:6]}"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            f"## Pending capability request [{req_id}] — {now()}",
            f"- Request ID: {req_id}",
            f"- Kind: {kind}", f"- Summary: {self.logger.redactor.text(summary)[:500]}",
            f"- Reason: {self.logger.redactor.text(reason)[:1_000]}",
            f"- Provider/service: {provider or 'not specified'}",
            f"- Environment variable names: {', '.join(env_names or []) or 'none'}",
            f"- Official page: {signup_url or 'not specified'}",
            f"- Note for the human administrator (Human action required): Approve this request by editing host configuration or environment yourself, then run /approve {req_id} (or /resume).",
            "- Notice for the human: SELF cannot create accounts, edit host configuration, open host ports, add mounts, send email, or make financial actions.", "",
        ]
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines))
        self.logger.log("capability_requested", kind=kind, provider=provider, env_names=env_names or [], official_page=signup_url)
        if halt:
            hr_lines = [
                "# Pending Human Action / Capability Request",
                "",
                f"### Request ID: {req_id}",
                f"- Task / Request ID: `{req_id}`",
                f"- Kind: {kind}",
                f"- Summary: {self.logger.redactor.text(summary)[:500]}",
                f"- Reason: {self.logger.redactor.text(reason)[:1_000]}",
                f"- Provider/service: {provider or 'not specified'}",
                f"- Environment variable names: {', '.join(env_names or []) or 'none'}",
                f"- Official page: {signup_url or 'not specified'}",
                "",
                "## How to Approve and Resume",
                "1. Perform any required host action (e.g. host socket mount, setting environment variable, or reviewing patch).",
                f"2. In the TUI chat box, approve this request by typing:",
                f"   `/approve {req_id}`",
                "   (or type `/resume`, or delete this `HUMAN_REQUEST.md` file).",
                "   SELF will immediately unpause the task, recalculate priority, and execute it after finishing its current cycle.",
                "",
                "## How to Decline",
                "If you do NOT want to grant this capability or wish SELF to proceed without it:",
                f"1. In the TUI chat box, decline this request by typing:",
                f"   `/decline {req_id}`",
                "   (or type `/decline [reason]`).",
                "   SELF will record this decision in state/declined_capabilities.json, never ask again, and continue with other goals.",
                "",
            ]
            self.human_request.write_text("\n".join(hr_lines), encoding="utf-8")
            try:
                self.harness_request.parent.mkdir(parents=True, exist_ok=True)
                payload = {
                    "id": req_id,
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
        return {"ok": False, "status": "human_approval_required", "path": str(self.path), "halted": halt, "id": req_id}


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

