from __future__ import annotations

import json
import io
import tempfile
import time
import unittest
from pathlib import Path

from event_log import EventLogger
from hardening import DailyTokenLedger
from llm import BudgetedLLM, LLMResult
from loop import AgentConfig, AgentLoop
from model_decisions import (MAX_CHECKPOINTS_PER_SESSION,
                             MAX_DELEGATION_PROMPT_CHARS, MAX_DELEGATION_OUTPUT_TOKENS,
                             ModelDecisions, CHECKPOINT_OUTPUT_TOKENS, RETRY_OUTPUT_TOKENS,
                             print_decision_summary)
from model_registry import ModelRegistry
from base_tools import ToolRunner
from tool_registry import ToolRegistry
from wake import WakeCoordinator
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
            self.assertIn('"choice":"helper"', record["raw_response"])
            self.assertEqual([call["max_tokens"] for call in client.calls],
                             [CHECKPOINT_OUTPUT_TOKENS, RETRY_OUTPUT_TOKENS])
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
            budget = BudgetedLLM(client, logger, 900)
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
            self.assertEqual(result["output"], "base answer")
            self.assertEqual([call["model"] for call in client.calls],
                             ["helper", "helper", "base"])
            self.assertEqual([call["max_tokens"] for call in client.calls],
                             [MAX_DELEGATION_OUTPUT_TOKENS, RETRY_OUTPUT_TOKENS, RETRY_OUTPUT_TOKENS])
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
            decisions, registry, client, ledger = self.setup_decisions(root, [])
            for _ in range(MAX_CHECKPOINTS_PER_SESSION):
                self.assertEqual(decisions.decide_model("task", moment="critic"), "base")
            restarted = ModelDecisions(root, decisions.logger, registry,
                                       BudgetedLLM(client, decisions.logger, None, ledger),
                                       "session-one")
            self.assertEqual(restarted.decide_model("task", moment="critic"), "base")
            self.assertEqual(len(client.calls), MAX_CHECKPOINTS_PER_SESSION)
            self.assertEqual(restarted.last_decisions()[-1]["default_reason"], "checkpoint_cap")
            self.assertEqual(restarted.last_decisions()[-1]["origin"], "default_after_error")
            restarted.record_task_observation("task-id", "task", False)
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
            with patch("tool_registry.run_process", return_value=fake_test):
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


if __name__ == "__main__":
    unittest.main()
