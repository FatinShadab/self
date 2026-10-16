"""Fake-only checks for the fixed A/B harness arms."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.infra.event_log import EventLogger
from agent.llm.llm import LLMResult
from agent.runtime.loop import AgentConfig, AgentLoop
from agent.tools.base_tools import HELPER_TOOL_NAMES, ToolRunner
from agent.tools.tool_registry import ToolRegistry


class FakeLLM:
    base_model = "base"
    available_models = ["base", "helper"]
    provider = "fake"

    def __init__(self):
        self.calls = []

    def call(self, **kwargs):
        self.calls.append(kwargs)
        return LLMResult([{"type": "text", "text": "Done."}], 1, 1, "end_turn", kwargs.get("model") or "base")


class ABArmTests(unittest.TestCase):
    def test_off_removes_helper_tools_prompt_and_checkpoints(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"SELF_HELPER_MODELS":"off"}):
            root = Path(temp)
            logger = EventLogger(root / "logs/actions.jsonl")
            client = FakeLLM()
            runner = ToolRunner(logger, root)
            loop = AgentLoop(AgentConfig(workspace=root, max_iterations=1, token_budget=20000),
                             logger, client, runner)
            self.assertIsNone(loop.model_decisions)
            self.assertIsNone(loop.model_registry)
            self.assertNotIn("Helper models exist", loop._system_prompt())
            self.assertFalse(runner.execute("ask_model", {})["ok"])
            loop.run()
            offered = {tool["name"] for tool in client.calls[0]["tools"]}
            self.assertFalse(offered & HELPER_TOOL_NAMES)

    def test_on_keeps_helpers_and_forced_critic_uses_named_model(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logger = EventLogger(root / "logs/actions.jsonl")
            with patch.dict(os.environ, {"SELF_HELPER_MODELS":"on"}):
                client = FakeLLM()
                loop = AgentLoop(AgentConfig(workspace=root, max_iterations=1, token_budget=20000),
                                 logger, client, ToolRunner(logger, root))
                self.assertIsNotNone(loop.model_decisions)
                loop.run()
                offered = {tool["name"] for tool in client.calls[0]["tools"]}
                self.assertIn("ask_model", offered)
            seen = []

            def review(**kwargs):
                seen.append(kwargs.get("model"))
                return LLMResult([{"type":"text","text":'{"approved":true,"issues":[]}'}],
                                 1, 1, "end_turn", kwargs.get("model") or "base")

            registry = ToolRegistry(root, logger, review, set())
            code = "def run(value: int) -> int:\n    return value + 1\n"
            tests = "import unittest\nfrom tool import run\nclass T(unittest.TestCase):\n def test_run(self): self.assertEqual(run(1),2)\n"
            with patch.dict(os.environ, {"SELF_HELPER_MODELS":"off", "SELF_CRITIC_MODEL":"helper"}):
                registry.create_tool("increment_ab", "increment a value", code, tests)
            self.assertEqual(seen, ["helper"])
