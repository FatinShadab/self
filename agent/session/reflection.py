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

from agent.infra.event_log import EventLogger
from agent.infra.hardening import DailyTokenLedger
from agent.llm.llm import BudgetExceeded, BudgetedLLM, LLMClient, response_truncated
from agent.helper_models.model_decisions import ModelDecisions
from agent.infra.file_lock import locked_file
from agent.prompts.reflection import (
    BACKGROUND_REFLECTION_RETRY_NUDGE,
    BACKGROUND_REFLECTION_SYSTEM_PROMPT,
)


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
        max_tokens: int | None = None,
        stop_provider: Callable[[], bool] | None = None,
    ) -> None:
        self.workspace = Path(workspace)
        self.logger = logger
        self.ledger = ledger
        self.client = llm_client
        self.enabled = enabled
        self.max_per_session = max(1, min(int(max_per_session), 20))
        self.min_cycles = max(1, min(int(min_cycles), 100))
        self.max_tokens = int(max_tokens) if max_tokens is not None else None
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
        """Reset reflection counters when a new session begins."""
        with self._lock:
            if self._state.get("session_id") == session_id:
                return
            self._state["session_id"] = session_id
            self._state["posted_in_session"] = 0
            self._state["last_posted_cycle"] = 0
            self._save_state_locked()

    def open_question(self) -> dict[str, str] | None:
        """Return the pending reflection question, if any."""
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
        system = BACKGROUND_REFLECTION_SYSTEM_PROMPT
        if self.client is None:
            self.client = LLMClient(self.logger)
        payload = json.dumps({"system": system, "messages": [{"role": "user", "content": context}], "tools": []}, ensure_ascii=False)
        input_reservation = (len(payload.encode("utf-8")) + 1) // 2 + 512
        if self.ledger.available_tokens() - input_reservation < 64:
            self.logger.log("reflection_skipped", cycle=candidate["cycle"], reason="budget")
            return None
        model_registry = getattr(self.client, "model_registry", None)
        decisions = None
        reflection_model = None
        if model_registry is not None:
            decision_budget = BudgetedLLM(self.client, self.logger, None, self.ledger)
            decisions = ModelDecisions(
                self.workspace, self.logger, model_registry, decision_budget,
                candidate["session_id"])
            reflection_model = decisions.decide_model(
                f"Background reflection after cycle {candidate['cycle']}: {context[:400]}",
                moment="background_reflection")
        effective_model = reflection_model or getattr(self.client, "base_model", "gpt-oss:120b")
        reflection_cap = (model_registry.get_output_cap(effective_model)
                          if model_registry is not None
                          else (self.max_tokens or int(os.getenv("SELF_DEFAULT_OUTPUT_CEILING", "32768"))))
        model_arg = {"model": reflection_model} if reflection_model is not None else {}
        budget = BudgetedLLM(self.client, self.logger, None, self.ledger)

        parsed_value = None
        truncated = False
        parse_failed = False
        last_text = ""
        try:
            for attempt_num in (1, 2):
                if attempt_num == 1:
                    messages = [{"role": "user", "content": context}]
                else:
                    messages = [
                        {"role": "user", "content": context},
                        {"role": "assistant", "content": last_text[:4000]},
                        {"role": "user", "content": BACKGROUND_REFLECTION_RETRY_NUDGE}
                    ]
                response = budget.call(system=system, messages=messages,
                                       tools=[], max_tokens=reflection_cap, **model_arg)
                is_trunc = response_truncated(response, reflection_cap)
                text = "\n".join(
                    str(block.get("text", "")).strip()
                    for block in response.content
                    if block.get("type") == "text" and str(block.get("text", "")).strip()
                ).strip()
                last_text = text
                if text.startswith("```"):
                    text = text.strip("`").removeprefix("json").strip()
                try:
                    val = json.loads(text)
                    if not isinstance(val, dict):
                        raise ValueError("Reflection response is not a dict")
                    parsed_value = val
                    if is_trunc:
                        truncated = True
                    break
                except Exception:
                    truncated = is_trunc
                    parse_failed = True
                    if attempt_num == 1:
                        continue
                    break
        except BudgetExceeded:
            self.logger.log("reflection_skipped", cycle=candidate["cycle"], reason="budget")
            return None

        if model_registry is not None and truncated:
            model_registry.record_truncated_call(effective_model)
        if decisions is not None:
            decision_id = getattr(decisions, "last_checkpoint_call_id", None)
            if decision_id:
                if truncated:
                    decisions.outcomes.append(decision_id, effective_model, "checkpoint:background_reflection",
                                             "call_truncated", True, "objective",
                                             session_id=candidate["session_id"])
                if parse_failed:
                    decisions.outcomes.append(decision_id, effective_model, "checkpoint:background_reflection",
                                             "output_parse_failed", True, "objective",
                                             session_id=candidate["session_id"])

        if parsed_value is None:
            self.logger.log("reflection_skipped", cycle=candidate["cycle"], reason="malformed_response")
            return None
        value = parsed_value
        if not isinstance(value.get("post"), bool) or not value["post"]:
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
        """Persist a reply to the open question and clear its pending state."""
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
        """Shut down the reflection executor without waiting for active work."""
        self._executor.shutdown(wait=False, cancel_futures=False)
