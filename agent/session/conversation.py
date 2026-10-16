"""Bounded, read-only human conversation workers."""
from __future__ import annotations

import json
import os
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from agent.infra.event_log import EventLogger
from agent.infra.hardening import DailyTokenLedger
from agent.llm.llm import BudgetedLLM, LLMClient


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ConversationManager:
    """Answers ordinary human messages without entering the autonomous inbox."""

    def __init__(self, workspace: str | Path, logger: EventLogger,
                 ledger: DailyTokenLedger, llm_client: Any | None = None,
                 *, max_workers: int | None = None, max_tokens: int = 1_200) -> None:
        self.workspace = Path(workspace)
        self.logger = logger
        self.ledger = ledger
        self.client = llm_client
        self.max_workers = max(1, int(max_workers or os.getenv("SELF_MAX_CONVERSATION_WORKERS", "2")))
        configured_tokens = int(os.getenv("SELF_CONVERSATION_MAX_TOKENS", str(max_tokens)))
        self.max_tokens = max(256, min(configured_tokens, 4_096))
        self.executor = ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="self-chat")
        self.path = self.workspace / "state" / "conversation_threads.jsonl"
        self._lock = threading.Lock()

    def _append(self, record: dict[str, Any]) -> None:
        safe = self.logger.redactor.value(record)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            try:
                records = [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines()[-399:]]
            except (OSError, json.JSONDecodeError):
                records = []
            records.append(safe)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in records[-400:]) + "\n", encoding="utf-8")
            os.replace(temporary, self.path)

    def submit(self, text: str, context_provider: Callable[[], str],
               on_result: Callable[[str, str, str], None]) -> str:
        thread_id = uuid.uuid4().hex
        self._append({"timestamp": _now(), "thread_id": thread_id, "role": "human", "text": text})
        self.logger.log("conversation_thread_started", thread_id=thread_id, chars=len(text))
        future = self.executor.submit(self._answer, thread_id, text, context_provider)

        def finished(done: Future[Any]) -> None:
            try:
                response = done.result()
                on_result(thread_id, response, "assistant")
            except Exception as exc:
                message = f"I could not answer this conversation thread because of {type(exc).__name__}. Autonomous work is continuing."
                self.logger.log("conversation_thread_failed", thread_id=thread_id, error_type=type(exc).__name__)
                on_result(thread_id, message, "error")

        future.add_done_callback(finished)
        return thread_id

    def _answer(self, thread_id: str, text: str, context_provider: Callable[[], str]) -> str:
        if self.client is None:
            self.client = LLMClient(self.logger)
        context = context_provider()[:12_000]
        system_prompt = (
            "You are SELF's read-only conversation assistant. Answer the human clearly using only the supplied "
            "durable state and recent activity. Do not call tools, edit files, change plans, create tools, or "
            "claim that you performed an action. If work is pending, explain its status and distinguish facts "
            "from uncertainty. Keep the answer concise."
        )
        message = f"Context:\n{context}\n\nHuman message:\n{text}"
        # BudgetedLLM's allowance covers both its conservative input estimate
        # and output tokens. A response-only budget of 1200 would reject every
        # normal conversation once the live state snapshot is included.
        payload = json.dumps(
            {"system": system_prompt, "messages": [{"role": "user", "content": message}], "tools": []},
            ensure_ascii=False,
        )
        input_reservation = (len(payload.encode("utf-8")) + 1) // 2 + 512
        call_budget = input_reservation + self.max_tokens + 128
        budget = BudgetedLLM(self.client, self.logger, call_budget, self.ledger, adaptive_budget=False)
        result = budget.call(
            system=system_prompt,
            messages=[{"role": "user", "content": message}],
            tools=[], max_tokens=self.max_tokens,
        )
        response = "\n".join(str(block.get("text", "")).strip() for block in result.content
                              if block.get("type") == "text" and str(block.get("text", "")).strip()).strip()
        if not response:
            response = "I do not have a textual answer yet, but the autonomous work is continuing."
        response = self.logger.redactor.text(response[:12_000])
        self._append({"timestamp": _now(), "thread_id": thread_id, "role": "assistant", "text": response})
        self.logger.log("conversation_thread_completed", thread_id=thread_id, chars=len(response))
        return response

    def close(self) -> None:
        self.executor.shutdown(wait=False, cancel_futures=False)
