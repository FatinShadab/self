from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from base_tools import ToolRunner
from event_log import EventLogger
from llm import LLMResult
from loop import AgentConfig, AgentLoop


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
    def test_configured_models_and_switch_tool_reach_agent(self) -> None:
        class ModelAwareLLM(FakeLLM):
            def __init__(self) -> None:
                super().__init__()
                self.provider = "ollama"
                self.base_model = "base-model"
                self.model = self.base_model
                self.available_models = [self.base_model, "other-model"]
                self.systems: list[str] = []
                self.offered_tools: list[list[str]] = []

            def select_model(self, model: str) -> dict[str, str]:
                if model not in self.available_models:
                    raise ValueError("unconfigured model")
                self.model = model
                return {"model": model}

            def call(self, **kwargs: Any) -> LLMResult:
                self.calls += 1
                self.systems.append(str(kwargs["system"]))
                self.offered_tools.append([tool["name"] for tool in kwargs["tools"]])
                if self.calls == 1:
                    return LLMResult(
                        content=[{"type": "tool_use", "id": "switch-1", "name": "select_model", "input": {"model": "other-model"}}],
                        input_tokens=1, output_tokens=1, stop_reason="tool_use", model=self.model,
                    )
                return LLMResult(
                    content=[{"type": "text", "text": "Continued with the selected model."}],
                    input_tokens=1, output_tokens=1, stop_reason="end_turn", model=self.model,
                )

        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp)
            logger = EventLogger(workspace / "logs" / "actions.jsonl")
            fake = ModelAwareLLM()
            AgentLoop(
                AgentConfig(workspace=workspace, max_iterations=1, token_budget=10_000),
                logger, fake, ToolRunner(logger, workspace),
            ).run()
            self.assertIn("Configured: base-model, other-model", fake.systems[0])
            self.assertIn("select_model", fake.offered_tools[0])
            self.assertIn("ask_brain", fake.offered_tools[0])
            self.assertIn("Current: other-model", fake.systems[1])
            self.assertEqual(fake.model, "other-model")

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


if __name__ == "__main__":
    unittest.main()
