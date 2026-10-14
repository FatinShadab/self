"""Mutable provider metadata; facts are only trusted after a documented refresh."""
from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from event_log import EventLogger
from hardening import CapabilityRequests
from providers.adapters import (
    CerebrasAdapter, CloudflareAdapter, GeminiAdapter, GroqAdapter, HuggingFaceAdapter,
    MistralAdapter, OllamaLocalAdapter, OpenRouterAdapter,
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


# These are discovery seeds, deliberately not authoritative quota values. The
# research tool fetches their official docs and only a verified observation can
# populate numerical limits used by the router.
SEEDS: dict[str, dict[str, Any]] = {
    "gemini": {"base_url": "https://generativelanguage.googleapis.com/v1beta", "source_url": "https://ai.google.dev/gemini-api/docs/rate-limits", "signup_url": "https://aistudio.google.com/app/apikey", "key_env": ["GOOGLE_API_KEY"], "models": ["gemini-2.5-flash", "gemini-2.5-flash-lite"], "strengths": ["general reasoning", "long context"], "free_tier": {"requests_per_minute": None, "tokens_per_day": None, "notes": "Model and project-specific; consult the active AI Studio limits page."}},
    "groq": {"base_url": "https://api.groq.com/openai/v1", "source_url": "https://console.groq.com/docs/rate-limits", "signup_url": "https://console.groq.com/keys", "key_env": ["GROQ_API_KEY"], "models": ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b"], "strengths": ["low latency", "bulk simple tasks"], "free_tier": {"requests_per_minute": None, "tokens_per_day": None, "notes": "Limits vary by model and account; inspect the current free-plan table and response headers."}},
    "openrouter": {"base_url": "https://openrouter.ai/api/v1", "source_url": "https://openrouter.ai/docs/api/reference/limits", "signup_url": "https://openrouter.ai/keys", "key_env": ["OPENROUTER_API_KEY"], "models": ["openrouter/free"], "strengths": ["free model routing", "model variety"], "free_tier": {"requests_per_minute": None, "tokens_per_day": None, "notes": "Free-model daily limits depend on account credit history; query /api/v1/key after key setup."}},
    "mistral": {"base_url": "https://api.mistral.ai/v1", "source_url": "https://docs.mistral.ai/admin/billing-usage/usage-limits", "signup_url": "https://console.mistral.ai/api-keys", "key_env": ["MISTRAL_API_KEY"], "models": ["mistral-small-latest"], "strengths": ["general tasks", "European hosting"], "free_tier": {"requests_per_minute": None, "tokens_per_day": None, "notes": "Free-mode limits are account and model-specific; consult Admin API Limits."}},
    "cerebras": {"base_url": "https://api.cerebras.ai/v1", "source_url": "https://docs.cerebras.ai/", "signup_url": "https://cloud.cerebras.ai/", "key_env": ["CEREBRAS_API_KEY"], "models": ["gpt-oss-120b"], "strengths": ["fast inference"], "free_tier": {"requests_per_minute": None, "tokens_per_day": None, "notes": "Verify availability and quota in the Cerebras Cloud console before routing."}},
    "huggingface": {"base_url": "https://router.huggingface.co/v1", "source_url": "https://huggingface.co/docs/inference-providers/en/pricing", "signup_url": "https://huggingface.co/settings/tokens", "key_env": ["HF_TOKEN"], "models": ["openai/gpt-oss-120b"], "strengths": ["model variety", "experimentation"], "free_tier": {"requests_per_minute": None, "tokens_per_day": None, "notes": "Monthly credit amounts and rate limits can change; verify account billing and headers."}},
    "cloudflare_workers_ai": {"base_url": "https://api.cloudflare.com/client/v4", "source_url": "https://developers.cloudflare.com/workers-ai/platform/pricing/", "signup_url": "https://dash.cloudflare.com/profile/api-tokens", "key_env": ["CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID"], "models": ["@cf/zai-org/glm-4.7-flash"], "strengths": ["edge inference", "fast summarization"], "free_tier": {"requests_per_minute": None, "tokens_per_day": None, "neurons_per_day": None, "notes": "Quota is measured in neurons, not tokens; verify available free-plan models and daily allocation."}},
    "ollama_local": {"base_url": "http://127.0.0.1:11434", "source_url": "https://docs.ollama.com/api", "signup_url": "", "key_env": [], "models": [], "strengths": ["offline local inference", "no account"], "free_tier": {"requests_per_minute": None, "tokens_per_day": None, "notes": "No provider quota; requires a reachable local Ollama service and an already-installed model."}},
}


class ProviderRegistry:
    def __init__(self, workspace: str | Path, logger: EventLogger) -> None:
        self.workspace = Path(workspace)
        self.path = self.workspace / "state" / "providers.json"
        self.logger = logger
        self.adapters = {
            "gemini": GeminiAdapter(), "groq": GroqAdapter(), "openrouter": OpenRouterAdapter(),
            "mistral": MistralAdapter(), "cerebras": CerebrasAdapter(), "huggingface": HuggingFaceAdapter(),
            "cloudflare_workers_ai": CloudflareAdapter(), "ollama_local": OllamaLocalAdapter(),
        }

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = self._read()
        providers = data.setdefault("providers", {})
        changed = False
        for name, seed in SEEDS.items():
            if name not in providers:
                providers[name] = {"provider": name, "verification_status": "needs_refresh", "last_verified": None, **seed}
                changed = True
            elif name == "cerebras" and providers[name].get("source_url") == "https://inference.cerebras.ai/docs":
                # Correct a retired documentation URL without overwriting any
                # user-reviewed quota or model fields.
                providers[name]["source_url"] = seed["source_url"]
                providers[name]["last_verified"] = None
                providers[name]["verification_status"] = "needs_refresh"
                providers[name].pop("source_excerpt", None)
                providers[name].pop("source_excerpt_sha256", None)
                changed = True
        if changed or not self.path.exists():
            data["schema_version"] = 1
            data["updated_at"] = now()
            self._write(data)
            self.logger.log("provider_registry_initialized", providers=sorted(providers))

    def _read(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("providers", {}), dict):
                return data
        except (OSError, json.JSONDecodeError):
            pass
        return {"schema_version": 1, "providers": {}}

    def _write(self, data: dict[str, Any]) -> None:
        safe = self.logger.redactor.value(data)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(safe, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, self.path)

    def providers(self) -> dict[str, dict[str, Any]]:
        self.initialize()
        return self._read()["providers"]

    def configured(self) -> list[str]:
        self.initialize()
        return sorted(name for name, adapter in self.adapters.items() if adapter.is_configured())

    def metadata(self, provider: str) -> dict[str, Any]:
        try:
            return self.providers()[provider]
        except KeyError as exc:
            raise ValueError(f"Unknown provider: {provider}") from exc

    def fetch_official_docs(self, provider: str, max_chars: int = 12_000) -> dict[str, Any]:
        meta = self.metadata(provider)
        url = str(meta["source_url"])
        parsed = urlsplit(url)
        self.logger.log("network_request", method="GET", host=parsed.hostname or "", path=parsed.path or "/", purpose="provider_research")
        request = urllib.request.Request(url, headers={"User-Agent": "SELF-provider-research/0.1"})
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                raw = response.read(max_chars + 1)
                status = response.status
                content_type = response.headers.get_content_type()
        except urllib.error.HTTPError as exc:
            raw, status, content_type = exc.read(max_chars + 1), exc.code, "text/plain"
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Provider documentation unavailable for {provider}: {exc.reason}") from exc
        text = raw[:max_chars].decode("utf-8", errors="replace")
        data = self._read()
        record = data["providers"][provider]
        record["last_verified"] = now()
        record["verification_status"] = "docs_fetched_pending_structured_review"
        record["source_excerpt_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
        record["source_excerpt"] = self.logger.redactor.text(re.sub(r"\s+", " ", text)[:4_000])
        data["updated_at"] = now()
        self._write(data)
        self.logger.log("provider_docs_fetched", provider=provider, source_url=url, status=status, content_type=content_type)
        return {"provider": provider, "source_url": url, "status": status, "content_type": content_type, "body": text, "truncated": len(raw) > max_chars}

    def record_verification(self, provider: str, free_tier: dict[str, Any], models: list[str], strengths: list[str], source_url: str) -> dict[str, Any]:
        meta = self.metadata(provider)
        expected = urlsplit(str(meta["source_url"])).hostname
        actual = urlsplit(source_url).hostname
        if not actual or actual != expected:
            raise ValueError("Verification source must be the configured official documentation host")
        if not isinstance(free_tier, dict) or "requests_per_minute" not in free_tier or "tokens_per_day" not in free_tier:
            raise ValueError("free_tier must include requests_per_minute and tokens_per_day (use null only when docs do not publish it)")
        for field in ("requests_per_minute", "tokens_per_day"):
            value = free_tier.get(field)
            if value is not None and (not isinstance(value, int) or value < 0):
                raise ValueError(f"{field} must be a non-negative integer or null")
        data = self._read()
        record = data["providers"][provider]
        record.update({"free_tier": self.logger.redactor.value(free_tier), "models": [str(item)[:160] for item in models[:30]], "strengths": [str(item)[:160] for item in strengths[:12]], "last_verified": now(), "verification_status": "verified_from_official_docs", "source_url": source_url})
        data["updated_at"] = now()
        self._write(data)
        self.logger.log("provider_verified", provider=provider, source_url=source_url, limits=free_tier)
        return {"ok": True, "provider": provider, "last_verified": record["last_verified"]}

    def request_key(self, provider: str) -> dict[str, Any]:
        meta = self.metadata(provider)
        if self.adapters[provider].is_configured():
            return {"ok": True, "provider": provider, "status": "already_configured"}
        path = self.workspace / "state" / "key_requests.md"
        request = [
            f"## {provider} — {now()}",
            f"- Provider: {provider}",
            f"- Signup / key page: {meta.get('signup_url') or 'Not required for local Ollama'}",
            f"- Environment variable(s): {', '.join(meta.get('key_env', [])) or 'none'}",
            "- Steps: Use the provider's official page above, create or copy an API key yourself, add it to the host-side .env file, then restart the container with `docker compose up -d --force-recreate`.",
            f"- Expected free limits: {json.dumps(meta.get('free_tier', {}), ensure_ascii=False)}",
            "- SELF will not create an account, solve a CAPTCHA, or use additional accounts.",
            "",
        ]
        with path.open("a", encoding="utf-8") as handle:
            handle.write("\n".join(request))
        CapabilityRequests(self.workspace, self.logger).request(
            "credential",
            f"Add a {provider} API credential to the host-side .env file.",
            "SELF needs a human-supplied credential before it can call this provider.",
            provider,
            list(meta.get("key_env", [])),
            str(meta.get("signup_url", "")),
        )
        self.logger.log("provider_key_requested", provider=provider, env_names=meta.get("key_env", []), signup_url=meta.get("signup_url", ""))
        return {"ok": False, "provider": provider, "status": "key_requested", "path": str(path), "env_names": meta.get("key_env", [])}
