"""Tests verifying removal of all token limits except the daily allowance."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.infra.event_log import EventLogger
from agent.infra.hardening import DailyTokenLedger
from agent.llm.llm import BudgetExceeded, BudgetedLLM, LLMResult
from agent.llm.model_registry import ModelRegistry
from agent.helper_models.model_decisions import ModelDecisions
from agent.helper_models.model_probe import ModelProber
from agent.runtime.loop import AgentConfig, AgentLoop
from agent.tools.base_tools import ToolRunner
from agent.tools.tool_registry import ToolRegistry
from agent.ui.wake import WakeCoordinator


class RecordingFakeClient:
    def __init__(self, responses: list[object] | None = None, model: str = "gpt-oss:120b",
                 available_models: list[str] | None = None) -> None:
        self.responses = list(responses or [])
        self.base_model = model
        self.provider = "test"
        self.available_models = list(available_models or [model, "helper-model"])
        self.calls: list[dict] = []

    def call(self, **kwargs) -> LLMResult:
        self.calls.append(dict(kwargs))
        selected_model = str(kwargs.get("model", self.base_model))
        if self.responses:
            item = self.responses.pop(0)
            if isinstance(item, Exception):
                raise item
            if isinstance(item, LLMResult):
                return item
            text = item.get("text", "") if isinstance(item, dict) else str(item)
            stop_reason = item.get("stop_reason", "end_turn") if isinstance(item, dict) else "end_turn"
            output_tokens = item.get("output_tokens", 42) if isinstance(item, dict) else 42
            return LLMResult(
                content=[{"type": "text", "text": text}],
                input_tokens=15,
                output_tokens=output_tokens,
                stop_reason=stop_reason,
                model=selected_model,
                max_output_tokens=kwargs.get("max_tokens"),
            )
        return LLMResult(
            content=[{"type": "text", "text": "OK"}],
            input_tokens=10,
            output_tokens=20,
            stop_reason="end_turn",
            model=selected_model,
            max_output_tokens=kwargs.get("max_tokens"),
        )


class TokenLimitsRemovalTests(unittest.TestCase):
    def test_no_call_path_passes_hardcoded_cap_other_than_registry_ceiling(self):
        """Verify actor loop, critic, checkpoint, probe, and reflection use registry ceiling."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logger = EventLogger(root / "logs" / "actions.jsonl")
            registry = ModelRegistry(root, logger, "gpt-oss:120b", ["gpt-oss:120b", "helper-model"])
            base_ceiling = registry.get_output_cap("gpt-oss:120b")
            helper_ceiling = registry.get_output_cap("helper-model")
            self.assertEqual(base_ceiling, 32_768)

            client = RecordingFakeClient(model="gpt-oss:120b")
            client.model_registry = registry
            ledger = DailyTokenLedger(root, logger, cap=500_000)
            budget = BudgetedLLM(client, logger, daily_ledger=ledger)

            # 1. Actor loop call
            config = AgentConfig(workspace=root, max_iterations=1, session_id="sess-1")
            runner = ToolRunner(logger, root)
            loop = AgentLoop(config, logger, client, runner)
            loop.run()
            actor_calls = [c for c in client.calls if "system" in c]
            self.assertTrue(len(actor_calls) >= 1)
            self.assertEqual(actor_calls[0]["max_tokens"], base_ceiling)

            # 2. Checkpoint / decide_model call
            client.calls.clear()
            client.responses = ['{"choice":"helper-model","reason":"task fit"}']
            decisions = ModelDecisions(root, logger, registry, budget, "sess-1")
            choice = decisions.decide_model("test task", moment="checkpoint")
            self.assertEqual(choice, "helper-model")
            self.assertEqual(client.calls[0]["max_tokens"], base_ceiling)

            # 3. Critic call in ToolRegistry
            client.calls.clear()
            client.responses = [
                '{"choice":"helper-model","reason":"critic fit"}',
                '{"approved":true,"issues":[]}',
            ]
            tool_reg = ToolRegistry(root, logger, budget.call, set())
            tool_reg.model_decisions = decisions
            code = "def run() -> dict:\n    return {'status': 'ok'}\n"
            test_code = "import unittest\nfrom tool import run\nclass T(unittest.TestCase):\n    def test_run(self): self.assertEqual(run(), {'status': 'ok'})\n"
            fake_test = {"output": "Ran 1 test\nOK", "timed_out": False, "exit_code": 0, "truncated": False}
            with patch("agent.tools.tool_registry.run_process", return_value=fake_test):
                result = tool_reg.create_tool("status_tool", "reports status", code, test_code)
            self.assertTrue(result["ok"])
            critic_calls = [c for c in client.calls if "approved" in str(c)]
            # Critic uses helper ceiling because helper-model was chosen by decide_model
            self.assertEqual(critic_calls[0]["max_tokens"], helper_ceiling)

            # 4. Probe call
            client.calls.clear()
            prober = ModelProber(registry, budget, logger, "sess-1", "ollama")
            client.responses = ["9", "Summary in 10 words", '{"status":"ready","count":3}', "def triangular(n): return n*(n+1)//2"]
            prober.probe_model("helper-model")
            for call in client.calls:
                self.assertEqual(call["max_tokens"], helper_ceiling)

            # 5. Ask model / delegation call
            client.calls.clear()
            client.responses = ["helper response"]
            delegation = decisions.ask_model("helper-model", "do work", "summary", "reason", "benefit")
            self.assertEqual(delegation["status"], "completed")
            self.assertEqual(client.calls[0]["max_tokens"], helper_ceiling)

    def test_call_whose_ceiling_exceeds_daily_allowance_runs_when_real_usage_fits(self):
        """A ceiling of 32,768 must not block a call when remaining daily allowance is only 3,000."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logger = EventLogger(root / "logs" / "actions.jsonl")
            ledger = DailyTokenLedger(root, logger, cap=3_000)
            self.assertEqual(ledger.available_tokens(), 3_000)

            client = RecordingFakeClient(responses=[{"text": "Short concise answer", "output_tokens": 50}])
            budget = BudgetedLLM(client, logger, daily_ledger=ledger)

            # Call with huge ceiling 32,768
            result = budget.call(
                system="Be concise",
                messages=[{"role": "user", "content": "hello"}],
                tools=[],
                max_tokens=32_768,
            )
            self.assertEqual(result.content[0]["text"], "Short concise answer")
            self.assertEqual(result.max_output_tokens, 32_768)
            # Ledger settled to real usage (15 input + 50 output = 65 tokens)
            self.assertEqual(ledger.available_tokens(), 3_000 - 65)

    def test_exhausted_daily_allowance_refuses_next_call_cleanly_and_pauses_loop(self):
        """When daily allowance is exhausted mid-call, the NEXT call is refused and loop pauses."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logger = EventLogger(root / "logs" / "actions.jsonl")
            # 2,000 daily allowance covers the estimate of 1 call (~1,540)
            ledger = DailyTokenLedger(root, logger, cap=2_000)
            client = RecordingFakeClient(responses=[
                # Call 1 spends 2,500 tokens, which exhausts the 2,000 allowance mid-call
                {"text": "Long response", "output_tokens": 2_485},
            ])
            budget = BudgetedLLM(client, logger, daily_ledger=ledger)

            # Call 1 finishes cleanly even though it exceeds the cap mid-call
            result1 = budget.call(system="sys", messages=[{"role": "user", "content": "first"}],
                                  tools=[], max_tokens=32_768)
            self.assertEqual(result1.content[0]["text"], "Long response")
            self.assertEqual(ledger.available_tokens(), 0)

            # The NEXT call is refused cleanly with BudgetExceeded(kind="daily")
            with self.assertRaises(BudgetExceeded) as cm:
                budget.call(system="sys", messages=[{"role": "user", "content": "second"}],
                            tools=[], max_tokens=32_768)
            self.assertEqual(cm.exception.kind, "daily")
            self.assertIn("Daily token limit reached", str(cm.exception))

            # Verify AgentLoop handles this by entering _pause_until_daily_reset
            config = AgentConfig(workspace=root, max_iterations=5, session_id="sess-pause", daily_ledger=ledger)
            runner = ToolRunner(logger, root)
            loop = AgentLoop(config, logger, client, runner)
            paused = False

            def fake_pause(*args, **kwargs):
                nonlocal paused
                paused = True
                loop.stop_file.touch()

            with patch.object(loop, "_pause_until_daily_reset", side_effect=fake_pause):
                loop.run()
            self.assertTrue(paused)

    def test_checkpoints_beyond_12_and_48_still_produce_real_choices_with_reasons(self):
        """Checkpoints beyond old 12 and 48 limits produce real choices without checkpoint_cap."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logger = EventLogger(root / "logs" / "actions.jsonl")
            registry = ModelRegistry(root, logger, "gpt-oss:120b", ["gpt-oss:120b", "helper-model"])
            responses = [f'{{"choice":"gpt-oss:120b","reason":"checkpoint {i} deliberation"}}' for i in range(60)]
            client = RecordingFakeClient(responses=responses, model="gpt-oss:120b")
            client.model_registry = registry
            ledger = DailyTokenLedger(root, logger, cap=5_000_000)
            budget = BudgetedLLM(client, logger, daily_ledger=ledger)
            decisions = ModelDecisions(root, logger, registry, budget, "sess-60")

            for i in range(60):
                choice = decisions.decide_model(f"Context task {i}", moment="checkpoint", tool_name=f"tool_{i}")
                self.assertEqual(choice, "gpt-oss:120b")

            self.assertEqual(len(client.calls), 60)
            rows = decisions.last_decisions(limit=None)
            self.assertEqual(len(rows), 60)
            self.assertTrue(all(r["origin"] == "model_choice" for r in rows))
            self.assertTrue(all("deliberation" in r["reason"] for r in rows))
            self.assertFalse(any(r.get("origin") == "default_after_cap" for r in rows))
            self.assertFalse(any(r.get("default_reason") == "checkpoint_cap" for r in rows))

    def test_truncated_structured_call_triggers_single_retry_and_records_signals(self):
        """A structured call that hits max_tokens triggers exactly one retry asking to be shorter."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logger = EventLogger(root / "logs" / "actions.jsonl")
            registry = ModelRegistry(root, logger, "gpt-oss:120b", ["gpt-oss:120b", "helper-model"])
            ledger = DailyTokenLedger(root, logger, cap=500_000)

            # Checkpoint call: attempt 1 truncated, attempt 2 succeeds with valid JSON
            responses = [
                {"text": '{"choice":"helper-model", "reason": "too long...', "stop_reason": "max_tokens", "output_tokens": 32_768},
                {"text": '{"choice":"helper-model", "reason": "concise"}', "stop_reason": "end_turn", "output_tokens": 15},
            ]
            client = RecordingFakeClient(responses=responses, model="gpt-oss:120b")
            client.model_registry = registry
            budget = BudgetedLLM(client, logger, daily_ledger=ledger)
            decisions = ModelDecisions(root, logger, registry, budget, "sess-trunc")

            choice = decisions.decide_model("review code", moment="checkpoint", tool_name="tool_trunc")
            self.assertEqual(choice, "helper-model")
            self.assertEqual(len(client.calls), 2)
            # Attempt 2 prompted to be concise / return valid JSON
            self.assertIn("truncated or not valid JSON", str(client.calls[1]["messages"][-1]["content"]))
            # Signals recorded
            outcomes = [json.loads(line) for line in decisions.outcomes.path.read_text().splitlines()]
            self.assertTrue(any(row["signal"] == "call_truncated" for row in outcomes))


if __name__ == "__main__":
    unittest.main()
