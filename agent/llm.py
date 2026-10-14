from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from anthropic import Anthropic

from event_log import EventLogger
from hardening import DailyTokenLedger


class BudgetExceeded(RuntimeError):
    def __init__(self, message: str, *, kind: str = "run") -> None:
        super().__init__(message)
        self.kind = kind


class BudgetedLLM:
    """One budget shared by the actor and critic; failures reserve unknown spend."""

    def __init__(
        self,
        client: Any,
        logger: EventLogger,
        token_budget: int,
        daily_ledger: DailyTokenLedger | None = None,
        *,
        adaptive_budget: bool = False,
        max_token_budget: int | None = None,
    ) -> None:
        self.client = client
        self.logger = logger
        self.token_budget = max(1, token_budget)
        self.initial_token_budget = self.token_budget
        self.adaptive_budget = adaptive_budget
        self.max_token_budget = max(self.token_budget, max_token_budget or self.token_budget)
        self.tokens_used = 0
        self.daily_ledger = daily_ledger

    def _adapt_budget(self) -> None:
        if not self.adaptive_budget or self.daily_ledger is None or self.token_budget >= self.max_token_budget:
            return
        daily_remaining = self.daily_ledger.available_tokens()
        new_budget = min(self.max_token_budget, self.tokens_used + daily_remaining)
        if new_budget <= self.token_budget:
            return
        previous = self.token_budget
        self.token_budget = new_budget
        self.logger.log(
            "run_token_budget_adapted",
            initial_budget=self.initial_token_budget,
            previous_budget=previous,
            new_budget=self.token_budget,
            daily_remaining=daily_remaining,
            max_budget=self.max_token_budget,
        )

    def call(self, *, system: str, messages: list[dict[str, Any]],
             tools: list[dict[str, Any]], max_tokens: int) -> LLMResult:
        import json
        # JSON/schema-heavy tool payloads tokenize much more densely than normal
        # prose. Reserving half the UTF-8 byte count plus a fixed margin remains
        # conservative while leaving room for a small configured run budget.
        payload = json.dumps({"system": system, "messages": messages, "tools": tools}, ensure_ascii=False)
        reserved_input = (len(payload.encode("utf-8")) + 1) // 2 + 512
        self._adapt_budget()
        allowance = min(max_tokens, self.token_budget - self.tokens_used - reserved_input)
        if allowance < 64:
            raise BudgetExceeded("Insufficient remaining budget for this actor or critic call")
        reservation = reserved_input + allowance
        if self.daily_ledger is not None and not self.daily_ledger.reserve(reservation):
            raise BudgetExceeded("Daily token budget is exhausted", kind="daily")
        try:
            result = self.client.call(system=system, messages=messages, tools=tools, max_tokens=allowance)
        except Exception:
            self.tokens_used += reservation
            if self.daily_ledger is not None:
                self.daily_ledger.settle(reservation, None)
            self.logger.log("token_spend", usage_known=False, reserved_tokens=reservation,
                            run_tokens_used=self.tokens_used, run_token_budget=self.token_budget)
            raise
        self.tokens_used += result.total_tokens
        if self.daily_ledger is not None:
            self.daily_ledger.settle(reservation, result.total_tokens)
        self.logger.log("token_spend", usage_known=True, call_input_tokens=result.input_tokens,
                        call_output_tokens=result.output_tokens, run_tokens_used=self.tokens_used,
                        run_token_budget=self.token_budget)
        return result


@dataclass
class LLMResult:
    content: list[dict[str, Any]]
    input_tokens: int
    output_tokens: int
    stop_reason: str | None
    model: str

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


def _first_env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return None


class LLMClient:
    """Thin provider boundary; Phase 5 can replace this class without changing the loop."""

    def __init__(self, logger: EventLogger, timeout: float = 120) -> None:
        self.logger = logger
        ollama_key = _first_env("OLLAMA_API_KEY", "OLLAM_API_KEY")
        anthropic_key = _first_env("ANTHROPIC_API_KEY")
        self.model = _first_env("OLLAMA_MODEL", "OLLAM_MODEL", "ANTHROPIC_MODEL") or "gpt-oss:120b-cloud"

        if ollama_key:
            self.provider = "ollama"
            self.base_url = _first_env("OLLAMA_BASE_URL", "OLLAM_BASE_URL") or "https://ollama.com"
            self._client = Anthropic(
                auth_token=ollama_key,
                base_url=self.base_url,
                timeout=timeout,
                max_retries=0,
            )
        elif anthropic_key:
            self.provider = "anthropic"
            self.base_url = _first_env("ANTHROPIC_BASE_URL") or "https://api.anthropic.com"
            self._client = Anthropic(
                api_key=anthropic_key,
                base_url=self.base_url,
                timeout=timeout,
                max_retries=0,
            )
        else:
            raise RuntimeError(
                "No LLM credential found. Set OLLAMA_API_KEY in the host-side .env file."
            )

    def call(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int,
    ) -> LLMResult:
        parsed = urlsplit(self.base_url)
        base_path = parsed.path.rstrip("/")
        endpoint_path = f"{base_path}/v1/messages" if base_path else "/v1/messages"
        self.logger.log("network_request", method="POST", host=parsed.hostname or "", path=endpoint_path)
        self.logger.log(
            "llm_call_started",
            provider=self.provider,
            model=self.model,
            message_count=len(messages),
            tool_count=len(tools),
            max_output_tokens=max_tokens,
        )
        response = None
        for attempt in range(3):
            try:
                response = self._client.messages.create(
                    model=self.model,
                    max_tokens=max_tokens,
                    system=system,
                    messages=messages,
                    tools=tools,
                )
                break
            except Exception as exc:
                status_code = getattr(exc, "status_code", None)
                retryable = status_code in {500, 502, 503, 504} or "Internal Server Error" in str(exc)
                self.logger.log(
                    "llm_call_failed",
                    provider=self.provider,
                    model=self.model,
                    error_type=type(exc).__name__,
                    error=str(exc),
                    retry_attempt=attempt + 1,
                    retryable=retryable,
                )
                if not retryable or attempt == 2:
                    raise
                time.sleep(1.5 * (attempt + 1))

        if response is None:
            raise RuntimeError("LLM provider returned no response")

        usage = response.usage
        input_tokens = sum(int(getattr(usage, field, 0) or 0) for field in
                           ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        content = [block.model_dump(exclude_none=True) for block in response.content]
        self.logger.log(
            "llm_call_completed",
            provider=self.provider,
            model=response.model,
            stop_reason=response.stop_reason,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
        )
        return LLMResult(
            content=content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            stop_reason=response.stop_reason,
            model=response.model,
        )
