"""Daily token budget tracking and network error classification."""
from __future__ import annotations

import os
import json
from typing import Any

from agent.infra.event_log import EventLogger
from agent.infra.hardening import DailyTokenLedger
from agent.llm.client.result import LLMResult


class BudgetExceeded(RuntimeError):
    """Signal that a model call would exceed its token allowance."""

    def __init__(self, message: str, *, kind: str = "run") -> None:
        super().__init__(message)
        self.kind = kind


def _is_network_error(exc: Exception) -> bool:
    """Identify transient transport/connection errors that should not count as model failures."""
    if isinstance(exc, (ConnectionError, TimeoutError, OSError)):
        return True
    name = type(exc).__name__
    if name in {"APIConnectionError", "ConnectError", "ConnectTimeout", "ReadTimeout", "TimeoutException", "NetworkError"}:
        return True
    msg = str(exc).casefold()
    return any(marker in msg for marker in (
        "connection error", "connection refused", "connecterror", "connection reset",
        "network is unreachable", "timed out", "timeout", "remoteprotocolerror",
    ))


class BudgetedLLM:
    """Daily token budget tracking; mid-call exhaustion completes and refuses next call."""

    def __init__(
        self,
        client: Any,
        logger: EventLogger,
        token_budget: int | None = None,
        daily_ledger: DailyTokenLedger | None = None,
        *,
        adaptive_budget: bool = False,
        max_token_budget: int | None = None,
    ) -> None:
        self.client = client
        self.logger = logger
        # token_budget, adaptive_budget, max_token_budget are ignored;
        # daily_ledger is the only active token limit.
        self.token_budget = None
        self.tokens_used = 0
        self.daily_ledger = daily_ledger

    def call(self, *, system: str, messages: list[dict[str, Any]],
             tools: list[dict[str, Any]], max_tokens: int,
             model: str | None = None, min_output_tokens: int = 64) -> LLMResult:
        """Send a model request bounded by the model output ceiling and daily allowance."""
        if model is not None and model not in getattr(self.client, "available_models", []):
            raise ValueError("Model is not in the configured allowlist")
        payload = json.dumps({"system": system, "messages": messages, "tools": tools}, ensure_ascii=False)
        reserved_input = (len(payload.encode("utf-8")) + 1) // 2 + 512
        expected_output = min(max_tokens, int(os.getenv("SELF_EXPECTED_OUTPUT_TOKENS", "1024")))
        reservation_estimate = reserved_input + expected_output

        actual_reservation = 0
        if self.daily_ledger is not None:
            available = self.daily_ledger.available_tokens()
            if available <= 0:
                raise BudgetExceeded("Daily token limit reached", kind="daily")
            actual_reservation = reservation_estimate
            if not self.daily_ledger.reserve(actual_reservation):
                raise BudgetExceeded("Daily token limit reached", kind="daily")

        try:
            call_args = {"system": system, "messages": messages, "tools": tools, "max_tokens": max_tokens}
            if model is not None:
                call_args["model"] = model
            result = self.client.call(**call_args)
        except Exception as exc:
            if _is_network_error(exc):
                if self.daily_ledger is not None and actual_reservation > 0:
                    self.daily_ledger.settle(actual_reservation, 0)
                self.logger.log("token_spend", usage_known=True, reserved_tokens=actual_reservation,
                                tokens_released=actual_reservation,
                                max_output_tokens=max_tokens,
                                tokens_used=self.tokens_used,
                                daily_token_budget=self.daily_ledger.cap if self.daily_ledger else 0,
                                reason="network_error_released")
                raise
            self.tokens_used += actual_reservation
            if self.daily_ledger is not None and actual_reservation > 0:
                self.daily_ledger.settle(actual_reservation, None)
            self.logger.log("token_spend", usage_known=False, reserved_tokens=actual_reservation,
                            max_output_tokens=max_tokens,
                            tokens_used=self.tokens_used,
                            daily_token_budget=self.daily_ledger.cap if self.daily_ledger else 0)
            raise

        self.tokens_used += result.total_tokens
        result.max_output_tokens = max_tokens
        if self.daily_ledger is not None:
            self.daily_ledger.settle(actual_reservation, result.total_tokens)
        self.logger.log("token_spend", usage_known=True, call_input_tokens=result.input_tokens,
                        call_output_tokens=result.output_tokens, max_output_tokens=max_tokens,
                        tokens_used=self.tokens_used,
                        daily_token_budget=self.daily_ledger.cap if self.daily_ledger else 0)
        return result


def call_with_minimum(llm: Any, minimum: int, **kwargs: Any) -> LLMResult:
    """Keep probe/decision calls out of the provider when a run cap is too small."""
    if isinstance(llm, BudgetedLLM):
        return llm.call(min_output_tokens=minimum, **kwargs)
    return llm.call(**kwargs)
