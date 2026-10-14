from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from benchmark import run_benchmark
from brain_router import BrainRouter
from event_log import EventLogger
from providers.base import ProviderResponse
from providers.registry import ProviderRegistry


class FakeProvider:
    def is_configured(self) -> bool:
        return True

    def chat(self, messages: list[dict[str, Any]], model: str, max_tokens: int) -> ProviderResponse:
        prompt = str(messages[-1]["content"])
        text = "42" if "17 + 25" in prompt else "tested tools"
        return ProviderResponse(text=text, usage={"input_tokens": 3, "output_tokens": 2}, model=model, headers={})


class ProviderTests(unittest.TestCase):
    def _configured_router(self, root: Path) -> tuple[ProviderRegistry, BrainRouter]:
        logger = EventLogger(root / "logs" / "actions.jsonl")
        registry = ProviderRegistry(root, logger)
        registry.initialize()
        registry.record_verification(
            "groq",
            {"requests_per_minute": 5, "tokens_per_day": 1_000, "notes": "test-only verified limits"},
            ["test-model"], ["fast"], "https://console.groq.com/docs/rate-limits",
        )
        registry.adapters["groq"] = FakeProvider()
        return registry, BrainRouter(root, logger, registry)

    def test_key_request_writes_instructions_not_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logger = EventLogger(root / "logs" / "actions.jsonl")
            registry = ProviderRegistry(root, logger)
            response = registry.request_key("gemini")
            text = (root / "state" / "key_requests.md").read_text()
            self.assertFalse(response["ok"])
            self.assertIn("GOOGLE_API_KEY", text)
            self.assertIn("SELF will not create an account", text)

    def test_cerebras_legacy_doc_url_is_migrated(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logger = EventLogger(root / "logs" / "actions.jsonl")
            registry = ProviderRegistry(root, logger)
            registry.initialize()
            data = registry._read()
            data["providers"]["cerebras"]["source_url"] = "https://inference.cerebras.ai/docs"
            registry._write(data)
            registry.initialize()
            self.assertEqual(registry.metadata("cerebras")["source_url"], "https://docs.cerebras.ai/")

    def test_router_requires_verified_limits_then_tracks_usage(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry, router = self._configured_router(root)
            result = router.chat([{"role": "user", "content": "say hi"}], None, 32, "simple", "groq")
            self.assertTrue(result["ok"])
            usage = json.loads((root / "state" / "provider_usage.json").read_text())
            self.assertEqual(len(usage["providers"]["groq"]["calls"]), 1)

    def test_router_skips_unverified_external_provider(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logger = EventLogger(root / "logs" / "actions.jsonl")
            registry = ProviderRegistry(root, logger)
            registry.initialize()
            registry.adapters["groq"] = FakeProvider()
            result = BrainRouter(root, logger, registry).chat([{"role": "user", "content": "hi"}], None, 32, "simple", "groq")
            self.assertFalse(result["ok"])
            self.assertEqual(result["skipped"][0]["reason"], "unverified_or_account_specific_limits")

    def test_benchmark_persists_quality_scores(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry, router = self._configured_router(root)
            result = run_benchmark(root, router.logger, router, ["groq"])
            self.assertTrue(result["ok"])
            data = json.loads((root / "state" / "provider_scores.json").read_text())
            self.assertEqual(data["providers"]["groq"]["quality"], 1.0)


if __name__ == "__main__":
    unittest.main()
