"""Supplemental provider research, chat, benchmarking, and Ollama probe handlers."""
from __future__ import annotations

from pathlib import Path
from typing import Any


def handle_research_provider(brain_router: Any, provider: str) -> dict[str, Any]:
    """Fetch official provider information through the router."""
    if brain_router is None:
        raise RuntimeError("brain router is not configured")
    return brain_router.research_provider(provider)


def handle_record_provider_verification(
    brain_router: Any,
    provider: str,
    free_tier: dict[str, Any],
    models: list[str],
    strengths: list[str],
    source_url: str,
) -> dict[str, Any]:
    """Store provider limits verified against its official source."""
    if brain_router is None:
        raise RuntimeError("brain router is not configured")
    return brain_router.record_provider_verification(provider, free_tier, models, strengths, source_url)


def handle_request_provider_key(brain_router: Any, provider: str) -> dict[str, Any]:
    """Ask the human to configure a missing provider credential."""
    if brain_router is None:
        raise RuntimeError("brain router is not configured")
    return brain_router.request_key(provider)


def handle_ask_brain(
    brain_router: Any,
    prompt: str,
    task_type: str = "simple",
    model: str | None = None,
    preferred_provider: str | None = None,
    max_tokens: int = 512,
) -> dict[str, Any]:
    """Send a bounded plain-text request through a supplemental provider."""
    if brain_router is None:
        raise RuntimeError("brain router is not configured")
    return brain_router.chat(
        [{"role": "user", "content": prompt}],
        model,
        max(32, min(int(max_tokens), 4_096)),
        task_type,
        preferred_provider,
    )


def handle_benchmark_providers(
    workspace: Path,
    logger: Any,
    brain_router: Any,
    providers: list[str] | None = None,
) -> dict[str, Any]:
    """Run the provider comparison and persist benchmark scores."""
    from agent.tools.benchmark import run_benchmark

    return run_benchmark(workspace, logger, brain_router, providers)


def handle_probe_local_ollama(body: Any) -> dict[str, Any]:
    """Check local Ollama availability without starting or pulling a model."""
    return body.probe_local_ollama()
