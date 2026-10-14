"""Small stdlib-only adapters; credentials are read only while making a call."""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import quote, urlsplit

from .base import ProviderError, ProviderRateLimited, ProviderResponse, ProviderUnavailable


def _env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return None


def _json_request(url: str, payload: dict[str, Any], headers: dict[str, str], timeout: float = 90) -> tuple[dict[str, Any], dict[str, str]]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8")), dict(response.headers.items())
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")[:2_000]
        retry = exc.headers.get("retry-after") if exc.headers else None
        try:
            retry_after = float(retry) if retry else None
        except ValueError:
            retry_after = None
        if exc.code == 429:
            raise ProviderRateLimited(f"HTTP 429 from {urlsplit(url).hostname}: {raw}", retry_after) from exc
        raise ProviderError(f"HTTP {exc.code} from {urlsplit(url).hostname}: {raw}") from exc
    except urllib.error.URLError as exc:
        raise ProviderUnavailable(f"Cannot reach {urlsplit(url).hostname}: {exc.reason}") from exc


class OpenAICompatibleAdapter:
    def __init__(self, provider: str, base_url: str, env_names: tuple[str, ...]) -> None:
        self.provider, self.base_url, self.env_names = provider, base_url.rstrip("/"), env_names

    def is_configured(self) -> bool:
        return bool(_env(*self.env_names))

    def chat(self, messages: list[dict[str, Any]], model: str, max_tokens: int) -> ProviderResponse:
        key = _env(*self.env_names)
        if not key:
            raise ProviderUnavailable(f"Missing {self.env_names[0]}")
        data, headers = _json_request(
            f"{self.base_url}/chat/completions",
            {"model": model, "messages": messages, "max_tokens": max_tokens},
            {"Authorization": f"Bearer {key}"},
        )
        try:
            text = str(data["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(f"{self.provider} returned no chat text") from exc
        usage = data.get("usage") or {}
        return ProviderResponse(text, {"input_tokens": int(usage.get("prompt_tokens", 0) or 0), "output_tokens": int(usage.get("completion_tokens", 0) or 0)}, model, headers)


class GroqAdapter(OpenAICompatibleAdapter):
    def __init__(self) -> None:
        super().__init__("groq", "https://api.groq.com/openai/v1", ("GROQ_API_KEY",))


class OpenRouterAdapter(OpenAICompatibleAdapter):
    def __init__(self) -> None:
        super().__init__("openrouter", "https://openrouter.ai/api/v1", ("OPENROUTER_API_KEY",))


class MistralAdapter(OpenAICompatibleAdapter):
    def __init__(self) -> None:
        super().__init__("mistral", "https://api.mistral.ai/v1", ("MISTRAL_API_KEY",))


class CerebrasAdapter(OpenAICompatibleAdapter):
    def __init__(self) -> None:
        super().__init__("cerebras", "https://api.cerebras.ai/v1", ("CEREBRAS_API_KEY",))


class HuggingFaceAdapter(OpenAICompatibleAdapter):
    def __init__(self) -> None:
        super().__init__("huggingface", "https://router.huggingface.co/v1", ("HF_TOKEN", "HUGGINGFACEHUB_API_TOKEN"))


class GeminiAdapter:
    provider = "gemini"

    def is_configured(self) -> bool:
        return bool(_env("GOOGLE_API_KEY", "GEMINI_API_KEY"))

    def chat(self, messages: list[dict[str, Any]], model: str, max_tokens: int) -> ProviderResponse:
        key = _env("GOOGLE_API_KEY", "GEMINI_API_KEY")
        if not key:
            raise ProviderUnavailable("Missing GOOGLE_API_KEY")
        contents = []
        system_parts = []
        for message in messages:
            role = str(message.get("role", "user"))
            content = message.get("content", "")
            if isinstance(content, list):
                content = "\n".join(str(part.get("text", "")) if isinstance(part, dict) else str(part) for part in content)
            if role == "system":
                system_parts.append(str(content))
            else:
                contents.append({"role": "model" if role == "assistant" else "user", "parts": [{"text": str(content)}]})
        payload: dict[str, Any] = {"contents": contents, "generationConfig": {"maxOutputTokens": max_tokens}}
        if system_parts:
            payload["systemInstruction"] = {"parts": [{"text": "\n".join(system_parts)}]}
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{quote(model, safe='._-')}:generateContent"
        data, headers = _json_request(url, payload, {"x-goog-api-key": key})
        try:
            parts = data["candidates"][0]["content"]["parts"]
            text = "".join(str(part.get("text", "")) for part in parts)
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("gemini returned no chat text") from exc
        usage = data.get("usageMetadata") or {}
        return ProviderResponse(text, {"input_tokens": int(usage.get("promptTokenCount", 0) or 0), "output_tokens": int(usage.get("candidatesTokenCount", 0) or 0)}, model, headers)


class CloudflareAdapter:
    provider = "cloudflare_workers_ai"

    def is_configured(self) -> bool:
        return bool(_env("CLOUDFLARE_API_TOKEN") and _env("CLOUDFLARE_ACCOUNT_ID"))

    def chat(self, messages: list[dict[str, Any]], model: str, max_tokens: int) -> ProviderResponse:
        token, account = _env("CLOUDFLARE_API_TOKEN"), _env("CLOUDFLARE_ACCOUNT_ID")
        if not token or not account:
            raise ProviderUnavailable("Missing CLOUDFLARE_API_TOKEN or CLOUDFLARE_ACCOUNT_ID")
        url = f"https://api.cloudflare.com/client/v4/accounts/{quote(account, safe='')}/ai/run/{quote(model, safe='@/._-')}"
        data, headers = _json_request(url, {"messages": messages, "max_tokens": max_tokens}, {"Authorization": f"Bearer {token}"})
        result = data.get("result") or {}
        text = result.get("response") or result.get("text")
        if not text:
            raise ProviderError("Cloudflare Workers AI returned no chat text")
        usage = result.get("usage") or {}
        return ProviderResponse(str(text), {"input_tokens": int(usage.get("input_tokens", 0) or 0), "output_tokens": int(usage.get("output_tokens", 0) or 0)}, model, headers)


class OllamaLocalAdapter:
    provider = "ollama_local"

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or os.getenv("OLLAMA_LOCAL_BASE_URL") or "http://127.0.0.1:11434").rstrip("/")

    def is_configured(self) -> bool:
        return True

    def chat(self, messages: list[dict[str, Any]], model: str, max_tokens: int) -> ProviderResponse:
        started = time.monotonic()
        data, headers = _json_request(f"{self.base_url}/api/chat", {"model": model, "messages": messages, "stream": False, "options": {"num_predict": max_tokens}}, {})
        text = ((data.get("message") or {}).get("content"))
        if not text:
            raise ProviderError("local Ollama returned no chat text")
        return ProviderResponse(str(text), {"input_tokens": int(data.get("prompt_eval_count", 0) or 0), "output_tokens": int(data.get("eval_count", 0) or 0), "latency_ms": int((time.monotonic() - started) * 1000)}, model, headers)
