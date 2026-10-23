"""External model provider research and benchmarking tool schemas."""
from __future__ import annotations

from typing import Any

RESEARCH_PROVIDER_DEFINITION: dict[str, Any] = {
        "name": "research_provider",
        "description": "Fetch a configured provider's official documentation, log only host/path, and store a bounded research excerpt for human/agent review. Never signs up or creates an account.",
        "input_schema": {"type": "object", "properties": {"provider": {"type": "string"}}, "required": ["provider"]},
    }

RECORD_PROVIDER_VERIFICATION_DEFINITION: dict[str, Any] = {
        "name": "record_provider_verification",
        "description": "After reading official provider documentation, record models, strengths, source URL, and explicit free-tier RPM/tokens-per-day limits (null only if unpublished).",
        "input_schema": {"type": "object", "properties": {
            "provider": {"type": "string"}, "free_tier": {"type": "object"}, "models": {"type": "array", "items": {"type": "string"}},
            "strengths": {"type": "array", "items": {"type": "string"}}, "source_url": {"type": "string"},
        }, "required": ["provider", "free_tier", "models", "strengths", "source_url"]},
    }

REQUEST_PROVIDER_KEY_DEFINITION: dict[str, Any] = {
        "name": "request_provider_key",
        "description": "Write a human-only API-key request for a provider. This never creates an account and does not halt unrelated agent work.",
        "input_schema": {"type": "object", "properties": {"provider": {"type": "string"}}, "required": ["provider"]},
    }

ASK_BRAIN_DEFINITION: dict[str, Any] = {
        "name": "ask_brain",
        "description": "Use a safely routed supplementary provider for plain-text reasoning, simple work, or summarization. It uses only configured keys, respects recorded limits, backs off on 429, and falls back safely.",
        "input_schema": {"type": "object", "properties": {
            "prompt": {"type": "string"}, "task_type": {"type": "string", "enum": ["reasoning", "simple", "summarization"], "default": "simple"},
            "model": {"type": "string"}, "preferred_provider": {"type": "string"}, "max_tokens": {"type": "integer", "default": 512},
        }, "required": ["prompt"]},
    }

BENCHMARK_PROVIDERS_DEFINITION: dict[str, Any] = {
        "name": "benchmark_providers",
        "description": "Run the small built-in local eval set only against configured providers that are safely within verified free limits, saving quality/latency data to state/provider_scores.json.",
        "input_schema": {"type": "object", "properties": {"providers": {"type": "array", "items": {"type": "string"}}}},
    }
