"""Unit tests for multi-cycle plugin plug and unplug lifecycle."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any

from agent.infra.event_log import EventLogger
from agent.infra.untrusted import unwrap_untrusted
from agent.llm.llm import LLMResult
from agent.plugins.manager import PluginManager
from agent.runtime.loop import AgentConfig, AgentLoop
from agent.tools.base_tools import ToolRunner


class ScriptedLLM:
    def __init__(self, turns: list[list[dict[str, Any]]]) -> None:
        self.turns = list(turns)
        self.call_history: list[dict[str, Any]] = []
        self.tokens_used = 0
        self.base_model = "mock-model"
        self.provider = "mock"

    def call(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int,
    ) -> LLMResult:
        self.call_history.append({
            "system": system,
            "messages": list(messages),
            "tools": list(tools),
        })
        if self.turns:
            content = self.turns.pop(0)
        else:
            content = [{"type": "text", "text": "I have completed all tasks."}]
        return LLMResult(
            content=content,
            input_tokens=10,
            output_tokens=10,
            stop_reason="end_turn",
            model="mock-model",
        )


class PluginUnplugLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp())
        self.workspace = self.temp_dir / "workspace"
        self.workspace.mkdir(parents=True)
        self.config_dir = self.temp_dir / "config"
        self.config_dir.mkdir(parents=True)
        self.logger = EventLogger(self.workspace / "logs" / "actions.jsonl")
        self.shipped_dir = Path(__file__).resolve().parents[2] / "plugins"

        self.plugin_manager = PluginManager(
            workspace=self.workspace,
            config_dir=self.config_dir,
            shipped_dir=self.shipped_dir,
            logger=self.logger,
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_unplug_lifecycle_across_cycles(self) -> None:
        # 1. Enable 'hello' plugin
        self.plugin_manager.enable_by_human("hello")

        # Turn 1 (Cycle 1): model calls 'hello.greet'
        turn1_call = [
            {"type": "tool_use", "id": "call_1", "name": "hello.greet", "input": {"greeting": "Greetings"}}
        ]
        # Turn 2 (Cycle 1): model finishes cycle 1 with text
        turn1_finish = [{"type": "text", "text": "Cycle 1 report: hello plugin tested."}]

        # Turn 3 (Cycle 2): model attempts to call vanished tool 'hello.greet'
        turn2_call_vanished = [
            {"type": "tool_use", "id": "call_2", "name": "hello.greet", "input": {"greeting": "Hello again"}}
        ]
        # Turn 4 (Cycle 2): model observes error and reports
        turn2_finish = [{"type": "text", "text": "Cycle 2 report: observed tool was no longer available."}]

        scripted_turns = [turn1_call, turn1_finish, turn2_call_vanished, turn2_finish]
        llm = ScriptedLLM(scripted_turns)

        runner = ToolRunner(self.logger, self.workspace)
        runner.plugins = self.plugin_manager

        # Hook on_cycle to disable plugin between cycle 1 and cycle 2
        def cycle_callback(cycle: int, report: str, tokens: int) -> None:
            if cycle == 1:
                # Disable plugin before cycle 2 begins
                self.plugin_manager.disable_by_human("hello")

        config = AgentConfig(
            workspace=self.workspace,
            max_iterations=2,
            retrieve_memories=False,
            plugins=self.plugin_manager,
            on_cycle=cycle_callback,
        )

        agent = AgentLoop(config, self.logger, llm, runner)
        summary = agent.run()

        # Core completed 2 full cycles cleanly!
        self.assertEqual(summary.iterations, 2)
        self.assertEqual(summary.reason, "max_iterations")

        # Check call 1 (Cycle 1): plugin was enabled
        cycle1_call = llm.call_history[0]
        cycle1_tool_names = {t["name"] for t in cycle1_call["tools"]}
        self.assertIn("hello.greet", cycle1_tool_names)
        self.assertIn("hello capability", cycle1_call["system"])

        # Check call 3 (Cycle 2): plugin was UNPLUGGED at boundary
        cycle2_call = llm.call_history[2]
        cycle2_tool_names = {t["name"] for t in cycle2_call["tools"]}
        # Tool is gone from offered definitions!
        self.assertNotIn("hello.greet", cycle2_tool_names)
        # Embodiment is gone from system prompt!
        self.assertNotIn("hello capability", cycle2_call["system"])
        # No leftover active references in prompts
        self.assertNotIn("[Plugin: hello]", cycle2_call["system"])

        # Check tool result delivered to model in call 4 (response to call_2)
        cycle2_resp_messages = llm.call_history[3]["messages"]
        last_user_msg = cycle2_resp_messages[-1]["content"]
        tool_result = last_user_msg[0]
        self.assertEqual(tool_result["type"], "tool_result")
        raw_content = tool_result["content"]
        if "<UNTRUSTED_DATA" in raw_content:
            raw_content = unwrap_untrusted(raw_content)
        result_content = json.loads(raw_content)
        self.assertFalse(result_content["ok"])
        self.assertEqual(
            result_content["error"],
            "tool no longer available: plugin hello disabled",
        )
