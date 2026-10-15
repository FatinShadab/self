from __future__ import annotations

import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from event_log import EventLogger
from base_tools import ToolRunner
from llm import LLMClient, _env_key_list


class ProviderLimitError(Exception):
    status_code = 429


class FakeBlock:
    def model_dump(self, exclude_none: bool = True) -> dict[str, str]:
        return {"type": "text", "text": "ok"}


class FakeAnthropic:
    instances: list["FakeAnthropic"] = []

    def __init__(self, **kwargs: object) -> None:
        self.key = str(kwargs.get("auth_token") or kwargs.get("api_key"))
        self.base_url = str(kwargs.get("base_url"))
        self.calls = 0
        self.last_model: object = None
        self.models: list[object] = []
        self.messages = self
        self.instances.append(self)

    def create(self, **kwargs: object) -> SimpleNamespace:
        self.calls += 1
        self.last_model = kwargs.get("model")
        self.models.append(self.last_model)
        if self.key == "first":
            raise ProviderLimitError("rate limit reached")
        return SimpleNamespace(
            usage=SimpleNamespace(input_tokens=2, output_tokens=1),
            content=[FakeBlock()],
            stop_reason="end_turn",
            model="fake-model",
        )


class LLMKeyRotationTests(unittest.TestCase):
    def test_agent_can_select_only_configured_models_for_next_call(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            logger = EventLogger(os.path.join(temp, "actions.jsonl"))
            FakeAnthropic.instances = []
            env = {
                "OLLAMA_API_KEYS": "second",
                "OLLAMA_MODEL": "base-model",
                "LLM_AVAILABLE_MODELS": '["small-model", "large-model", "base-model"]',
            }
            with patch("llm.Anthropic", FakeAnthropic), patch.dict(os.environ, env, clear=True):
                client = LLMClient(logger)
                self.assertEqual(client.available_models, ["base-model", "small-model", "large-model"])
                with self.assertRaises(ValueError):
                    client.select_model("unlisted-model")
                self.assertEqual(client.model, "base-model")
                client.call(system="system", messages=[{"role": "user", "content": "hello"}], tools=[], max_tokens=128)
                client.select_model("large-model")
                client.call(system="system", messages=[{"role": "user", "content": "hello"}], tools=[], max_tokens=128)
                self.assertEqual(len(FakeAnthropic.instances), 1)
                self.assertEqual(FakeAnthropic.instances[0].models, ["base-model", "large-model"])
                self.assertEqual(FakeAnthropic.instances[0].key, "second")
                self.assertEqual(FakeAnthropic.instances[0].base_url, "https://ollama.com")
                client.select_model("base-model")
                self.assertEqual(client.model, "base-model")

                runner = ToolRunner(logger, workspace=temp)
                runner.llm_client = client
                self.assertTrue(runner.execute("select_model", {"model": "small-model"})["ok"])
                self.assertEqual(client.model, "small-model")
                self.assertFalse(runner.execute("select_model", {"model": "unlisted-model"})["ok"])
                self.assertEqual(client.model, "small-model")

    def test_key_list_accepts_json_and_delimited_values(self) -> None:
        with patch.dict(os.environ, {"TEST_KEYS": '["one", "two"]'}, clear=False):
            self.assertEqual(_env_key_list("TEST_KEYS"), ["one", "two"])
        with patch.dict(os.environ, {"TEST_KEYS": "one,two;three"}, clear=False):
            self.assertEqual(_env_key_list("TEST_KEYS"), ["one", "two", "three"])

    def test_provider_limit_rotates_to_next_key_without_logging_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            logger = EventLogger(os.path.join(temp, "actions.jsonl"))
            FakeAnthropic.instances = []
            env = {
                "OLLAMA_API_KEYS": "first,second",
                "OLLAMA_API_KEY": "",
                "OLLAM_API_KEYS": "",
                "OLLAM_API_KEY": "",
                "OLLAMA_BASE_URL": "https://example.test",
            }
            with patch("llm.Anthropic", FakeAnthropic), patch.dict(os.environ, env, clear=False):
                client = LLMClient(logger)
                result = client.call(system="system", messages=[{"role": "user", "content": "hello"}], tools=[], max_tokens=128)

            self.assertEqual(result.model, "fake-model")
            self.assertEqual([item.calls for item in FakeAnthropic.instances], [1, 1])
            log = logger.path.read_text(encoding="utf-8")
            self.assertIn("llm_key_rotated", log)
            self.assertNotIn("first", log)
            self.assertNotIn("second", log)


if __name__ == "__main__":
    unittest.main()
