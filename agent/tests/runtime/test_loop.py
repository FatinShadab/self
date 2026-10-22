"""SELF test loop module."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from agent.infra.hardening import DailyTokenLedger
from agent.tools.base_tools import ToolRunner
from agent.infra.event_log import EventLogger
from agent.llm.llm import LLMResult
from agent.runtime.loop import AgentConfig, AgentLoop


class FakeLLM:
    def __init__(self, responses: list[LLMResult] | None = None) -> None:
        self.calls = 0
        self.responses = responses or []

    def call(self, **_: Any) -> LLMResult:
        self.calls += 1
        if self.responses:
            return self.responses.pop(0)
        return LLMResult(
            content=[{"type": "text", "text": f"Completed exploration report {self.calls}."}],
            input_tokens=10,
            output_tokens=5,
            stop_reason="end_turn",
            model="fake-model",
        )


class AgentLoopTests(unittest.TestCase):
    def test_fixed_base_and_model_registry_tools_reach_agent(self) -> None:
        class ModelAwareLLM(FakeLLM):
            def __init__(self) -> None:
                super().__init__()
                self.provider = "ollama"
                self.base_model = "base-model"
                self.available_models = [self.base_model, "other-model"]
                self.systems: list[str] = []
                self.offered_tools: list[list[str]] = []

            def call(self, **kwargs: Any) -> LLMResult:
                self.calls += 1
                self.systems.append(str(kwargs["system"]))
                self.offered_tools.append([tool["name"] for tool in kwargs["tools"]])
                if self.calls == 1:
                    return LLMResult(
                        content=[{"type": "tool_use", "id": "models-1", "name": "list_models", "input": {}}],
                        input_tokens=1, output_tokens=1, stop_reason="tool_use", model=self.base_model,
                    )
                return LLMResult(
                    content=[{"type": "text", "text": "Continued with the base model."}],
                    input_tokens=1, output_tokens=1, stop_reason="end_turn", model=self.base_model,
                )

        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp)
            logger = EventLogger(workspace / "logs" / "actions.jsonl")
            fake = ModelAwareLLM()
            AgentLoop(
                AgentConfig(workspace=workspace, max_iterations=1, token_budget=10_000),
                logger, fake, ToolRunner(logger, workspace),
            ).run()
            self.assertIn('"name": "other-model"', fake.systems[0])
            self.assertIn('"status": "untested"', fake.systems[0])
            self.assertIn("list_models", fake.offered_tools[0])
            self.assertIn("record_model_assessment", fake.offered_tools[0])
            self.assertIn("probe_model", fake.offered_tools[0])
            self.assertIn("research_model", fake.offered_tools[0])
            self.assertIn("ask_model", fake.offered_tools[0])
            self.assertNotIn("select_model", fake.offered_tools[0])
            self.assertIn("ask_brain", fake.offered_tools[0])
            self.assertIn("Base: base-model", fake.systems[1])

    def test_existing_stop_file_prevents_llm_call(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp)
            (workspace / "STOP").touch()
            logger = EventLogger(workspace / "logs" / "actions.jsonl")
            fake = FakeLLM()
            summary = AgentLoop(
                AgentConfig(workspace=workspace, max_iterations=5, token_budget=10_000),
                logger,
                fake,
                ToolRunner(logger, workspace),
            ).run()
            self.assertEqual(summary.reason, "stop_file")
            self.assertEqual(summary.iterations, 0)
            self.assertEqual(fake.calls, 0)

    def test_five_iteration_exploration(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp)
            logger = EventLogger(workspace / "logs" / "actions.jsonl")
            fake = FakeLLM()
            loop = AgentLoop(
                AgentConfig(workspace=workspace, max_iterations=5, token_budget=10_000),
                logger,
                fake,
                ToolRunner(logger, workspace),
            )
            summary = loop.run()
            self.assertEqual(summary.iterations, 5)
            self.assertEqual(fake.calls, 5)
            self.assertEqual(summary.reason, "max_iterations")

    def test_tool_use_is_executed_and_observed(self) -> None:
        responses = [
            LLMResult(
                content=[
                    {"type": "text", "text": "Checking the shell."},
                    {
                        "type": "tool_use",
                        "id": "tool-1",
                        "name": "run_shell",
                        "input": {"cmd": "printf hello"},
                    },
                ],
                input_tokens=10,
                output_tokens=5,
                stop_reason="tool_use",
                model="fake-model",
            ),
            LLMResult(
                content=[{"type": "text", "text": "Found a working shell."}],
                input_tokens=10,
                output_tokens=5,
                stop_reason="end_turn",
                model="fake-model",
            ),
        ]
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp)
            logger = EventLogger(workspace / "logs" / "actions.jsonl")
            fake = FakeLLM(responses)
            summary = AgentLoop(
                AgentConfig(workspace=workspace, max_iterations=1, token_budget=10_000),
                logger,
                fake,
                ToolRunner(logger, workspace),
            ).run()
            self.assertEqual(summary.iterations, 1)
            self.assertEqual(fake.calls, 2)
            self.assertIn('"event":"tool_result"', logger.path.read_text())

    def test_repeated_tool_action_is_blocked(self) -> None:
        responses = [
            LLMResult(content=[{"type": "tool_use", "id": "tool-1", "name": "run_shell", "input": {"cmd": "printf hello"}}], input_tokens=1, output_tokens=1, stop_reason="tool_use", model="fake-model"),
            LLMResult(content=[{"type": "text", "text": "Finished the check."}], input_tokens=1, output_tokens=1, stop_reason="end_turn", model="fake-model"),
            LLMResult(content=[{"type": "tool_use", "id": "tool-2", "name": "run_shell", "input": {"cmd": "printf hello"}}], input_tokens=1, output_tokens=1, stop_reason="tool_use", model="fake-model"),
            LLMResult(content=[{"type": "text", "text": "I will stop repeating this action."}], input_tokens=1, output_tokens=1, stop_reason="end_turn", model="fake-model"),
        ]
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp)
            logger = EventLogger(workspace / "logs" / "actions.jsonl")
            summary = AgentLoop(
                AgentConfig(workspace=workspace, max_iterations=2, token_budget=10_000),
                logger,
                FakeLLM(responses),
                ToolRunner(logger, workspace),
            ).run()
            self.assertEqual(summary.iterations, 2)
            self.assertIn("repeated_tool_action_blocked", logger.path.read_text())

    def test_tool_rounds_are_not_capped(self) -> None:
        responses = [
            LLMResult(
                content=[{"type": "tool_use", "id": f"tool-{index}", "name": "run_shell", "input": {"cmd": f"printf {index}"}}],
                input_tokens=1,
                output_tokens=1,
                stop_reason="tool_use",
                model="fake-model",
            )
            for index in range(10)
        ]
        responses.append(LLMResult(content=[{"type": "text", "text": "Completed the extended investigation."}], input_tokens=1, output_tokens=1, stop_reason="end_turn", model="fake-model"))
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp)
            logger = EventLogger(workspace / "logs" / "actions.jsonl")
            fake = FakeLLM(responses)
            summary = AgentLoop(
                AgentConfig(workspace=workspace, max_iterations=1, token_budget=10_000),
                logger,
                fake,
                ToolRunner(logger, workspace),
            ).run()
            self.assertEqual(summary.iterations, 1)
            self.assertEqual(fake.calls, 11)

    def test_pause_until_daily_reset_does_not_spin_on_dust_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp)
            logger = EventLogger(workspace / "logs" / "actions.jsonl")
            fake = FakeLLM()
            ledger = DailyTokenLedger(workspace, logger, cap=100)
            data = ledger._read()
            data["used_tokens"] = 90  # 10 dust tokens available
            ledger._write(data)

            loop = AgentLoop(
                AgentConfig(workspace=workspace, max_iterations=1, token_budget=10_000, daily_ledger=ledger),
                logger,
                fake,
                ToolRunner(logger, workspace),
            )

            sleep_calls = 0

            def _fake_sleep(duration: float) -> None:
                nonlocal sleep_calls
                sleep_calls += 1
                if sleep_calls == 3:
                    # Trigger stop to exit the pause loop safely
                    (workspace / "STOP").write_text("stop", encoding="utf-8")

            with patch("time.sleep", side_effect=_fake_sleep):
                loop._pause_until_daily_reset()

            self.assertEqual(sleep_calls, 3)
            log_text = logger.path.read_text(encoding="utf-8")
            self.assertIn("daily_token_limit_paused", log_text)
            self.assertNotIn("daily_token_limit_resumed", log_text)

    def test_pause_until_daily_reset_resumes_on_budget_increase(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp)
            logger = EventLogger(workspace / "logs" / "actions.jsonl")
            fake = FakeLLM()
            ledger = DailyTokenLedger(workspace, logger, cap=100)
            data = ledger._read()
            data["used_tokens"] = 100  # 0 available
            ledger._write(data)

            loop = AgentLoop(
                AgentConfig(workspace=workspace, max_iterations=1, token_budget=10_000, daily_ledger=ledger),
                logger,
                fake,
                ToolRunner(logger, workspace),
            )

            sleep_calls = 0

            def _fake_sleep(duration: float) -> None:
                nonlocal sleep_calls
                sleep_calls += 1
                # Operator resets used tokens or increases budget
                d = ledger._read()
                d["used_tokens"] = 0
                ledger._write(d)

            with patch("agent.runtime.loop.time.sleep", side_effect=_fake_sleep):
                loop._pause_until_daily_reset()

            self.assertEqual(sleep_calls, 1)
            log_text = logger.path.read_text(encoding="utf-8")
            self.assertIn("daily_token_limit_paused", log_text)
            self.assertIn("daily_token_limit_resumed", log_text)


if __name__ == "__main__":
    unittest.main()
