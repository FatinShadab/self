"""Unit tests verifying core suite passes and operates cleanly with zero plugins."""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any

from agent.infra.event_log import EventLogger
from agent.llm.llm import LLMResult
from agent.plugins.manager import PluginManager
from agent.runtime.loop import AgentConfig, AgentLoop
from agent.tools.base_tools import ToolRunner


class ScriptedZeroLLM:
    def __init__(self) -> None:
        self.call_history: list[dict[str, Any]] = []
        self.tokens_used = 0
        self.base_model = "mock-base"
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
        return LLMResult(
            content=[{"type": "text", "text": "Cycle report: baseline exploration with zero plugins."}],
            input_tokens=10,
            output_tokens=10,
            stop_reason="end_turn",
            model="mock-base",
        )


class ZeroPluginsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp())
        self.workspace = self.temp_dir / "workspace"
        self.workspace.mkdir(parents=True)
        self.config_dir = self.temp_dir / "config"
        self.config_dir.mkdir(parents=True)
        self.logger = EventLogger(self.workspace / "logs" / "actions.jsonl")

        self.plugin_manager = PluginManager(
            workspace=self.workspace,
            config_dir=self.config_dir,
            shipped_dir=self.temp_dir / "empty_shipped",
            logger=self.logger,
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_run_with_zero_plugins(self) -> None:
        llm = ScriptedZeroLLM()
        runner = ToolRunner(self.logger, self.workspace)
        runner.plugins = self.plugin_manager

        config = AgentConfig(
            workspace=self.workspace,
            max_iterations=1,
            retrieve_memories=False,
            plugins=self.plugin_manager,
        )

        agent = AgentLoop(config, self.logger, llm, runner)
        summary = agent.run()

        self.assertEqual(summary.iterations, 1)
        self.assertEqual(summary.reason, "max_iterations")

        call = llm.call_history[0]
        self.assertNotIn("Active Plugins", call["system"])
        self.assertNotIn("Active Plugins Notes", call["messages"][0]["content"])

        # No plugin tools in offered definitions
        tool_names = [t["name"] for t in call["tools"]]
        for t in tool_names:
            self.assertNotIn(".", t)
