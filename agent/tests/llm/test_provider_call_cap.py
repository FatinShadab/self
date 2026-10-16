"""Provider attempts stop at the campaign's per-run call cap."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agent.infra.event_log import EventLogger
from agent.llm.llm import LLMClient


class ProviderCallCapTests(unittest.TestCase):
    def test_call_cap_counts_real_attempts_with_fake_provider(self):
        calls = []

        class Client:
            def __init__(self, **kwargs):
                self.messages = self

            def create(self, **kwargs):
                calls.append(kwargs)
                block = SimpleNamespace(model_dump=lambda **_: {"type":"text", "text":"ok"})
                return SimpleNamespace(usage=SimpleNamespace(input_tokens=1, output_tokens=1),
                                       content=[block], stop_reason="end_turn", model=kwargs["model"])

        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {
                "OLLAMA_API_KEY":"fake-key", "OLLAMA_API_KEYS":"", "ANTHROPIC_API_KEY":"",
                "SELF_MAX_PROVIDER_CALLS":"1", "OLLAMA_MODEL":"base",
                "LLM_AVAILABLE_MODELS":"helper"}):
            logger = EventLogger(Path(temp) / "logs/actions.jsonl")
            with patch("agent.llm.llm.Anthropic", Client):
                client = LLMClient(logger)
                client.call(system="s", messages=[], tools=[], max_tokens=64)
                with self.assertRaisesRegex(RuntimeError, "Provider call cap reached"):
                    client.call(system="s", messages=[], tools=[], max_tokens=64)
            self.assertEqual(len(calls), 1)
