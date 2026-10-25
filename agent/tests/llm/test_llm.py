"""SELF test llm module."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agent.tests.test_helpers import ensure_test_base_model

ensure_test_base_model()

from agent.infra.event_log import EventLogger
from agent.tools.base_tools import ToolRunner
from agent.llm.llm import BudgetedLLM, LLMClient, _env_key_list
from agent.llm.model_registry import ModelRegistry
from agent.infra.hardening import DailyTokenLedger


class ProviderLimitError(Exception):
    status_code = 429


class NotFoundError(Exception):
    status_code = 404


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
    def test_provider_model_not_found_sets_registry_status(self) -> None:
        class MissingAnthropic(FakeAnthropic):
            def create(self, **kwargs: object) -> SimpleNamespace:
                raise NotFoundError("unknown model")
        with tempfile.TemporaryDirectory() as temp:
            logger = EventLogger(os.path.join(temp, "logs", "actions.jsonl"))
            with patch("agent.llm.llm.Anthropic", MissingAnthropic), patch.dict(os.environ, {
                "OLLAMA_API_KEYS": "test-only", "OLLAMA_MODEL": "base",
                "LLM_AVAILABLE_MODELS": '["helper"]',
            }, clear=True):
                client = LLMClient(logger)
                with self.assertRaises(NotFoundError):
                    client.call(system="test", messages=[], tools=[], max_tokens=128, model="helper")
                entry = client.model_registry.get_model("helper")
                self.assertEqual(entry["status"], "not_found")
                self.assertIn("did not recognize", entry["status_message"])

    def test_daily_ledger_survives_concurrent_process_updates(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            logger = EventLogger(os.path.join(temp, "logs", "actions.jsonl"))
            ledger = DailyTokenLedger(temp, logger, cap=1000)
            script = (
                "import sys\n"
                "from agent.infra.event_log import EventLogger\n"
                "from agent.infra.hardening import DailyTokenLedger\n"
                "root = sys.argv[1]\n"
                "ledger = DailyTokenLedger(root, EventLogger(root + '/logs/actions.jsonl'), cap=1000)\n"
                "for _ in range(50):\n"
                "    assert ledger.reserve(1)\n"
                "    ledger.settle(1, 1)\n"
            )
            workers = [subprocess.Popen([sys.executable, "-c", script, temp],
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                       for _ in range(2)]
            for worker in workers:
                _, errors = worker.communicate(timeout=20)
                self.assertEqual(worker.returncode, 0, errors.decode("utf-8", errors="replace"))
            self.assertEqual(ledger._read()["used_tokens"], 100)
            self.assertEqual(ledger._read()["reserved_tokens"], 0)

    def test_per_call_model_is_allowlisted_without_changing_base(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            logger = EventLogger(os.path.join(temp, "actions.jsonl"))
            FakeAnthropic.instances = []
            env = {
                "OLLAMA_API_KEYS": "second",
                "OLLAMA_MODEL": "base-model",
                "LLM_AVAILABLE_MODELS": '["small-model", "large-model", "base-model"]',
            }
            with patch("agent.llm.llm.Anthropic", FakeAnthropic), patch.dict(os.environ, env, clear=True):
                client = LLMClient(logger)
                self.assertEqual(client.available_models, ["base-model", "small-model", "large-model"])
                self.assertEqual(client.model, "base-model")
                with self.assertRaises(ValueError):
                    client.call(system="system", messages=[], tools=[], max_tokens=128, model="unlisted-model")
                client.call(system="system", messages=[{"role": "user", "content": "hello"}], tools=[], max_tokens=128)
                client.call(system="system", messages=[{"role": "user", "content": "hello"}], tools=[], max_tokens=128, model="large-model")
                client.call(system="system", messages=[{"role": "user", "content": "hello"}], tools=[], max_tokens=128)
                self.assertEqual(len(FakeAnthropic.instances), 1)
                self.assertEqual(FakeAnthropic.instances[0].models, ["base-model", "large-model", "base-model"])
                self.assertEqual(FakeAnthropic.instances[0].key, "second")
                self.assertEqual(FakeAnthropic.instances[0].base_url, "https://ollama.com")
                self.assertEqual(client.model, "base-model")
                with self.assertRaises(AttributeError):
                    client.model = "small-model"
                budget = BudgetedLLM(client, logger, 10_000)
                with self.assertRaises(ValueError):
                    budget.call(system="system", messages=[], tools=[], max_tokens=128, model="unlisted-model")
                budget.call(system="system", messages=[], tools=[], max_tokens=128, model="small-model")
                self.assertEqual(FakeAnthropic.instances[0].models[-1], "small-model")
                self.assertEqual(client.model, "base-model")
                runner = ToolRunner(logger, workspace=temp)
                runner.model_registry = client.model_registry
                self.assertFalse(runner.execute("select_model", {"model": "small-model"})["ok"])
                listed = runner.execute("list_models", {})
                self.assertEqual([item["role"] for item in listed["models"]], ["base", "helper", "helper"])
                self.assertEqual(listed["models"][0]["measured_stats"]["calls"], 2)
                self.assertEqual(listed["models"][2]["measured_stats"]["calls"], 1)
                self.assertFalse(runner.execute("record_model_assessment", {
                    "name": "small-model", "assessment": "seems concise", "evidence": ""})["ok"])
                self.assertTrue(runner.execute("record_model_assessment", {
                    "name": "small-model", "assessment": "followed a short instruction",
                    "evidence": "logs/actions.jsonl:llm_call_completed"})["ok"])
                self.assertEqual(runner.execute("list_models", {})["models"][1]["agent_assessment"],
                                 "followed a short instruction")
                reopened = ModelRegistry(temp, logger, client.base_model, client.available_models)
                self.assertEqual(reopened.list_models()["models"][1]["assessment_evidence"],
                                 "logs/actions.jsonl:llm_call_completed")

    def test_registry_redacts_assessments_and_writes_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            with patch.dict(os.environ, {"TEST_API_KEY": "private-value-123"}):
                logger = EventLogger(os.path.join(temp, "logs", "actions.jsonl"))
                registry = ModelRegistry(temp, logger, "base", ["base", "helper"])
                registry.record_model_assessment(
                    "helper", "Saw private-value-123 in output", "logs/actions.jsonl:1")
                saved = registry.path.read_text(encoding="utf-8")
                self.assertNotIn("private-value-123", saved)
                self.assertIn("<redacted>", saved)
                self.assertEqual(len(registry.list_models()["models"]), 2)
                self.assertEqual(list(registry.path.parent.glob(".models-*.tmp")), [])

    def test_registry_stats_survive_two_processes_updating_same_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            logger = EventLogger(os.path.join(temp, "logs", "actions.jsonl"))
            registry = ModelRegistry(temp, logger, "base", ["base", "helper"])
            script = (
                "import sys\n"
                "from agent.infra.event_log import EventLogger\n"
                "from agent.llm.model_registry import ModelRegistry\n"
                "root = sys.argv[1]\n"
                "registry = ModelRegistry(root, EventLogger(root + '/logs/actions.jsonl'), 'base', ['base', 'helper'])\n"
                "for _ in range(50): registry.record_call('helper', failed=False, latency_ms=1)\n"
            )
            workers = [subprocess.Popen([sys.executable, "-c", script, temp],
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                       for _ in range(2)]
            for worker in workers:
                _, errors = worker.communicate(timeout=20)
                self.assertEqual(worker.returncode, 0, errors.decode("utf-8", errors="replace"))
            stats = registry.list_models()["models"][1]["measured_stats"]
            self.assertEqual(stats["calls"], 100)
            self.assertEqual(stats["failures"], 0)
            self.assertEqual(stats["latency_ms_total"], 100)

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
            with patch("agent.llm.llm.Anthropic", FakeAnthropic), patch.dict(os.environ, env, clear=False):
                client = LLMClient(logger)
                result = client.call(system="system", messages=[{"role": "user", "content": "hello"}], tools=[], max_tokens=128)

            self.assertEqual(result.model, "fake-model")
            self.assertEqual([item.calls for item in FakeAnthropic.instances], [1, 1])
            log = logger.path.read_text(encoding="utf-8")
            self.assertIn("llm_key_rotated", log)
            self.assertNotIn("first", log)
            self.assertNotIn("second", log)

    def test_helpers_needing_evaluation_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            logger = EventLogger(os.path.join(temp, "logs", "actions.jsonl"))
            registry = ModelRegistry(temp, logger, "base", ["base", "helper"])
            self.assertEqual(registry.helpers_needing_evaluation(), ["helper"])

            probe_id = registry.begin_probe("helper", "session-1")
            registry.finish_probe("helper", probe_id, failed=False)
            registry.record_research("helper", status="completed", source_url="https://example.com", facts=[])
            registry.record_model_assessment("helper", "Great helper", f"probe:{probe_id}")

            self.assertEqual(registry.helpers_needing_evaluation(), [])

            reopened = ModelRegistry(temp, logger, "base", ["base", "helper-v2"])
            self.assertEqual(reopened.helpers_needing_evaluation(), ["helper-v2"])
            helper_v2 = reopened.get_model("helper-v2")
            self.assertEqual(helper_v2["agent_assessment"], "")
            self.assertEqual(helper_v2["probe_history"], [])
            data = reopened._read()
            old_entry = next(m for m in data["models"] if m["name"] == "helper")
            self.assertFalse(old_entry.get("configured"))
            self.assertEqual(old_entry.get("status"), "unconfigured")

    def test_network_errors_retry_and_release_budget(self) -> None:
        class NetworkErrorAnthropic:
            instances = []
            def __init__(self, **kwargs):
                self.calls = 0
                self.messages = self
                NetworkErrorAnthropic.instances.append(self)
            def create(self, **kwargs):
                self.calls += 1
                raise ConnectionError("Connection refused by peer")

        with tempfile.TemporaryDirectory() as temp:
            logger = EventLogger(os.path.join(temp, "logs", "actions.jsonl"))
            ledger = DailyTokenLedger(temp, logger, cap=10_000)
            env = {"OLLAMA_API_KEYS": "key1", "OLLAMA_MODEL": "base"}
            with patch("agent.llm.llm.Anthropic", NetworkErrorAnthropic), patch.dict(os.environ, env, clear=True), patch("time.sleep", return_value=None):
                client = LLMClient(logger)
                budget = BudgetedLLM(client, logger, 5_000, daily_ledger=ledger)
                with self.assertRaises(ConnectionError):
                    budget.call(system="sys", messages=[{"role": "user", "content": "hi"}], tools=[], max_tokens=100)

                self.assertEqual(budget.tokens_used, 0)
                self.assertEqual(ledger.available_tokens(), 10_000)

                stats = client.model_registry.get_model("base")["measured_stats"]
                self.assertEqual(stats["network_errors"], 1)
                self.assertEqual(stats["failures"], 0)
                self.assertEqual(stats["consecutive_failures"], 0)

    def test_schema_version_3_migration_and_model_knowledge(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logger = EventLogger(root / "logs" / "actions.jsonl")
            state_dir = root / "state"
            state_dir.mkdir(parents=True)
            v2_data = {
                "schema_version": 2,
                "probe_format_version": 2,
                "base_model": "base",
                "models": [
                    {
                        "name": "base",
                        "role": "base",
                        "configured": True,
                        "status": "reachable",
                        "research": {"status": "not_checked", "facts": []},
                    },
                    {
                        "name": "helper",
                        "role": "helper",
                        "configured": True,
                        "status": "reachable",
                        "probe_history": [{"id": "p1", "session_id": "s1", "at": 100.0, "status": "completed"}],
                        "research": {
                            "status": "verified_mention",
                            "source_url": "https://ollama.com/library/helper",
                            "facts": [
                                {
                                    "field": "model_name_mentioned",
                                    "value": "helper",
                                    "excerpt": "helper GitHub 183.5K Download Models Docs Pricing Sign in",
                                    "source_url": "https://ollama.com/library/helper",
                                    "origin": "web",
                                }
                            ],
                        },
                    },
                ],
            }
            (state_dir / "models.json").write_text(json.dumps(v2_data), encoding="utf-8")
            registry = ModelRegistry(root, logger, "base", ["base", "helper"])
            # Verified that migration to schema_version 3 cleaned up verified_mention and model_name_mentioned
            reopened = registry.list_models()
            self.assertEqual(reopened["schema_version"], 3)
            helper = next(m for m in reopened["models"] if m["name"] == "helper")
            self.assertEqual(helper["research"]["status"], "fetched_no_model_fact")
            self.assertEqual(helper["research"]["facts"], [])
            self.assertEqual(helper["research"]["urls_tried"], ["https://ollama.com/library/helper"])

            # Test supplying model_knowledge facts via record_model_assessment
            registry.record_model_assessment(
                "helper", "good model", "direct inspection",
                facts={"total_params": "30B", "context_window": "128k"},
            )
            updated = registry.get_model("helper")
            self.assertEqual(updated["research"]["total_params"], "30B")
            self.assertEqual(updated["research"]["context_window"], "128k")
            facts = updated["research"]["facts"]
            self.assertEqual(len(facts), 2)
            for f in facts:
                self.assertEqual(f["origin"], "model_knowledge")
                self.assertFalse(f["verified"])


if __name__ == "__main__":
    unittest.main()
