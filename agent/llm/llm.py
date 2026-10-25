"""SELF llm module."""
from __future__ import annotations

import os
import sys
from threading import Lock
import time
from typing import Any
from urllib.parse import urlsplit

try:
    from anthropic import Anthropic
except ImportError:
    Anthropic = None

from agent.infra.event_log import EventLogger
from agent.infra.provider_calls import reserve_provider_call
from agent.llm.client import (
    BudgetExceeded as _BudgetExceeded,
    BudgetedLLM as _BudgetedLLM,
    LLMResult as _LLMResult,
    _env_key_list as _env_key_list_fn,
    _first_env as _first_env_fn,
    _is_network_error as _is_network_error_fn,
    call_with_minimum as _call_with_minimum,
    response_truncated as _response_truncated,
)
from agent.llm.model_registry import ModelRegistry

BudgetExceeded = _BudgetExceeded
BudgetedLLM = _BudgetedLLM
LLMResult = _LLMResult
response_truncated = _response_truncated
call_with_minimum = _call_with_minimum
_first_env = _first_env_fn
_env_key_list = _env_key_list_fn
_is_network_error = _is_network_error_fn


class LLMClient:
    """Thin provider boundary; Phase 5 can replace this class without changing the loop."""

    def __init__(self, logger: EventLogger, timeout: float = 120) -> None:
        self.logger = logger
        self._key_lock = Lock()
        self._key_index = 0
        ollama_keys = _env_key_list("OLLAMA_API_KEYS", "OLLAMA_API_KEY", "OLLAM_API_KEYS", "OLLAM_API_KEY")
        anthropic_keys = _env_key_list("ANTHROPIC_API_KEYS", "ANTHROPIC_API_KEY")
        if (ollama_keys or anthropic_keys) and Anthropic is None:
            raise RuntimeError(
                "The 'anthropic' package is required to initialize LLMClient. "
                "Install requirements via: pip install -r agent/requirements.txt"
            )
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
        configured_model = (
            _first_env("OLLAMA_MODEL", "OLLAM_MODEL") if self.provider == "ollama"
            else _first_env("ANTHROPIC_MODEL")
        ) or os.getenv("SELF_BASE_MODEL")
        if not configured_model:
            if "unittest" in sys.modules or "pytest" in sys.modules or os.getenv("SELF_TEST_MODE") or os.getenv("PYTEST_CURRENT_TEST"):
                configured_model = "gpt-oss:120b-cloud"
            else:
                raise RuntimeError(
                    "No LLM model configured. Please set OLLAMA_MODEL, ANTHROPIC_MODEL, or SELF_BASE_MODEL in your environment."
                )
        self.base_model = configured_model
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


__all__ = [
    "Anthropic",
    "BudgetExceeded",
    "BudgetedLLM",
    "LLMClient",
    "LLMResult",
    "_env_key_list",
    "_first_env",
    "_is_network_error",
    "call_with_minimum",
    "reserve_provider_call",
    "response_truncated",
]
