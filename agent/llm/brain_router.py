"""Quota-aware routing for supplementary plain-text model calls."""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.infra.event_log import EventLogger
from agent.infra.provider_calls import reserve_provider_call
from agent.llm.providers import ProviderRateLimited, ProviderUnavailable
from agent.llm.providers.registry import ProviderRegistry


TASK_PREFERENCES = {
    "reasoning": ["ollama", "gemini", "groq", "cerebras", "mistral", "openrouter", "huggingface", "cloudflare_workers_ai", "ollama_local"],
    "simple": ["groq", "cloudflare_workers_ai", "openrouter", "huggingface", "gemini", "mistral", "cerebras", "ollama_local"],
    "summarization": ["cloudflare_workers_ai", "groq", "gemini", "openrouter", "huggingface", "mistral", "cerebras", "ollama_local"],
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class BrainRouter:
    """Route provider research and chat requests through configured adapters."""

    def __init__(self, workspace: str | Path, logger: EventLogger, registry: ProviderRegistry | None = None) -> None:
        self.workspace = Path(workspace)
        self.logger = logger
        self.registry = registry or ProviderRegistry(workspace, logger)
        self.usage_path = self.workspace / "state" / "provider_usage.json"

    def _usage(self) -> dict[str, Any]:
        try:
            data = json.loads(self.usage_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (OSError, json.JSONDecodeError):
            pass
        return {"schema_version": 1, "providers": {}}

    def _save_usage(self, data: dict[str, Any]) -> None:
        self.usage_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.usage_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.logger.redactor.value(data), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, self.usage_path)

    @staticmethod
    def _estimate_tokens(messages: list[dict[str, Any]], max_tokens: int) -> int:
        return len(json.dumps(messages, ensure_ascii=False).encode("utf-8")) + max_tokens

    def _within_limit(self, provider: str, meta: dict[str, Any], estimated_tokens: int) -> tuple[bool, str]:
        limits = meta.get("free_tier") or {}
        rpm, tpd = limits.get("requests_per_minute"), limits.get("tokens_per_day")
        # Do not deliberately spend a provider's advertised free allocation until
        # both dimensions have been verified as numerical limits. Local Ollama is
        # the exception: it has no external free-tier quota.
        if provider != "ollama_local" and (not isinstance(rpm, int) or not isinstance(tpd, int)):
            return False, "unverified_or_account_specific_limits"
        data = self._usage()
        now_epoch = time.time()
        record = data.setdefault("providers", {}).setdefault(provider, {"calls": []})
        if float(record.get("backoff_until", 0) or 0) > now_epoch:
            return False, "backoff_active"
        record["calls"] = [call for call in record.get("calls", []) if now_epoch - float(call.get("at", 0)) < 86_400]
        calls_last_minute = [call for call in record["calls"] if now_epoch - float(call.get("at", 0)) < 60]
        used_today = sum(int(call.get("tokens", 0)) for call in record["calls"])
        if provider != "ollama_local" and len(calls_last_minute) + 1 > rpm:
            return False, "recorded_rpm_limit"
        if provider != "ollama_local" and used_today + estimated_tokens > tpd:
            return False, "recorded_tokens_per_day_limit"
        return True, "available"

    def _record_usage(self, provider: str, tokens: int) -> None:
        data = self._usage()
        record = data.setdefault("providers", {}).setdefault(provider, {"calls": []})
        record.setdefault("calls", []).append({"at": time.time(), "tokens": max(0, int(tokens))})
        record["updated_at"] = _now()
        self._save_usage(data)

    def candidates(self, task_type: str, preferred_provider: str | None = None) -> list[str]:
        """Return configured provider candidates for routing."""
        self.registry.initialize()
        if preferred_provider:
            if preferred_provider not in self.registry.adapters:
                raise ValueError(f"Unknown provider: {preferred_provider}")
            return [preferred_provider]
        return TASK_PREFERENCES.get(task_type, TASK_PREFERENCES["simple"])

    def chat(self, messages: list[dict[str, Any]], model: str | None, max_tokens: int, task_type: str = "simple", preferred_provider: str | None = None) -> dict[str, Any]:
        """Select a configured provider and send a bounded chat request."""
        if task_type not in TASK_PREFERENCES:
            raise ValueError("task_type must be reasoning, simple, or summarization")
        estimated = self._estimate_tokens(messages, max_tokens)
        skipped: list[dict[str, str]] = []
        for provider in self.candidates(task_type, preferred_provider):
            if provider == "ollama":  # Existing primary LLM uses a different tool-call protocol.
                skipped.append({"provider": provider, "reason": "primary_loop_only"})
                continue
            adapter = self.registry.adapters[provider]
            meta = self.registry.metadata(provider)
            if not adapter.is_configured():
                skipped.append({"provider": provider, "reason": "missing_key_or_service"})
                continue
            allowed, reason = self._within_limit(provider, meta, estimated)
            if not allowed:
                skipped.append({"provider": provider, "reason": reason})
                continue
            selected_model = model or (meta.get("models") or [""])[0]
            if not selected_model:
                skipped.append({"provider": provider, "reason": "no_verified_model"})
                continue
            base = str(meta.get("base_url", ""))
            from urllib.parse import urlsplit
            parsed = urlsplit(base)
            self.logger.log("network_request", method="POST", host=parsed.hostname or "", path=parsed.path or "/", purpose="brain_router")
            started = time.monotonic()
            provider_call_number = reserve_provider_call(self.logger, provider, selected_model)
            self.logger.log("provider_call_attempt", provider=provider, model=selected_model,
                            provider_call_number=provider_call_number)
            try:
                response = adapter.chat(messages, selected_model, max_tokens)
            except ProviderRateLimited as exc:
                cooldown = min(3_600, max(1.0, exc.retry_after or 30.0))
                self._record_backoff(provider, cooldown, str(exc))
                skipped.append({"provider": provider, "reason": "rate_limited"})
                continue
            except ProviderUnavailable as exc:
                skipped.append({"provider": provider, "reason": "unavailable"})
                self.logger.log("provider_call_unavailable", provider=provider, error=str(exc))
                continue
            except Exception as exc:
                skipped.append({"provider": provider, "reason": "provider_error"})
                self.logger.log("provider_call_failed", provider=provider, error_type=type(exc).__name__, error=str(exc))
                continue
            usage = response.usage
            spent = int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0))
            self._record_usage(provider, spent or estimated)
            latency_ms = round((time.monotonic() - started) * 1000, 2)
            self.logger.log("provider_call_completed", provider=provider, model=response.model, input_tokens=usage.get("input_tokens", 0), output_tokens=usage.get("output_tokens", 0), latency_ms=latency_ms)
            return {"ok": True, "provider": provider, "model": response.model, "text": self.logger.redactor.text(response.text), "usage": usage, "latency_ms": latency_ms, "skipped": skipped}
        return {"ok": False, "error": "No provider was safely available", "skipped": skipped}

    def _record_backoff(self, provider: str, seconds: float, detail: str) -> None:
        data = self._usage()
        record = data.setdefault("providers", {}).setdefault(provider, {"calls": []})
        record["backoff_until"] = time.time() + seconds
        self._save_usage(data)
        self.logger.log("provider_backoff", provider=provider, seconds=seconds, detail=detail)

    def request_key(self, provider: str) -> dict[str, Any]:
        """Write a human-facing request for a missing provider credential."""
        return self.registry.request_key(provider)

    def research_provider(self, provider: str) -> dict[str, Any]:
        """Fetch configured official documentation for a provider."""
        return self.registry.fetch_official_docs(provider)

    def record_provider_verification(self, provider: str, free_tier: dict[str, Any], models: list[str], strengths: list[str], source_url: str) -> dict[str, Any]:
        """Store provider limits and strengths verified from official docs."""
        return self.registry.record_verification(provider, free_tier, models, strengths, source_url)

    def probe_local_ollama(self) -> dict[str, Any]:
        """Check only; deliberately never pulls a model or launches a daemon."""
        meta = self.registry.metadata("ollama_local")
        base_url = str(meta["base_url"]).rstrip("/")
        from urllib.parse import urlsplit
        parsed = urlsplit(base_url)
        self.logger.log("network_request", method="GET", host=parsed.hostname or "", path=f"{parsed.path}/api/tags", purpose="local_ollama_probe")
        try:
            with urllib.request.urlopen(f"{base_url}/api/tags", timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
            models = [str(item.get("name", "")) for item in payload.get("models", []) if item.get("name")]
            available = bool(models)
            result = {"ok": available, "reachable": True, "models": models, "message": "Local Ollama reachable." if available else "Ollama is reachable but no model is installed; no download was attempted."}
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as exc:
            result = {"ok": False, "reachable": False, "models": [], "message": f"Local Ollama unavailable: {type(exc).__name__}"}
        try:
            memory = next(line for line in Path("/proc/meminfo").read_text().splitlines() if line.startswith("MemTotal:"))
            ram_bytes = int(memory.split()[1]) * 1024
        except (OSError, StopIteration, ValueError):
            ram_bytes = None
        result["container_limits"] = {"logical_cpus": os.cpu_count() or 0, "ram_bytes": ram_bytes, "configured_memory_ceiling": "4g (docker-compose)"}
        data = self.registry._read()
        record = data["providers"]["ollama_local"]
        record["local_probe"] = {**result, "at": _now()}
        data["updated_at"] = _now()
        self.registry._write(data)
        self.logger.log("local_ollama_probed", reachable=result["reachable"], model_count=len(result["models"]), ram_bytes=ram_bytes)
        return result
