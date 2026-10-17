"""SELF test model decisions module."""
from __future__ import annotations

import json
import io
import tempfile
import time
import unittest
from pathlib import Path

from agent.infra.event_log import EventLogger
from agent.infra.hardening import DailyTokenLedger
from agent.llm.llm import BudgetedLLM, LLMResult
from agent.runtime.loop import AgentConfig, AgentLoop
from agent.helper_models.model_decisions import (MAX_CHECKPOINTS_PER_SESSION,
                             MAX_DELEGATION_PROMPT_CHARS, MAX_DELEGATION_OUTPUT_TOKENS,
                             ModelDecisions, CHECKPOINT_OUTPUT_TOKENS, RETRY_OUTPUT_TOKENS,
                             print_decision_summary)
from agent.llm.model_registry import ModelRegistry
from agent.tools.base_tools import ToolRunner
from agent.tools.tool_registry import ToolRegistry
from agent.ui.wake import WakeCoordinator
from unittest.mock import patch


def answer(text: str, model: str, *, stop_reason: str = "end_turn",
           output_tokens: int = 7) -> LLMResult:
    return LLMResult(content=[{"type": "text", "text": text}], input_tokens=5,
                     output_tokens=output_tokens, stop_reason=stop_reason, model=model)


class FakeClient:
    base_model = "base"
    available_models = ["base", "helper"]
    provider = "test"

    def __init__(self, responses: list[object], registry: ModelRegistry) -> None:
        self.responses = list(responses)
        self.model_registry = registry
        self.base_model = registry.base_model
        self.available_models = list(registry.names)
        self.calls: list[dict] = []

    @property
    def model(self) -> str:
        return self.base_model

    def call(self, **kwargs):
        self.calls.append(dict(kwargs))
        result = self.responses.pop(0) if self.responses else '{"choice":"base","reason":"enough"}'
        if isinstance(result, Exception):
            self.model_registry.record_call(kwargs.get("model", "base"), failed=True, latency_ms=1)
            raise result
        self.model_registry.record_call(kwargs.get("model", "base"), failed=False, latency_ms=1)
        if isinstance(result, dict):
            return answer(result.get("text", ""), kwargs.get("model", "base"),
                          stop_reason=result.get("stop_reason", "end_turn"),
                          output_tokens=result.get("output_tokens", 7))
        return answer(result, kwargs.get("model", "base"))


class ModelDecisionTests(unittest.TestCase):
    def setup_decisions(self, root: Path, responses: list[object]):
        logger = EventLogger(root / "logs" / "actions.jsonl")
        registry = ModelRegistry(root, logger, "base", ["base", "helper"])
        client = FakeClient(responses, registry)
        ledger = DailyTokenLedger(root, logger, cap=100_000)
        budget = BudgetedLLM(client, logger, None, ledger)
        decisions = ModelDecisions(root, logger, registry, budget, "session-one")
        return decisions, registry, client, ledger

    def test_allowlist_required_fields_and_fallback_records_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            decisions, registry, client, ledger = self.setup_decisions(
                root, [RuntimeError("helper down"), "base answer"])
            decisions.start_task("fallback-task")
            for model in ("unknown", "base"):
                with self.assertRaises(ValueError):
                    decisions.ask_model(model, "prompt", "summary", "reason", "benefit")
            for reason, benefit in (("", "benefit"), ("reason", " ")):
                with self.assertRaises(ValueError):
                    decisions.ask_model("helper", "prompt", "summary", reason, benefit)
            with registry._locked():
                state = registry._read()
                state["models"][1]["status"] = "disabled"
                registry._write(state)
            with self.assertRaises(ValueError):
                decisions.ask_model("helper", "prompt", "summary", "reason", "benefit")
            with registry._locked():
                state = registry._read()
                state["models"][1]["status"] = "configured"
                registry._write(state)
            result = decisions.ask_model("helper", "prompt", "summary", "reason", "benefit")
            self.assertEqual(result["status"], "fallback")
            self.assertEqual(result["output"], "base answer")
            self.assertEqual([call["model"] for call in client.calls], ["helper", "base"])
            self.assertEqual(client.model, "base")
            self.assertEqual(registry.get_model("helper")["measured_stats"]["failures"], 1)
            self.assertGreater(ledger._read()["used_tokens"], 12)
            rows = decisions.last_decisions()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["source"], "agent_tool")
            self.assertEqual(rows[0]["status"], "fallback")
            self.assertEqual(rows[0]["origin"], "default_after_error")
            self.assertIsNone(rows[0]["outcome"])
            decisions.record_task_outcomes("fallback-task", completed=True, iterations=1,
                                           tool_errors=0, provider_errors=1)
            outcome_rows = [json.loads(line) for line in decisions.outcomes.path.read_text().splitlines()]
            self.assertTrue(any(row["source"] == "task_baseline" for row in outcome_rows))
            self.assertTrue(any(row["call_id"] == result["call_id"] and row["model"] == "helper"
                                for row in outcome_rows))

    def test_successful_delegation_is_capped_and_logged(self):
        with tempfile.TemporaryDirectory() as temp:
            decisions, registry, client, _ = self.setup_decisions(Path(temp), ["helper answer"])
            with self.assertRaises(ValueError):
                decisions.ask_model("helper", "x" * (MAX_DELEGATION_PROMPT_CHARS + 1),
                                    "summary", "reason", "benefit")
            result = decisions.ask_model("helper", "short prompt", "summary", "reason", "benefit")
            self.assertEqual(result["output"], "helper answer")
            self.assertTrue(result["untrusted"])
            self.assertLessEqual(client.calls[0]["max_tokens"], MAX_DELEGATION_OUTPUT_TOKENS)
            self.assertEqual(client.calls[0]["model"], "helper")
            self.assertEqual(registry.base_model, "base")
            self.assertEqual(decisions.last_decisions()[-1]["status"], "completed")
            self.assertEqual(decisions.last_decisions()[-1]["origin"], "model_choice")

    def test_self_reported_outcome_links_to_ask_call_without_overwriting_objective(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            decisions, _, _, _ = self.setup_decisions(root, ["helper answer"])
            call = decisions.ask_model("helper", "prompt", "summary", "reason", "benefit")
            decisions.record_delegation_outcome(call["call_id"], "partly_used", "Used one idea")
            with self.assertRaises(ValueError):
                decisions.record_delegation_outcome(call["call_id"], "maybe", "")
            rows = [json.loads(line) for line in decisions.outcomes.path.read_text().splitlines()]
            self.assertEqual({row["call_id"] for row in rows}, {call["call_id"]})
            self.assertEqual({row["provenance"] for row in rows}, {"objective", "self_reported"})
            self.assertEqual({row["signal"] for row in rows if row["provenance"] == "self_reported"},
                             {"usefulness", "note"})
            self.assertEqual(decisions.last_decisions()[-1]["origin"], "model_choice")

    def test_malformed_defaults_to_base_and_base_choice_is_logged(self):
        with tempfile.TemporaryDirectory() as temp:
            decisions, _, client, _ = self.setup_decisions(Path(temp),
                ["not json", '{"choice":"unknown","reason":"why"}',
                 '{"choice":"base","reason":"I can handle it"}'])
            self.assertEqual(decisions.decide_model("review", moment="critic"), "base")
            self.assertEqual(decisions.last_decisions()[-1]["origin"], "default_after_parse_failure")
            self.assertEqual(len(decisions.last_decisions()[-1]["attempts"]), 2)
            self.assertEqual(decisions.decide_model("review", moment="critic"), "base")
            self.assertEqual(decisions.last_decisions()[-1]["reason"], "I can handle it")
            self.assertEqual(decisions.last_decisions()[-1]["origin"], "model_choice")
            self.assertEqual([call["model"] for call in client.calls], ["base"] * 3)
            self.assertEqual(client.model, "base")

    def test_fenced_json_truncation_retry_and_auditable_choice(self):
        with tempfile.TemporaryDirectory() as temp:
            decisions, _, client, ledger = self.setup_decisions(Path(temp), [
                {"text": '{"choice":"helper"', "stop_reason": "max_tokens"},
                {"text": 'The choice is:\n```json\n{"choice":"helper","reason":"fit"}\n```'},
            ])
            self.assertEqual(decisions.decide_model("review", moment="critic"), "helper")
            record = decisions.last_decisions()[-1]
            self.assertEqual(record["origin"], "model_choice")
            self.assertEqual(record["options"], ["base", "helper"])
            self.assertEqual(record["registry_summary"][1]["status"], "untested")
            self.assertTrue(record["attempts"][0]["truncated"])
            self.assertEqual(record["attempts"][0]["stop_reason"], "max_tokens")
            base_cap = decisions.registry.get_output_cap("base")
            self.assertEqual([call["max_tokens"] for call in client.calls],
                             [base_cap, base_cap])
            self.assertEqual(ledger._read()["used_tokens"], 24)

    def test_options_and_prompt_omit_unavailable_models_and_invalid_assessment(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logger = EventLogger(root / "logs" / "actions.jsonl")
            registry = ModelRegistry(root, logger, "base",
                                     ["base", "helper", "missing", "disabled", "unstable"])
            with registry._locked():
                data = registry._read()
                entries = {item["name"]: item for item in data["models"]}
                entries["missing"]["status"] = "not_found"
                entries["disabled"]["status"] = "disabled"
                entries["unstable"]["status"] = "last_call_failed"
                entries["unstable"]["last_failure_at"] = time.time()
                entries["unstable"]["measured_stats"]["consecutive_failures"] = 3
                entries["helper"]["agent_assessment"] = "Bad legacy judgment"
                entries["helper"]["assessment_evidence"] = "probe:" + "a" * 32
                entries["helper"]["probe_history"] = [
                    {"id": "a" * 32, "invalidated": True, "status": "completed",
                     "session_id": "old", "at": 1}]
                registry._write(data)
            client = FakeClient(['{"choice":"base","reason":"enough"}'], registry)
            decisions = ModelDecisions(root, logger, registry,
                                       BudgetedLLM(client, logger, None,
                                                   DailyTokenLedger(root, logger, cap=100_000)),
                                       "session-one")
            self.assertEqual(decisions.decide_model("review", moment="critic"), "base")
            row = decisions.last_decisions()[-1]
            self.assertEqual(row["options"], ["base", "helper"])
            self.assertEqual(row["origin"], "model_choice")
            self.assertEqual(row["registry_summary"][1]["assessment"], "")
            prompt = client.calls[0]["messages"][0]["content"]
            self.assertNotIn("Bad legacy judgment", prompt)
            self.assertNotIn("missing", prompt)
            self.assertNotIn("disabled", prompt)
            self.assertNotIn("unstable", prompt)
            system = AgentLoop(AgentConfig(workspace=root, max_iterations=1),
                               logger, client, ToolRunner(logger, root))._system_prompt()
            self.assertNotIn("Bad legacy judgment", system)
            self.assertNotIn('"name": "missing"', system)
            self.assertIn('"status": "untested"', system)

    def test_transient_failure_cooldown_expires_but_not_found_stays_excluded(self):
        with tempfile.TemporaryDirectory() as temp:
            decisions, registry, _, _ = self.setup_decisions(Path(temp), [])
            with registry._locked():
                state = registry._read()
                helper = state["models"][1]
                helper["status"] = "last_call_failed"
                helper["last_failure_at"] = time.time()
                registry._write(state)
            self.assertNotIn("helper", decisions._available())
            with patch.dict("os.environ", {"SELF_MODEL_FAILURE_COOLDOWN_SECONDS": "0"}):
                fresh = ModelDecisions(Path(temp), decisions.logger, registry, decisions.llm, "fresh")
            self.assertIn("helper", fresh._available())
            registry.mark_not_found("helper")
            self.assertNotIn("helper", fresh._available())

    def test_checkpoint_skips_when_minimum_output_cap_is_unaffordable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logger = EventLogger(root / "logs" / "actions.jsonl")
            registry = ModelRegistry(root, logger, "base", ["base", "helper"])
            client = FakeClient([], registry)
            ledger = DailyTokenLedger(root, logger, cap=1)
            ledger.settle(0, 1)  # Exhaust daily allowance
            budget = BudgetedLLM(client, logger, daily_ledger=ledger)
            decisions = ModelDecisions(root, logger, registry, budget, "session")
            self.assertEqual(decisions.decide_model("review", moment="critic"), "base")
            row = decisions.last_decisions()[-1]
            self.assertEqual(row["origin"], "skipped_budget")
            self.assertIsNone(row["attempts"][0]["effective_cap"])
            self.assertEqual(client.calls, [])

    def test_empty_helper_output_retries_then_falls_back_with_origin(self):
        with tempfile.TemporaryDirectory() as temp:
            decisions, registry, client, _ = self.setup_decisions(Path(temp),
                                                                 ["", "", "base answer"])
            result = decisions.ask_model("helper", "prompt", "summary", "reason", "benefit")
            self.assertEqual(result["status"], "fallback")
            self.assertEqual(result["origin"], "default_after_error")
            self.assertEqual([call["model"] for call in client.calls],
                             ["helper", "helper", "base"])
            helper_cap = decisions.registry.get_output_cap("helper")
            base_cap = decisions.registry.get_output_cap("base")
            self.assertEqual([call["max_tokens"] for call in client.calls],
                             [helper_cap, helper_cap, base_cap])
            self.assertEqual(registry.get_model("helper")["measured_stats"]["failures"], 2)
            record = decisions.last_decisions()[-1]
            self.assertEqual(record["origin"], "default_after_error")
            self.assertEqual(len(record["attempts"]), 3)

    def test_summary_counts_origins_and_legacy_records_are_marked(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logger = EventLogger(root / "logs" / "actions.jsonl")
            registry = ModelRegistry(root, logger, "base", ["base", "helper"])
            path = root / "state" / "model_decisions.jsonl"
            path.write_text(json.dumps({"call_id": "old", "session_id": "old",
                                        "source": "checkpoint:critic", "status": "malformed_default",
                                        "model": "base", "tokens": 0}) + "\n" +
                            json.dumps({"call_id": "task-old", "session_id": "old",
                                        "source": "task_observation", "ask_model_followed": False}) + "\n",
                            encoding="utf-8")
            client = FakeClient(['{"choice":"base","reason":"enough"}'], registry)
            decisions = ModelDecisions(root, logger, registry,
                                       BudgetedLLM(client, logger, None,
                                                   DailyTokenLedger(root, logger, cap=100_000)),
                                       "session-one")
            decisions.decide_model("review", moment="critic")
            rows = decisions.last_decisions()
            self.assertEqual({row["origin"] for row in rows},
                             {"default_after_parse_failure", "model_choice"})
            self.assertEqual(len({row["call_id"] for row in rows}), 2)
            self.assertTrue(all(row["source"].startswith("checkpoint:") for row in rows))
            self.assertTrue(all(row["session_id"] for row in rows))
            self.assertTrue((root / "state" / "model_task_observations.jsonl").exists())
            output = io.StringIO()
            print_decision_summary(root, output=output)
            self.assertIn('"model_choice": 1', output.getvalue())
            self.assertIn('"default_after_parse_failure": 1', output.getvalue())
            self.assertIn("1/2 (50.0%)", output.getvalue())

    def test_checkpoint_cap_persists_and_blocks_extra_calls(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            responses = ['{"choice":"base","reason":"solid capability"}'] * 50
            decisions, registry, client, ledger = self.setup_decisions(root, responses)
            for i in range(50):
                self.assertEqual(decisions.decide_model(f"task {i}", moment="critic", tool_name=f"tool_{i}"), "base")
            self.assertEqual(len(client.calls), 50)
            rows = decisions.last_decisions(limit=None)
            self.assertEqual(len(rows), 50)
            self.assertTrue(all(r["origin"] == "model_choice" for r in rows))
            self.assertTrue(all(r["reason"] == "solid capability" for r in rows))
            self.assertTrue(all(not r.get("default_reason") for r in rows))
            coordinator = WakeCoordinator(root, llm_client=client)
            snapshot = coordinator.models_snapshot()
            self.assertEqual(len(snapshot["last_ten_decisions"]), 10)
            self.assertTrue(all(str(row["source"]).startswith("checkpoint:")
                                for row in snapshot["last_ten_decisions"]))
            self.assertEqual(snapshot["registry"]["base_model"], "base")
            coordinator.reflections.close()

    def test_reflection_calls_use_chosen_helper_without_mutating_base(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logger = EventLogger(root / "logs" / "actions.jsonl")
            registry = ModelRegistry(root, logger, "base", ["base", "helper"])
            choice = '{"choice":"helper","reason":"try helper"}'
            client = FakeClient([choice, '{"plan":[],"summary":"done"}',
                                 choice, '{"post":false,"message":"","question":null}'], registry)
            wake = WakeCoordinator(root, llm_client=client)
            wake.status.session_id = "session-one"
            wake._reflection("shutdown reflection", "session done")
            self.assertEqual([call["model"] for call in client.calls[:2]], ["base", "helper"])
            candidate = {"session_id": "session-one", "cycle": 1, "report": "done",
                         "actions": [], "triggers": ["work"],
                         "context_provider": lambda *args: "A recorded task ended."}
            wake.reflections._reflect(candidate)
            self.assertEqual([call["model"] for call in client.calls[2:]], ["base", "helper"])
            self.assertEqual(client.model, "base")
            sources = [row["source"] for row in ModelDecisions(
                root, logger, registry, BudgetedLLM(client, logger, None, wake.daily_ledger),
                "session-one").last_decisions()]
            self.assertIn("checkpoint:session_end_handoff", sources)
            self.assertIn("checkpoint:background_reflection", sources)
            wake.reflections.close()

    def test_critic_uses_checkpoint_choice_as_per_call_model(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logger = EventLogger(root / "logs" / "actions.jsonl")
            review_calls = []
            def review_call(**kwargs):
                review_calls.append(kwargs)
                return answer('{"approved":true,"issues":[]}', kwargs["model"])
            class Choice:
                def decide_model(self, context, *, moment):
                    self.context, self.moment = context, moment
                    return "helper"
            choice = Choice()
            registry = ToolRegistry(root, logger, review_call, set())
            registry.model_decisions = choice
            code = "def run(value: int) -> int:\n    return value + 1\n"
            tests = "import unittest\nfrom tool import run\nclass T(unittest.TestCase):\n    def test_run(self): self.assertEqual(run(1), 2)\n"
            fake_test = {"output": "Ran 1 test in 0.001s\nOK", "timed_out": False,
                         "exit_code": 0, "truncated": False}
            with patch("agent.tools.tool_registry.run_process", return_value=fake_test):
                result = registry.create_tool("increment", "Increment a number", code, tests)
            self.assertTrue(result["ok"])
            self.assertEqual(choice.moment, "create_tool_critic")
            self.assertEqual(review_calls[0]["model"], "helper")

    def test_task_note_once_and_observation_records_no_delegation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logger = EventLogger(root / "logs" / "actions.jsonl")
            registry = ModelRegistry(root, logger, "base", ["base", "helper"])
            registry.record_model_assessment("helper", "Observed concise response", "test observation")
            client = FakeClient(["First report", "Second report"], registry)
            config = AgentConfig(workspace=root, max_iterations=2, token_budget=50_000,
                                 task="Inspect a small task", retrieve_memories=False,
                                 session_id="session-one")
            AgentLoop(config, logger, client, ToolRunner(logger, root)).run()
            self.assertEqual(len(client.calls), 2)
            self.assertIn("Helper models are available. Consider ask_model",
                          client.calls[0]["messages"][0]["content"])
            self.assertNotIn("Helper models are available. Consider ask_model",
                             client.calls[1]["messages"][0]["content"])
            self.assertIn("Observed concise response", client.calls[0]["system"])
            rows = ModelDecisions(root, logger, registry,
                BudgetedLLM(client, logger, None, DailyTokenLedger(root, logger)),
                "session-one").last_decisions()
            self.assertEqual(rows, [])
            observed = json.loads((root / "state" / "model_task_observations.jsonl").read_text().splitlines()[-1])
            self.assertFalse(observed["ask_model_followed"])
            outcomes = [json.loads(line) for line in (root / "state" / "model_outcomes.jsonl").read_text().splitlines()]
            self.assertEqual({row["source"] for row in outcomes}, {"task_baseline"})
            self.assertTrue(all(row["provenance"] == "objective" for row in outcomes))

    def test_task_observation_records_delegation_when_tool_is_called(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logger = EventLogger(root / "logs" / "actions.jsonl")
            registry = ModelRegistry(root, logger, "base", ["base", "helper"])
            class ScriptedClient(FakeClient):
                def call(self, **kwargs):
                    self.calls.append(dict(kwargs))
                    model = kwargs.get("model", "base")
                    registry.record_call(model, failed=False, latency_ms=1)
                    if model == "helper":
                        return answer("A short helper answer.", model)
                    if sum(call.get("model", "base") == "base" for call in self.calls) == 1:
                        return LLMResult(content=[{"type": "tool_use", "id": "delegate-1",
                            "name": "ask_model", "input": {"model": "helper", "prompt": "Summarize this.",
                            "task_type": "summary", "reason": "Try the helper",
                            "expected_benefit": "A short answer"}}],
                            input_tokens=5, output_tokens=7, stop_reason="tool_use", model=model)
                    return answer("Done.", model)
            client = ScriptedClient([], registry)
            config = AgentConfig(workspace=root, max_iterations=1, token_budget=50_000,
                                 task="Summarize", retrieve_memories=False,
                                 session_id="session-one")
            AgentLoop(config, logger, client, ToolRunner(logger, root)).run()
            rows = ModelDecisions(root, logger, registry,
                BudgetedLLM(client, logger, None, DailyTokenLedger(root, logger)),
                "session-one").last_decisions()
            observed = json.loads((root / "state" / "model_task_observations.jsonl").read_text().splitlines()[-1])
            self.assertTrue(observed["ask_model_followed"])
            self.assertEqual(rows[-1]["source"], "agent_tool")
            self.assertEqual(rows[-1]["origin"], "model_choice")
            self.assertEqual(sum("record_delegation_outcome once" in str(message)
                                 for message in client.calls[-1]["messages"]), 1)

    def test_summary_entry_and_picker_prompt_anti_inference(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logger = EventLogger(root / "logs" / "actions.jsonl")
            registry = ModelRegistry(root, logger, "gpt-oss:120b", ["gpt-oss:120b", "nemotron-3-ultra"])
            registry.record_research(
                "nemotron-3-ultra", status="completed", source_url="https://nvidia.com",
                facts=[], total_params="550B", active_params="55B", context_window="262k+",
                pricing="free tier", speed="medium", strengths="reasoning, coding",
            )
            # Create a fake entry for testing summary
            entry = registry.get_model("nemotron-3-ultra")
            summary = ModelDecisions._summary_entry(entry)
            self.assertEqual(summary["total_params"], "550B")
            self.assertEqual(summary["active_params"], "55B")
            self.assertEqual(summary["context_window"], "262k+")
            self.assertEqual(summary["pricing"], "free tier")
            self.assertEqual(summary["speed"], "medium")
            self.assertEqual(summary["strengths"], "reasoning, coding")
            self.assertEqual(summary["truncation_rate"], "unknown")
            self.assertEqual(summary["avg_latency_ms"], "unknown")
            self.assertEqual(summary["probe_latency_ms"], "unknown")
            self.assertIn("facts", summary)
            self.assertIn("facts_origin", summary)

            # Test base model summary formatting
            base_entry = registry.get_model("gpt-oss:120b")
            base_summary = ModelDecisions._summary_entry(base_entry)
            self.assertIn("calls", base_summary)
            self.assertIn("failures", base_summary)
            self.assertIn("truncation_rate", base_summary)
            self.assertIn("network_errors", base_summary)

            # Test picker prompt includes anti-inference directive
            client = FakeClient(['{"choice": "nemotron-3-ultra", "reason": "strong params"}'], registry)
            decisions = ModelDecisions(root, logger, registry, BudgetedLLM(client, logger, 50_000), "session-1")
            choice = decisions.decide_model("coding task", moment="checkpoint")
            self.assertEqual(choice, "nemotron-3-ultra")
            system_content = client.calls[0]["system"]
            self.assertIn("Do not infer model size", system_content)

    def test_checkpoint_caching_and_default_after_cap(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logger = EventLogger(root / "logs" / "actions.jsonl")
            registry = ModelRegistry(root, logger, "gpt-oss:120b", ["gpt-oss:120b", "helper"])
            client = FakeClient([
                '{"choice": "helper", "reason": "faster"}',
                '{"choice": "helper", "reason": "different tool"}',
                '{"choice": "gpt-oss:120b", "reason": "after task start"}',
            ], registry)
            decisions = ModelDecisions(root, logger, registry, BudgetedLLM(client, logger, daily_ledger=DailyTokenLedger(root, logger)), "session-1")

            # First decision for moment 'critic' with tool_name="tool_a"
            c1 = decisions.decide_model("review tool 1", moment="create_tool_critic", tool_name="tool_a")
            self.assertEqual(c1, "helper")
            self.assertEqual(len(client.calls), 1)

            # Second decision for same moment and same tool reuses cache
            c2 = decisions.decide_model("review tool 1 again", moment="create_tool_critic", tool_name="tool_a")
            self.assertEqual(c2, "helper")
            self.assertEqual(len(client.calls), 1)

            # Different tool name invalidates cache and triggers a new call
            c3 = decisions.decide_model("review tool 2", moment="create_tool_critic", tool_name="tool_b")
            self.assertEqual(c3, "helper")
            self.assertEqual(len(client.calls), 2)

            # New task invalidates cache
            decisions.start_task("new-task-id")
            c4 = decisions.decide_model("review tool 2", moment="create_tool_critic", tool_name="tool_b")
            self.assertEqual(c4, "gpt-oss:120b")
            self.assertEqual(len(client.calls), 3)

            # No decisions have default_after_cap or checkpoint_cap
            rows = decisions.last_decisions()
            self.assertFalse(any(r.get("origin") == "default_after_cap" for r in rows))
            self.assertFalse(any(r.get("default_reason") == "checkpoint_cap" for r in rows))

    def test_truncation_records_counters_and_signals(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logger = EventLogger(root / "logs" / "actions.jsonl")
            registry = ModelRegistry(root, logger, "gpt-oss:120b", ["gpt-oss:120b", "helper"])
            # Fake client that simulates a truncated response on checkpoint
            class TruncatedClient(FakeClient):
                def call(self, **kwargs):
                    self.calls.append(kwargs)
                    raw_trunc = '{"choice": "helper", "reason": "incomp'
                    return LLMResult(content=[{"type": "text", "text": raw_trunc}],
                                     input_tokens=10, output_tokens=900, stop_reason="max_tokens",
                                     model=kwargs.get("model", "gpt-oss:120b"))

            client = TruncatedClient([], registry)
            decisions = ModelDecisions(root, logger, registry, BudgetedLLM(client, logger, 50_000), "session-1")
            choice = decisions.decide_model("task", moment="critic")
            # Should have counted truncated calls in registry
            self.assertGreaterEqual(registry.get_model("gpt-oss:120b")["measured_stats"]["truncated_calls"], 1)
            # Should have recorded call_truncated in model_outcomes.jsonl
            outcomes = [json.loads(line) for line in decisions.outcomes.path.read_text().splitlines()]
            signals = [row["signal"] for row in outcomes]
            self.assertIn("call_truncated", signals)
            self.assertIn("output_parse_failed", signals)


if __name__ == "__main__":
    unittest.main()
