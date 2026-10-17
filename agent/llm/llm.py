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
        import json
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


@dataclass
class LLMResult:
    """Model response content and measured token usage."""

    content: list[dict[str, Any]]
    input_tokens: int
    output_tokens: int
    stop_reason: str | None
    model: str
    max_output_tokens: int | None = None

    @property
    def total_tokens(self) -> int:
        """Return the combined input and output token count."""
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
        """Reserve a provider attempt, send the request, and record measured usage."""
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
                is_net_err = _is_network_error(exc)
                retryable = is_net_err or status_code in {500, 502, 503, 504} or "Internal Server Error" in str(exc)
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
                    latency_ms = round((time.monotonic() - started) * 1000)
                    if is_net_err:
                        self.model_registry.record_network_error(selected_model, latency_ms=latency_ms)
                    else:
                        self.model_registry.record_call(
                            selected_model, failed=True,
                            not_found=(status_code in {404, "404"} or type(exc).__name__ == "NotFoundError"),
                            latency_ms=latency_ms)
                    raise
                transient_retries += 1
                time.sleep(min(10.0, 1.5 * (2 ** transient_retries)))

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
        result = LLMResult(
            content=content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            stop_reason=response.stop_reason,
            model=response.model,
        )
        if response_truncated(result, max_tokens):
            self.model_registry.record_truncated_call(selected_model)
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
            truncated=response_truncated(result, max_tokens),
        )
        return result
