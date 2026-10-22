"""Crash-safe wake/sleep state, session handoffs, and a human input inbox."""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from agent.infra.event_log import EventLogger


from agent.learning.plan import consolidate_plan_items


HANDOFF_CAP = 6_000


def now() -> str:
    """Return the current UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


class HumanInbox:
    """Append-only messages with a tiny cursor so a restart loses no human input."""

    def __init__(self, workspace: str | Path, logger: EventLogger) -> None:
        state = Path(workspace) / "state"
        self.path, self.cursor_path, self.logger = state / "human_input.jsonl", state / "human_input_cursor.json", logger

    def add(self, text: str, kind: str = "goal") -> None:
        """Append a human message to the durable inbox."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": now(),
            "text": self.logger.redactor.text(text)[:4_000],
            "kind": str(kind),
        }
        fd = os.open(self.path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            os.write(fd, (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8"))
        finally:
            os.close(fd)
        self.logger.log("human_input_received", chars=len(record["text"]), kind=str(kind))

    def consume(self) -> list[str]:
        """Return unread human messages and advance the inbox cursor."""
        try:
            offset = int(json.loads(self.cursor_path.read_text(encoding="utf-8")).get("line", 0))
        except (OSError, json.JSONDecodeError, ValueError):
            offset = 0
        try:
            lines = self.path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []
        values = []
        for line in lines[offset:]:
            try:
                value = json.loads(line).get("text", "")
            except json.JSONDecodeError:
                continue
            if value:
                values.append(self.logger.redactor.text(value))
        temporary = self.cursor_path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"line": len(lines), "updated_at": now()}) + "\n", encoding="utf-8")
        os.replace(temporary, self.cursor_path)
        return values


class SessionStore:
    """Persist session checkpoints and handoff state."""

    def __init__(self, workspace: str | Path, logger: EventLogger, handoff_cap: int = HANDOFF_CAP) -> None:
        self.workspace, self.logger, self.handoff_cap = Path(workspace), logger, max(2_000, handoff_cap)
        self.state = self.workspace / "state"
        self.sessions = self.state / "sessions.jsonl"
        self.active = self.state / "active_session.json"
        self.handoff = self.state / "handoff.json"
        self.handoff_backup = self.state / "handoff_last_good.json"
        self.journal = self.state / "journal.md"

    def _atomic_json(self, path: Path, value: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.logger.redactor.value(value), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, path)

    def _read_json(self, path: Path) -> dict[str, Any] | None:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else None
        except (OSError, json.JSONDecodeError):
            return None

    def load_handoff(self) -> tuple[dict[str, Any], bool]:
        """Load a resumable handoff record, if one exists."""
        value = self._read_json(self.handoff)
        if value is not None:
            encoded = json.dumps(self.logger.redactor.value(value), ensure_ascii=False)
            if len(encoded.encode("utf-8")) > self.handoff_cap:
                bounded = self._bounded_handoff(value)
                self._atomic_json(self.handoff, bounded)
                return bounded, False
            return value, False
        backup = self._read_json(self.handoff_backup)
        if backup is not None:
            self.logger.log("handoff_recovered_from_backup")
            encoded = json.dumps(self.logger.redactor.value(backup), ensure_ascii=False)
            if len(encoded.encode("utf-8")) > self.handoff_cap:
                bounded = self._bounded_handoff(backup)
                self._atomic_json(self.handoff, bounded)
                return bounded, True
            return backup, True
        return {}, self.handoff.exists()

    def start(self) -> dict[str, Any]:
        """Create a persistent session record and initial checkpoint."""
        self.state.mkdir(parents=True, exist_ok=True)
        previous_active = self._read_json(self.active)
        crash = None
        if previous_active and previous_active.get("status") == "running":
            crash = previous_active
            self._append_session({
                "session_id": previous_active.get("session_id"), "start_time": previous_active.get("start_time"),
                "end_time": now(), "end_reason": "crash", "iteration_count": previous_active.get("iteration_count", 0),
                "token_spend": previous_active.get("token_spend", 0), "probable_cause": "Container/process ended without a clean session finish.",
            })
            self.logger.log("session_crash_recovered", session_id=previous_active.get("session_id"))
        handoff, recovered_backup = self.load_handoff()
        session_id = uuid.uuid4().hex
        active = {"session_id": session_id, "start_time": now(), "status": "running", "iteration_count": 0, "token_spend": 0}
        self._atomic_json(self.active, active)
        self.logger.log("session_started", session_id=session_id, recovered_crash=bool(crash), recovered_handoff_backup=recovered_backup)
        return {"session_id": session_id, "handoff": handoff, "crash": crash, "handoff_recovered": recovered_backup}

    def checkpoint(self, session_id: str, handoff: dict[str, Any], iteration_count: int, token_spend: int) -> None:
        """Persist the current session state for recovery."""
        handoff = self._bounded_handoff(handoff)
        self._atomic_json(self.handoff, handoff)
        self._atomic_json(self.handoff_backup, handoff)
        self._atomic_json(self.active, {"session_id": session_id, "start_time": self._read_json(self.active).get("start_time", now()) if self._read_json(self.active) else now(), "status": "running", "iteration_count": iteration_count, "token_spend": token_spend, "last_checkpoint": now()})
        self.logger.log("session_handoff_checkpoint", session_id=session_id, iteration_count=iteration_count)

    def finish(self, session_id: str, handoff: dict[str, Any], iteration_count: int, token_spend: int, end_reason: str) -> None:
        """Mark a session complete and persist its final state."""
        self.checkpoint(session_id, handoff, iteration_count, token_spend)
        active = self._read_json(self.active) or {}
        self._append_session({"session_id": session_id, "start_time": active.get("start_time", now()), "end_time": now(), "end_reason": end_reason, "iteration_count": iteration_count, "token_spend": token_spend})
        self._append_journal(handoff, session_id, end_reason)
        self._atomic_json(self.active, {"session_id": session_id, "status": "completed", "end_reason": end_reason, "ended_at": now()})
        self.logger.log("session_finished", session_id=session_id, end_reason=end_reason, iteration_count=iteration_count)

    def _append_session(self, record: dict[str, Any]) -> None:
        fd = os.open(self.sessions, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            os.write(fd, (json.dumps(self.logger.redactor.value(record), ensure_ascii=False) + "\n").encode("utf-8"))
        finally:
            os.close(fd)

    def _append_journal(self, handoff: dict[str, Any], session_id: str, end_reason: str) -> None:
        entry = [
            f"## {now()} — session {session_id}", "",
            handoff.get("summary", "No summary was available."), "",
            "### Discoveries", *[f"- {item}" for item in handoff.get("discoveries", [])], "",
            "### Lessons", *[f"- {item}" for item in handoff.get("failures_and_lessons", [])], "",
            "### Next plan", *[f"- [{item.get('priority', 3)}] {item.get('step', '')}" for item in handoff.get("plan", [])], "",
            f"End reason: {end_reason}", "",
        ]
        with self.journal.open("a", encoding="utf-8") as handle:
            handle.write(self.logger.redactor.text("\n".join(entry)))

    def _bounded_handoff(self, handoff: dict[str, Any]) -> dict[str, Any]:
        safe = self.logger.redactor.value(handoff)
        encoded = json.dumps(safe, ensure_ascii=False)
        if len(encoded.encode("utf-8")) <= self.handoff_cap:
            return safe
        # Session journal retains the full human-readable record. Retain an
        # explicit compression marker rather than silently losing detail.
        overflow = self.state / "handoff_overflow.json"
        self._atomic_json(overflow, safe)
        compact = {
            "summary": str(safe.get("summary", ""))[:2_000],
            "long_term_summary": str(safe.get("long_term_summary", ""))[:3_000] or "Compression pending an LLM reflection; full checkpoint retained in handoff_overflow.json.",
            "discoveries": list(safe.get("discoveries", []))[-8:], "tools_created": list(safe.get("tools_created", []))[-8:],
            "failures_and_lessons": list(safe.get("failures_and_lessons", []))[-8:], "open_questions": list(safe.get("open_questions", []))[-8:],
            "plan": consolidate_plan_items(list(safe.get("plan", [])), max_items=8),
            "pending_human_inputs": list(safe.get("pending_human_inputs", safe.get("pending_human_requests", [])))[:8],
            "mood_of_run": safe.get("mood_of_run", "exploring"), "compression_pending": True,
        }
        # Guarantee the on-disk handoff cap even when an error message is
        # unusually large. The unabridged checkpoint remains in overflow and
        # journal.md, so this is explicit compaction rather than silent loss.
        list_fields = ("discoveries", "tools_created", "failures_and_lessons", "open_questions", "pending_human_inputs")
        while len(json.dumps(compact, ensure_ascii=False).encode("utf-8")) > self.handoff_cap:
            candidate = max(list_fields, key=lambda field: len(compact.get(field, [])))
            if compact.get(candidate):
                compact[candidate].pop()
                continue
            if len(compact.get("plan", [])) > 2:
                compact["plan"] = consolidate_plan_items(compact["plan"], max_items=max(2, len(compact["plan"]) - 1))
                continue
            if len(str(compact["long_term_summary"])) > 200:
                compact["long_term_summary"] = str(compact["long_term_summary"])[:-200]
                continue
            compact["summary"] = str(compact["summary"])[:200]
            break
        self.logger.log("handoff_compacted", overflow_path=str(overflow))
        return compact


def default_plan() -> list[dict[str, Any]]:
    """Return the initial persistent plan."""
    return [{"step": "Inspect current state and verify one environment fact.", "why": "Maintain an accurate model of the container.", "priority": 2, "status": "todo"}]
