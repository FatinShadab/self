"""SELF test model probe module."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.infra.event_log import EventLogger
from agent.infra.hardening import DailyTokenLedger
from agent.llm.llm import BudgetedLLM, BudgetExceeded, LLMResult
from agent.helper_models.model_probe import ModelProber, check_code_output, PROBE_CASES
from agent.llm.model_registry import ModelRegistry, PROBE_COOLDOWN_SECONDS


GOOD_OUTPUTS = [
    "9",
    "The library now opens Saturdays at 10 a.m.; weekday hours are unchanged.",
    '{"status":"ready","count":3}',
    "def triangular(n: int) -> int:\n    return n * (n + 1) // 2",
]


class FakeClient:
    available_models = ["base", "helper"]

    def __init__(self, outputs: list[object] | None = None) -> None:
        self.outputs = list(outputs or GOOD_OUTPUTS)
        self.calls: list[dict] = []

    def call(self, **kwargs: object) -> LLMResult:
        self.calls.append(dict(kwargs))
        item = self.outputs[(len(self.calls) - 1) % len(self.outputs)]
        if isinstance(item, Exception):
            raise item
        output = item.get("text", "") if isinstance(item, dict) else item
        stop_reason = item.get("stop_reason", "end_turn") if isinstance(item, dict) else "end_turn"
        output_tokens = item.get("output_tokens", 7) if isinstance(item, dict) else 7
        return LLMResult(content=[{"type": "text", "text": output}], input_tokens=5,
                         output_tokens=output_tokens, stop_reason=stop_reason,
                         model=str(kwargs.get("model")))


class FailingClient(FakeClient):
    def call(self, **kwargs: object) -> LLMResult:
        if len(self.calls) == 1:
            self.calls.append(dict(kwargs))
            raise RuntimeError("provider unavailable")
        return super().call(**kwargs)


class ModelProbeTests(unittest.TestCase):
    def test_structured_rating_schema_and_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logger = EventLogger(root / "logs" / "actions.jsonl")
            registry = ModelRegistry(root, logger, "base", ["base", "helper"])
            ratings = {name: "unknown" for name in
                       ("reasoning", "code", "instruction_following", "summarization", "json_output")}
            ratings["reasoning"] = "high"
            with self.assertRaises(ValueError):
                registry.record_model_assessment("helper", "Maybe useful", "observation", {"code": "high"})
            with self.assertRaises(ValueError):
                registry.record_model_assessment("helper", "Maybe useful", "observation",
                                                 {**ratings, "code": "excellent"})
            result = registry.record_model_assessment("helper", "Maybe useful", "observation", ratings)
            self.assertEqual(result["ratings"], ratings)
            self.assertIsNotNone(result["ratings_at"])
            reopened = ModelRegistry(root, logger, "base", ["base", "helper"])
            self.assertEqual(reopened.get_model("helper")["ratings"], ratings)

    def setup_prober(self, root: Path, *, outputs: list[object] | None = None,
                     cap: int = 100_000, clock=None, fetcher=None):
        logger = EventLogger(root / "logs" / "actions.jsonl")
        registry = ModelRegistry(root, logger, "base", ["base", "helper"])
        client = FakeClient(outputs)
        ledger = DailyTokenLedger(root, logger, cap=cap)
        budget = BudgetedLLM(client, logger, None, ledger)
        kwargs = {}
        if clock is not None:
            kwargs["clock"] = clock
        if fetcher is not None:
            kwargs["fetcher"] = fetcher
        prober = ModelProber(registry, budget, logger, "session-one", "ollama", **kwargs)
        return prober, registry, client, ledger, logger

    def test_probe_passes_objective_checks_and_counts_daily_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            prober, registry, client, ledger, logger = self.setup_prober(Path(temp))
            result = prober.probe_model("helper")
            self.assertTrue(result["ok"])
            self.assertEqual([case["passed"] for case in result["cases"]], [True] * 4)
            self.assertEqual([case["case"] for case in result["cases"]],
                             ["reasoning", "summarization", "json", "code"])
            self.assertEqual([call["model"] for call in client.calls], ["helper"] * 4)
            self.assertTrue(all(call["max_tokens"] == registry.get_output_cap("helper") for call in client.calls))
            self.assertEqual(result["outcome"], "passed")
            self.assertEqual(ledger.available_tokens(), ledger.cap - 48)
            self.assertEqual(registry.get_model("helper")["measured_stats"]["calls"], 4)
            self.assertIn(result["probe_id"], logger.path.read_text(encoding="utf-8"))
            self.assertTrue(registry.record_model_assessment(
                "helper", "Passed four checks", f"probe:{result['probe_id']}")["ok"])
            with self.assertRaises(ValueError):
                registry.record_model_assessment("helper", "Unsupported", "probe:" + "0" * 32)

    def test_unknown_disabled_cooldown_and_session_cap(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            current = [1_000.0]
            prober, registry, client, _, _ = self.setup_prober(Path(temp), clock=lambda: current[0])
            with self.assertRaises(ValueError):
                prober.probe_model("unknown")
            with registry._locked():
                data = registry._read()
                data["models"][1]["status"] = "disabled"
                registry._write(data)
            with self.assertRaisesRegex(ValueError, "disabled"):
                prober.probe_model("helper")
            with registry._locked():
                data = registry._read()
                data["models"][1]["status"] = "configured"
                registry._write(data)
            prober.probe_model("helper")
            with self.assertRaisesRegex(ValueError, "cooldown"):
                prober.probe_model("helper")
            current[0] += PROBE_COOLDOWN_SECONDS
            prober.probe_model("helper")
            current[0] += PROBE_COOLDOWN_SECONDS
            with self.assertRaisesRegex(ValueError, "cap"):
                prober.probe_model("helper")
            self.assertEqual(len(client.calls), 8)

    def test_failed_checks_and_budget_stop(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            prober, registry, client, _, _ = self.setup_prober(
                Path(temp), outputs=["10", "No relevant summary", "not json", "import os"])
            result = prober.probe_model("helper")
            self.assertTrue(result["ok"])
            self.assertEqual([case["passed"] for case in result["cases"]], [False] * 4)
            self.assertEqual(registry.get_model("helper")["measured_stats"]["probe_failures"], 4)
            self.assertEqual(registry.get_model("helper")["measured_stats"]["failures"], 4)
            self.assertEqual(len(client.calls), 4)
        with tempfile.TemporaryDirectory() as temp:
            prober, registry, client, _, _ = self.setup_prober(Path(temp))
            failing = FailingClient()
            prober.llm.client = failing
            result = prober.probe_model("helper")
            self.assertFalse(result["ok"])
            self.assertEqual(result["cases"][-1]["error_type"], "RuntimeError")
            self.assertEqual(registry.get_model("helper")["measured_stats"]["failures"], 1)
        with tempfile.TemporaryDirectory() as temp:
            prober, registry, client, _, _ = self.setup_prober(Path(temp), cap=100)
            skipped = prober.probe_model("helper")
            self.assertEqual(skipped["origin"], "skipped_budget")
            self.assertEqual(skipped["outcome"], "inconclusive")
            self.assertIsNone(skipped["cases"][0]["effective_cap"])
            self.assertEqual(client.calls, [])
            self.assertEqual(registry.get_model("helper")["probe_history"][-1]["status"], "inconclusive")

    def test_code_check_isolated_and_timeout_is_reported(self) -> None:
        self.assertTrue(check_code_output(GOOD_OUTPUTS[3])["passed"])
        real_run = subprocess.run
        inspected = []
        def inspect_run(*args, **kwargs):
            inspected.append((kwargs["cwd"], dict(kwargs["env"])))
            self.assertEqual(list(Path(kwargs["cwd"]).iterdir()), [])
            self.assertFalse(any("KEY" in key or "TOKEN" in key or "SECRET" in key
                                 for key in kwargs["env"]))
            return real_run(*args, **kwargs)
        with patch.dict("os.environ", {"OLLAMA_API_KEY": "private-test-value",
                                        "ANTHROPIC_API_KEY": "another-private-value"}), \
             patch("agent.helper_models.model_probe.subprocess.run", side_effect=inspect_run):
            self.assertTrue(check_code_output(GOOD_OUTPUTS[3])["passed"])
        self.assertEqual(len(inspected), 1)
        self.assertFalse(Path(inspected[0][0]).exists())
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "must_not_exist"
            malicious = f"import os\nos.system('touch {target}')"
            self.assertFalse(check_code_output(malicious)["passed"])
            self.assertFalse(target.exists())
        with patch("agent.helper_models.model_probe.subprocess.run", side_effect=subprocess.TimeoutExpired("python", 0.01)):
            self.assertEqual(check_code_output(GOOD_OUTPUTS[3])["reason"], "timeout")

    def test_truncation_and_empty_retry_are_inconclusive_not_failures(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            outputs = [
                {"text": "9", "stop_reason": "max_tokens", "output_tokens": 8},
                {"text": GOOD_OUTPUTS[1], "output_tokens": 32_768},
                GOOD_OUTPUTS[2], GOOD_OUTPUTS[3],
            ]
            prober, registry, client, _, _ = self.setup_prober(Path(temp), outputs=outputs)
            result = prober.probe_model("helper")
            self.assertEqual(result["outcome"], "inconclusive")
            self.assertEqual([case["outcome"] for case in result["cases"][:2]],
                             ["inconclusive", "inconclusive"])
            self.assertTrue(all(case["truncated"] for case in result["cases"][:2]))
            self.assertIsNone(result["cases"][0]["passed"])
            self.assertIn("unknown", result["note"])
            stats = registry.get_model("helper")["measured_stats"]
            self.assertEqual(stats["failures"], 0)
            self.assertEqual(stats["probe_inconclusive"], 2)
        with tempfile.TemporaryDirectory() as temp:
            outputs = ["", *GOOD_OUTPUTS]
            prober, registry, client, _, _ = self.setup_prober(Path(temp), outputs=outputs)
            result = prober.probe_model("helper")
            first = result["cases"][0]
            self.assertEqual(first["outcome"], "passed")
            self.assertEqual([a["outcome"] for a in first["attempts"]],
                             ["inconclusive", "passed"])
            self.assertEqual([call["max_tokens"] for call in client.calls[:2]],
                             [registry.get_output_cap("helper"), registry.get_output_cap("helper")])
            self.assertEqual(registry.get_model("helper")["measured_stats"]["calls"], 5)
            self.assertEqual(registry.get_model("helper")["measured_stats"]["failures"], 0)

    def test_fenced_json_is_reported_without_changing_strict_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            outputs = [GOOD_OUTPUTS[0], GOOD_OUTPUTS[1],
                       '```json\n{"status":"ready","count":3}\n```', GOOD_OUTPUTS[3]]
            prober, _, _, _, _ = self.setup_prober(Path(temp), outputs=outputs)
            row = prober.probe_model("helper")["cases"][2]
            self.assertEqual(row["outcome"], "failed")
            self.assertFalse(row["passed"])
            self.assertTrue(row["fenced_json"])

    def test_not_found_and_legacy_probe_invalidation_and_overrides(self) -> None:
        class NotFoundError(Exception):
            status_code = 404
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            prober, registry, _, _, _ = self.setup_prober(root, outputs=[NotFoundError("missing")])
            result = prober.probe_model("helper")
            self.assertFalse(result["ok"])
            entry = registry.get_model("helper")
            self.assertEqual(entry["status"], "not_found")
            self.assertIn("did not recognize", entry["status_message"])
            self.assertEqual(result["cases"][0]["error_type"], "NotFoundError")
            self.assertEqual(result["cases"][0]["error_kind"], "not_found")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logger = EventLogger(root / "logs" / "actions.jsonl")
            registry = ModelRegistry(root, logger, "base", ["base", "helper"])
            old_id = "a" * 32
            with registry._locked():
                data = registry._read()
                data.pop("probe_format_version")
                data["models"][1]["probe_history"] = [
                    {"id": old_id, "session_id": "session-one", "at": 1_000.0,
                     "status": "completed"}]
                data["models"][1]["agent_assessment"] = "Unfair failure claim"
                data["models"][1]["assessment_evidence"] = f"probe:{old_id}"
                registry._write(data)
            with patch.dict(os.environ, {"SELF_PROBE_COOLDOWN_SECONDS": "0",
                                        "SELF_PROBES_PER_MODEL_PER_SESSION": "3"}):
                reopened = ModelRegistry(root, logger, "base", ["base", "helper"])
            entry = reopened.get_model("helper")
            self.assertTrue(entry["probe_history"][0]["invalidated"])
            self.assertTrue(entry["probe_history"][0]["invalidation_reason"])
            self.assertEqual(entry["agent_assessment"], "")
            self.assertEqual(entry["assessment_evidence"], "")
            with self.assertRaises(ValueError):
                reopened.record_model_assessment("helper", "old", f"probe:{old_id}")
            self.assertEqual(reopened.probe_cooldown_seconds, 0)
            self.assertEqual(reopened.probes_per_model_per_session, 3)
            for _ in range(3):
                reopened.begin_probe("helper", "session-one", now=1_000.0)
            with self.assertRaisesRegex(ValueError, "cap"):
                reopened.begin_probe("helper", "session-one", now=1_000.0)
            self.assertEqual(len(reopened.get_model("helper")["probe_history"]), 4)

    def test_research_only_records_fetched_model_facts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            seen = []
            def fetched(url, _logger):
                seen.append(url)
                if url.endswith("/tags"):
                    return {"status": 200, "source_url": url,
                            "body": "<html><body>Tags: helper:latest 1M context window • Text input</body></html>"}
                return {"status": 200, "source_url": url,
                        "body": "<html><body>Model overview: helper has 70B total / 14B active parameters, free tier</body></html>"}
            prober, registry, _, _, logger = self.setup_prober(Path(temp), fetcher=fetched)
            result = prober.research_model("helper")
            self.assertTrue(result["ok"])
            self.assertEqual(result["status"], "facts_found")
            self.assertEqual(seen, ["https://ollama.com/library/helper", "https://ollama.com/library/helper/tags"])
            self.assertEqual(result["urls_tried"], seen)
            research = registry.get_model("helper")["research"]
            self.assertEqual(research["status"], "facts_found")
            self.assertEqual(research["total_params"], "70B")
            self.assertEqual(research["active_params"], "14B")
            self.assertIn("1M context window", research["context_window"])
            self.assertEqual(research["pricing"], "free tier")
            for fact in research["facts"]:
                self.assertIn(fact["value"], fact["excerpt"])
                self.assertEqual(fact["origin"], "web")
                self.assertTrue(fact["verified"])
                self.assertIsNotNone(fact["last_verified"])
            self.assertEqual(registry.get_model("helper")["agent_assessment"], "")
            with self.assertRaises(ValueError):
                prober.research_model("unknown")
            self.assertIn("model_research_recorded", logger.path.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temp:
            def absent(url, _logger):
                return {"status": 404, "source_url": url, "body": ""}
            prober, registry, _, _, _ = self.setup_prober(Path(temp), fetcher=absent)
            result = prober.research_model("helper")
            self.assertEqual(result["status"], "not_found")
            self.assertIn("404", result["status_message"])
            self.assertEqual(result["urls_tried"], ["https://ollama.com/library/helper"])
            self.assertEqual(registry.get_model("helper")["research"]["facts"], [])
            self.assertIsNone(registry.get_model("helper")["research"]["last_verified"])
            self.assertIsNone(registry.get_model("helper")["research"]["context_window"])
        with tempfile.TemporaryDirectory() as temp:
            def irrelevant(url, _logger):
                return {"status": 200, "source_url": url,
                        "body": "<html><body>Generic provider information only</body></html>"}
            prober, registry, _, _, _ = self.setup_prober(Path(temp), fetcher=irrelevant)
            result = prober.research_model("helper")
            self.assertEqual(result["status"], "fetched_no_model_fact")
            self.assertEqual(registry.get_model("helper")["research"]["facts"], [])

    def test_navigation_header_text_produces_no_facts(self) -> None:
        """Navigation or boilerplate header text must never produce a fact."""
        header_text = "nemotron-3-super GitHub 183.5K Download Models Docs Pricing Sign in"
        with tempfile.TemporaryDirectory() as temp:
            def header_fetcher(url, _logger):
                return {
                    "status": 200,
                    "source_url": url,
                    "body": f"<html><head><title>nemotron-3-super</title></head><body><header><nav>{header_text}</nav></header><main><div>{header_text}</div></main></body></html>",
                }
            root = Path(temp)
            logger = EventLogger(root / "logs" / "actions.jsonl")
            registry = ModelRegistry(root, logger, "gpt-oss:120b", ["gpt-oss:120b", "nemotron-3-super"])
            prober = ModelProber(registry, None, logger, "session-1", "ollama", fetcher=header_fetcher)
            result = prober.research_model("nemotron-3-super")
            self.assertEqual(result["status"], "fetched_no_model_fact")
            research = registry.get_model("nemotron-3-super")["research"]
            self.assertEqual(research["status"], "fetched_no_model_fact")
            self.assertEqual(research["facts"], [])
            self.assertIsNone(research["total_params"])
            self.assertIsNone(research["active_params"])
            self.assertIsNone(research["context_window"])
            self.assertIsNone(research["pricing"])
            self.assertIsNone(research["speed"])
            self.assertIsNone(research["strengths"])

    def test_agent_supplied_model_knowledge_facts(self) -> None:
        """Agent can supply facts from own knowledge as origin 'model_knowledge' with verified: false."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logger = EventLogger(root / "logs" / "actions.jsonl")
            registry = ModelRegistry(root, logger, "gpt-oss:120b", ["gpt-oss:120b", "nemotron-3-ultra"])
            # Agent records assessment with model_knowledge facts
            registry.record_model_assessment(
                "nemotron-3-ultra",
                assessment="nemotron-3-ultra status ok, call latency ~2.1s, probe latency ~1.8s",
                evidence="direct agent knowledge",
                facts={"total_params": "550B", "active_params": "55B", "context_window": "262k"},
            )
            entry = registry.get_model("nemotron-3-ultra")
            research = entry["research"]
            self.assertEqual(research["total_params"], "550B")
            self.assertEqual(research["active_params"], "55B")
            self.assertEqual(research["context_window"], "262k")
            for fact in research["facts"]:
                self.assertEqual(fact["origin"], "model_knowledge")
                self.assertFalse(fact["verified"])
                self.assertIsNone(fact["last_verified"])

            # Verify picker summary shows fact origins
            from agent.helper_models.model_decisions import ModelDecisions
            summary = ModelDecisions._summary_entry(entry)
            self.assertEqual(summary["total_params"], "550B")
            self.assertEqual(summary["active_params"], "55B")
            self.assertEqual(summary["facts_origin"]["total_params"], "model_knowledge")
            self.assertEqual(summary["facts_origin"]["active_params"], "model_knowledge")
            self.assertEqual(summary["facts"][0]["origin"], "model_knowledge")
            self.assertFalse(summary["facts"][0]["verified"])

    def test_probe_latency_tracked_and_reported(self) -> None:
        """Probe latency is recorded on the probe record and surfaced in summary_entry."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logger = EventLogger(root / "logs" / "actions.jsonl")
            registry = ModelRegistry(root, logger, "gpt-oss:120b", ["gpt-oss:120b", "helper"])
            probe_id = registry.begin_probe("helper", "sess-1")
            registry.finish_probe("helper", probe_id, failed=False, latency_ms=1850)
            entry = registry.get_model("helper")
            self.assertEqual(entry["probe_history"][0]["latency_ms"], 1850)

            from agent.helper_models.model_decisions import ModelDecisions
            summary = ModelDecisions._summary_entry(entry)
            self.assertEqual(summary["probe_latency_ms"], 1850)
            self.assertEqual(summary["avg_latency_ms"], "unknown")


if __name__ == "__main__":
    unittest.main()
