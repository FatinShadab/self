"""Read-only background reflections initiated by SELF after meaningful work."""
from __future__ import annotations

import json
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from event_log import EventLogger
from hardening import DailyTokenLedger
from llm import BudgetExceeded, BudgetedLLM, LLMClient
from model_decisions import ModelDecisions
from file_lock import locked_file


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ReflectionManager:
    """Runs one optional, bounded reflection without interrupting exploration."""

    def __init__(
        self,
        workspace: str | Path,
        logger: EventLogger,
        ledger: DailyTokenLedger,
        llm_client: Any | None = None,
        *,
        enabled: bool = True,
        max_per_session: int = 3,
        min_cycles: int = 3,
        max_tokens: int = 384,
        stop_provider: Callable[[], bool] | None = None,
    ) -> None:
        self.workspace = Path(workspace)
        self.logger = logger
        self.ledger = ledger
        self.client = llm_client
        self.enabled = enabled
        self.max_per_session = max(1, min(int(max_per_session), 20))
        self.min_cycles = max(1, min(int(min_cycles), 100))
        self.max_tokens = max(64, min(int(max_tokens), 1_024))
        self.stop_provider = stop_provider
        self.path = self.workspace / "state" / "reflection_threads.jsonl"
        self.state_path = self.workspace / "state" / "reflection_state.json"
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="self-reflection")
        self._active = False
        self._pending: dict[str, Any] | None = None
        self._state = self._load_state()

    def _load_state(self) -> dict[str, Any]:
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                return value
        except (OSError, json.JSONDecodeError):
            pass
        return {}

    def _save_state_locked(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        safe = self.logger.redactor.value(self._state)
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(safe, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, self.state_path)

    def _append_locked(self, record: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        safe = self.logger.redactor.value(record)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(safe, ensure_ascii=False) + "\n")

    def begin_session(self, session_id: str) -> None:
        with self._lock:
            if self._state.get("session_id") == session_id:
                return
            self._state["session_id"] = session_id
            self._state["posted_in_session"] = 0
            self._state["last_posted_cycle"] = 0
            self._save_state_locked()

    def open_question(self) -> dict[str, str] | None:
        with self._lock:
            thread_id = str(self._state.get("open_thread_id", "")).strip()
            question = str(self._state.get("open_question", "")).strip()
            if not thread_id or not question:
                return None
            return {"thread_id": thread_id, "question": question}

    def submit(
        self,
        *,
        session_id: str,
        cycle: int,
        report: str,
        actions: list[dict[str, Any]],
        triggers: list[str],
        context_provider: Callable[[int, str, list[dict[str, Any]], list[str]], str],
        on_result: Callable[[dict[str, Any]], None],
    ) -> bool:
        """Queue a candidate and retain only the newest one while busy."""
        if not self.enabled or not triggers or self._stopped():
            return False
        candidate = {
            "session_id": session_id,
            "cycle": int(cycle),
            "report": self.logger.redactor.text(report)[:4_000],
            "actions": self.logger.redactor.value(actions),
            "triggers": [self.logger.redactor.text(value)[:100] for value in triggers],
            "context_provider": context_provider,
            "on_result": on_result,
        }
        with self._lock:
            self._begin_session_locked(session_id)
            if self._state.get("open_thread_id"):
                self.logger.log("reflection_skipped", cycle=cycle, reason="open_question")
                return False
            if int(self._state.get("posted_in_session", 0)) >= self.max_per_session:
                self.logger.log("reflection_skipped", cycle=cycle, reason="session_limit")
                return False
            last_cycle = int(self._state.get("last_posted_cycle", 0) or 0)
            if last_cycle and int(cycle) - last_cycle < self.min_cycles:
                self.logger.log("reflection_skipped", cycle=cycle, reason="cycle_throttle")
                return False
            if self._active:
                self._pending = candidate
                self.logger.log("reflection_coalesced", cycle=cycle, triggers=candidate["triggers"])
                return True
            self._active = True
            self._executor.submit(self._run_candidate, candidate)
            return True

    def _begin_session_locked(self, session_id: str) -> None:
        if self._state.get("session_id") != session_id:
            self._state["session_id"] = session_id
            self._state["posted_in_session"] = 0
            self._state["last_posted_cycle"] = 0
            self._save_state_locked()

    def _run_candidate(self, candidate: dict[str, Any]) -> None:
        try:
            with locked_file(self.workspace / "state" / "eval_session.lock", shared=True):
                result = self._reflect(candidate)
                if result is not None:
                    candidate["on_result"](result)
        except Exception as exc:
            self.logger.log("reflection_failed", cycle=candidate["cycle"], error_type=type(exc).__name__)
        finally:
            next_candidate = None
            with self._lock:
                self._active = False
                if self._pending is not None:
                    pending = self._pending
                    self._pending = None
                    last_cycle = int(self._state.get("last_posted_cycle", 0) or 0)
                    allowed = (
                        not self._state.get("open_thread_id")
                        and self._state.get("session_id") == pending["session_id"]
                        and int(self._state.get("posted_in_session", 0)) < self.max_per_session
                        and (not last_cycle or int(pending["cycle"]) - last_cycle >= self.min_cycles)
                    )
                    if allowed:
                        next_candidate = pending
                        self._active = True
                    else:
                        self.logger.log("reflection_skipped", cycle=pending["cycle"], reason="post_completion_throttle")
            if next_candidate is not None:
                self._executor.submit(self._run_candidate, next_candidate)

    def _stopped(self) -> bool:
        try:
            return bool(self.stop_provider and self.stop_provider())
        except Exception:
            return True

    def _reflect(self, candidate: dict[str, Any]) -> dict[str, Any] | None:
        if self._stopped():
            self.logger.log("reflection_skipped", cycle=candidate["cycle"], reason="stop_requested")
            return None
        context = str(candidate["context_provider"](
            candidate["cycle"], candidate["report"], candidate["actions"], candidate["triggers"],
        ))[:8_000]
        system = (
            "You are SELF's read-only background reflection worker. Assess whether the supplied, recorded "
            "exploration evidence offers a useful concise observation or question for the human. Return ONLY JSON: "
            '{"post": boolean, "message": string, "question": string|null}. '
            "Post only when it is genuinely useful. Ground every claim in supplied state; distinguish uncertainty. "
            "You may reflect on SELF's operational purpose, limits, observed behavior, and human preferences. "
            "Do not claim consciousness, emotions, desires, needs, subjective experience, sentience, a biological "
            "body, or hidden memory. Do not request credentials, host changes, purchases, or other capability approval. "
            "Do not call tools or propose actions. Keep message under 700 characters and question under 300 characters."
        )
        if self.client is None:
            self.client = LLMClient(self.logger)
        payload = json.dumps({"system": system, "messages": [{"role": "user", "content": context}], "tools": []}, ensure_ascii=False)
        input_reservation = (len(payload.encode("utf-8")) + 1) // 2 + 512
        if self.ledger.available_tokens() - input_reservation < 64:
            self.logger.log("reflection_skipped", cycle=candidate["cycle"], reason="budget")
            return None
        call_budget = input_reservation + self.max_tokens + 128
        budget = BudgetedLLM(self.client, self.logger, call_budget, self.ledger, adaptive_budget=False)
        try:
            reflection_model = None
            model_registry = getattr(self.client, "model_registry", None)
            if model_registry is not None:
                decision_budget = BudgetedLLM(self.client, self.logger, None, self.ledger)
                reflection_model = ModelDecisions(
                    self.workspace, self.logger, model_registry, decision_budget,
                    candidate["session_id"]).decide_model(
                        f"Background reflection after cycle {candidate['cycle']}: {context[:400]}",
                        moment="background_reflection")
            model_arg = {"model": reflection_model} if reflection_model is not None else {}
            response = budget.call(system=system, messages=[{"role": "user", "content": context}],
                                   tools=[], max_tokens=self.max_tokens, **model_arg)
        except BudgetExceeded:
            self.logger.log("reflection_skipped", cycle=candidate["cycle"], reason="budget")
            return None
        text = "\n".join(
            str(block.get("text", "")).strip()
            for block in response.content
            if block.get("type") == "text" and str(block.get("text", "")).strip()
        ).strip()
        if text.startswith("```"):
            text = text.strip("`").removeprefix("json").strip()
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            self.logger.log("reflection_skipped", cycle=candidate["cycle"], reason="malformed_response")
            return None
        if not isinstance(value, dict) or not isinstance(value.get("post"), bool) or not value["post"]:
            self.logger.log("reflection_declined", cycle=candidate["cycle"])
            return None
        if not isinstance(value.get("message"), str) or (value.get("question") is not None and not isinstance(value.get("question"), str)):
            self.logger.log("reflection_skipped", cycle=candidate["cycle"], reason="invalid_response_shape")
            return None
        message = self.logger.redactor.text(value["message"].strip())[:700]
        raw_question = value.get("question")
        question = self.logger.redactor.text(raw_question.strip())[:300] if raw_question else ""
        if not message:
            self.logger.log("reflection_skipped", cycle=candidate["cycle"], reason="empty_message")
            return None
        unsafe_claim = any(marker in f"{message}\n{question}".casefold() for marker in (
            "i feel", "i want", "i need", "i desire", "i experience",
            "my feelings", "my needs", "my desires", "sentient", "sentience", "consciousness",
            "i am conscious", "i am alive",
        ))
        if unsafe_claim:
            self.logger.log("reflection_skipped", cycle=candidate["cycle"], reason="unsupported_inner_state_claim")
            return None
        thread_id = uuid.uuid4().hex
        display = message + (f"\n\nQuestion: {question}" if question else "")
        record = {
            "timestamp": _now(), "thread_id": thread_id, "role": "agent", "kind": "reflection",
            "session_id": candidate["session_id"], "cycle": candidate["cycle"],
            "triggers": candidate["triggers"], "message": message, "question": question,
        }
        with self._lock:
            if self._stopped():
                self.logger.log("reflection_skipped", cycle=candidate["cycle"], reason="stop_requested")
                return None
            if self._state.get("session_id") != candidate["session_id"]:
                self.logger.log("reflection_skipped", cycle=candidate["cycle"], reason="stale_session")
                return None
            # A reply may have arrived while the LLM call was in flight.
            if self._state.get("open_thread_id"):
                self.logger.log("reflection_skipped", cycle=candidate["cycle"], reason="open_question")
                return None
            self._append_locked(record)
            self._state["posted_in_session"] = int(self._state.get("posted_in_session", 0)) + 1
            self._state["last_posted_cycle"] = candidate["cycle"]
            if question:
                self._state["open_thread_id"] = thread_id
                self._state["open_question"] = question
            self._save_state_locked()
        self.logger.log("reflection_posted", thread_id=thread_id, cycle=candidate["cycle"], has_question=bool(question))
        return {"thread_id": thread_id, "message": display, "question": question, "cycle": candidate["cycle"]}

    def record_human_reply(self, text: str) -> dict[str, str] | None:
        clean = self.logger.redactor.text(text).strip()[:4_000]
        if not clean:
            return None
        with self._lock:
            thread_id = str(self._state.get("open_thread_id", "")).strip()
            question = str(self._state.get("open_question", "")).strip()
            if not thread_id or not question:
                return None
            self._append_locked({
                "timestamp": _now(), "thread_id": thread_id, "role": "human", "kind": "reflection_reply",
                "text": clean,
            })
            self._state.pop("open_thread_id", None)
            self._state.pop("open_question", None)
            self._save_state_locked()
        self.logger.log("reflection_reply_received", thread_id=thread_id, chars=len(clean))
        return {"thread_id": thread_id, "question": question, "text": clean}

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=False)
