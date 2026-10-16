"""SELF llm module."""
from __future__ import annotations

import os
import json
import re
from threading import Lock
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from anthropic import Anthropic

from agent.infra.event_log import EventLogger
from agent.infra.provider_calls import reserve_provider_call
from agent.infra.hardening import DailyTokenLedger
from agent.llm.model_registry import ModelRegistry


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
        token_budget: int | None,
        daily_ledger: DailyTokenLedger | None = None,
        *,
        adaptive_budget: bool = False,
        max_token_budget: int | None = None,
    ) -> None:
        self.client = client
        self.logger = logger
        # None means that this wrapper has no per-run ceiling. The daily
        # ledger, when present, remains the only aggregate token limit.
        self.token_budget = max(1, token_budget) if token_budget is not None else None
        self.initial_token_budget = self.token_budget
        self.adaptive_budget = adaptive_budget
        self.max_token_budget = (
            max(self.token_budget, max_token_budget or self.token_budget)
            if self.token_budget is not None else None
        )
        self.tokens_used = 0
        self.daily_ledger = daily_ledger

    def _adapt_budget(self) -> None:
        if (not self.adaptive_budget or self.daily_ledger is None or
                self.token_budget is None or self.max_token_budget is None or
                self.token_budget >= self.max_token_budget):
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
             tools: list[dict[str, Any]], max_tokens: int,
             model: str | None = None, min_output_tokens: int = 64) -> LLMResult:
        if model is not None and model not in getattr(self.client, "available_models", []):
            raise ValueError("Model is not in the configured allowlist")
        import json
        # JSON/schema-heavy tool payloads tokenize much more densely than normal
        # prose. Reserving half the UTF-8 byte count plus a fixed margin remains
        # conservative while leaving room for a small configured run budget.
        payload = json.dumps({"system": system, "messages": messages, "tools": tools}, ensure_ascii=False)
        reserved_input = (len(payload.encode("utf-8")) + 1) // 2 + 512
        self._adapt_budget()
        if self.token_budget is None:
            # Daily-only mode: reserve the prompt first, then spend as much of
            # the remaining daily allowance as this individual call requests.
            daily_remaining = self.daily_ledger.available_tokens() if self.daily_ledger is not None else max_tokens + reserved_input
            allowance = min(max_tokens, daily_remaining - reserved_input)
        else:
            allowance = min(max_tokens, self.token_budget - self.tokens_used - reserved_input)
        if allowance < min_output_tokens:
            kind = "daily" if self.token_budget is None else "run"
            raise BudgetExceeded("Insufficient remaining budget for the minimum output cap", kind=kind)
        reservation = reserved_input + allowance
        if self.daily_ledger is not None and not self.daily_ledger.reserve(reservation):
            raise BudgetExceeded("Daily token budget is exhausted", kind="daily")
        try:
            call_args = {"system": system, "messages": messages, "tools": tools, "max_tokens": allowance}
            if model is not None:
                call_args["model"] = model
            result = self.client.call(**call_args)
        except Exception:
            self.tokens_used += reservation
            if self.daily_ledger is not None:
                self.daily_ledger.settle(reservation, None)
            self.logger.log("token_spend", usage_known=False, reserved_tokens=reservation,
                            effective_cap=allowance,
                            run_tokens_used=self.tokens_used,
                            run_token_budget=self.token_budget if self.token_budget is not None else (self.daily_ledger.cap if self.daily_ledger else 0),
                            run_budget_mode="per_run" if self.token_budget is not None else "daily_only")
            raise
        self.tokens_used += result.total_tokens
        result.max_output_tokens = allowance
        if self.daily_ledger is not None:
            self.daily_ledger.settle(reservation, result.total_tokens)
        self.logger.log("token_spend", usage_known=True, call_input_tokens=result.input_tokens,
                        call_output_tokens=result.output_tokens, effective_cap=allowance,
                        run_tokens_used=self.tokens_used,
                        run_token_budget=self.token_budget if self.token_budget is not None else (self.daily_ledger.cap if self.daily_ledger else 0),
                        run_budget_mode="per_run" if self.token_budget is not None else "daily_only")
        return result


@dataclass
class LLMResult:
    content: list[dict[str, Any]]
    input_tokens: int
    output_tokens: int
    stop_reason: str | None
    model: str
    max_output_tokens: int | None = None

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


def response_truncated(result: LLMResult, requested_cap: int) -> bool:
    """Detect provider length stops, including hidden thinking token use."""
    reason = str(result.stop_reason or "").casefold()
    cap = result.max_output_tokens or requested_cap
    return (reason in {"max_tokens", "max_output_tokens", "length", "token_limit"}
            or reason.startswith("max_tokens") or result.output_tokens >= cap)


def call_with_minimum(llm: Any, minimum: int, **kwargs: Any) -> LLMResult:
    """Keep probe/decision calls out of the provider when a run cap is too small."""
    if isinstance(llm, BudgetedLLM):
        return llm.call(min_output_tokens=minimum, **kwargs)
    return llm.call(**kwargs)


def _first_env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return None


def _env_key_list(*names: str) -> list[str]:
    """Read comma-, semicolon-, newline-, or JSON-array-separated keys."""
    keys: list[str] = []
    for name in names:
        raw = os.getenv(name, "").strip()
        if not raw:
            continue
        values: list[Any] | None = None
        if raw.startswith("["):
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    values = parsed
            except json.JSONDecodeError:
                values = None
        if values is None:
            values = re.split(r"[,;\r\n]+", raw)
        for value in values:
            cleaned = str(value).strip().strip('"').strip("'")
            if cleaned and cleaned not in keys:
                keys.append(cleaned)
    return keys


class LLMClient:
    """Thin provider boundary; Phase 5 can replace this class without changing the loop."""

    def __init__(self, logger: EventLogger, timeout: float = 120) -> None:
        self.logger = logger
        self._key_lock = Lock()
        self._key_index = 0
        ollama_keys = _env_key_list("OLLAMA_API_KEYS", "OLLAMA_API_KEY", "OLLAM_API_KEYS", "OLLAM_API_KEY")
        anthropic_keys = _env_key_list("ANTHROPIC_API_KEYS", "ANTHROPIC_API_KEY")
        if ollama_keys:
            self.provider = "ollama"
            self.base_url = _first_env("OLLAMA_BASE_URL", "OLLAM_BASE_URL") or "https://ollama.com"
            self._clients = [
                Anthropic(auth_token=key, base_url=self.base_url, timeout=timeout, max_retries=0)
                for key in ollama_keys
            ]
        elif anthropic_keys:
            self.provider = "anthropic"
            self.base_url = _first_env("ANTHROPIC_BASE_URL") or "https://api.anthropic.com"
            self._clients = [
                Anthropic(api_key=key, base_url=self.base_url, timeout=timeout, max_retries=0)
                for key in anthropic_keys
            ]
        else:
            raise RuntimeError(
                "No LLM credential found. Set OLLAMA_API_KEYS or OLLAMA_API_KEY in the host-side .env file."
            )
        self.base_model = (
            _first_env("OLLAMA_MODEL", "OLLAM_MODEL") if self.provider == "ollama"
            else _first_env("ANTHROPIC_MODEL")
        ) or "gpt-oss:120b-cloud"
        self.available_models = list(dict.fromkeys([self.base_model, *_env_key_list("LLM_AVAILABLE_MODELS")]))
        workspace = logger.path.parent.parent if logger.path.parent.name == "logs" else logger.path.parent
        self.model_registry = ModelRegistry(workspace, logger, self.base_model, self.available_models)
        self.key_count = len(self._clients)
        self._client = self._clients[0]  # Compatibility for integrations that inspect the active client.

    def _active_client(self) -> Any:
        with self._key_lock:
            return self._clients[self._key_index]

    @property
    def model(self) -> str:
        """The primary model is fixed for the lifetime of this client."""
        return self.base_model

    def _rotate_key(self) -> bool:
        with self._key_lock:
            if self._key_index + 1 >= len(self._clients):
                return False
            self._key_index += 1
            self._client = self._clients[self._key_index]
            index = self._key_index
        self.logger.log(
            "llm_key_rotated",
            provider=self.provider,
            key_index=index,
            key_count=self.key_count,
            reason="provider limit, authentication, or quota failure",
        )
        return True

    @staticmethod
    def _is_key_limit_error(status_code: Any, error: Exception) -> bool:
        if status_code in {401, 403, 429, "401", "403", "429"}:
            return True
        text = str(error).casefold()
        return any(marker in text for marker in (
            "rate limit", "rate_limit", "too many requests", "quota", "insufficient_quota",
            "resource exhausted", "limit reached", "daily limit", "usage limit",
            "credits exhausted", "credit balance",
        ))

    def call(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int,
        model: str | None = None,
    ) -> LLMResult:
        if model is not None and model not in self.available_models:
            raise ValueError("Model is not in the configured allowlist")
        selected_model = model or self.base_model
        started = time.monotonic()
        parsed = urlsplit(self.base_url)
        base_path = parsed.path.rstrip("/")
        endpoint_path = f"{base_path}/v1/messages" if base_path else "/v1/messages"
        self.logger.log("network_request", method="POST", host=parsed.hostname or "", path=endpoint_path)
        self.logger.log(
            "llm_call_started",
            provider=self.provider,
            model=selected_model,
            message_count=len(messages),
            tool_count=len(tools),
            max_output_tokens=max_tokens,
            effective_cap=max_tokens,
        )
        response = None
        attempt = 0
        transient_retries = 0
        max_attempts = max(3, self.key_count + 2)
        while attempt < max_attempts:
            provider_call_number = reserve_provider_call(self.logger, self.provider, selected_model)
            self.logger.log("llm_call_attempt", provider=self.provider, model=selected_model,
                            provider_call_number=provider_call_number)
            attempt += 1
            try:
                response = self._active_client().messages.create(
                    model=selected_model,
                    max_tokens=max_tokens,
                    system=system,
                    messages=messages,
                    tools=tools,
                )
                break
            except Exception as exc:
                status_code = getattr(exc, "status_code", None)
                if self._is_key_limit_error(status_code, exc) and self._rotate_key():
                    continue
                retryable = status_code in {500, 502, 503, 504} or "Internal Server Error" in str(exc)
                self.logger.log(
                    "llm_call_failed",
                    provider=self.provider,
                    model=selected_model,
                    error_type=type(exc).__name__,
                    error=str(exc),
                    retry_attempt=attempt,
                    retryable=retryable,
                    effective_cap=max_tokens,
                )
                if not retryable or transient_retries >= 2:
                    self.model_registry.record_call(
                        selected_model, failed=True,
                        not_found=(status_code in {404, "404"} or type(exc).__name__ == "NotFoundError"),
                        latency_ms=round((time.monotonic() - started) * 1000))
                    raise
                transient_retries += 1
                time.sleep(1.5 * (attempt + 1))

        if response is None:
            self.model_registry.record_call(selected_model, failed=True,
                                            latency_ms=round((time.monotonic() - started) * 1000))
            raise RuntimeError("LLM provider returned no response")

        usage = response.usage
        input_tokens = sum(int(getattr(usage, field, 0) or 0) for field in
                           ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        content = [block.model_dump(exclude_none=True) for block in response.content]
        latency_ms = round((time.monotonic() - started) * 1000)
        self.model_registry.record_call(selected_model, failed=False, latency_ms=latency_ms)
        self.logger.log(
            "llm_call_completed",
            provider=self.provider,
            model=response.model,
            max_output_tokens=max_tokens,
            effective_cap=max_tokens,
            stop_reason=response.stop_reason,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            latency_ms=latency_ms,
        )
        return LLMResult(
            content=content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            stop_reason=response.stop_reason,
            model=response.model,
        )
