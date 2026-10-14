from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from base_tools import ToolRunner
from event_log import EventLogger
from llm import BudgetedLLM, LLMResult
from loop import AgentConfig, AgentLoop
from tool_registry import KeywordToolSearch, ToolRegistry, schema_from_code


DISK_CODE = '''import shutil
def run(path: str = "/home/entity") -> dict:
    usage = shutil.disk_usage(path)
    return {"path": path, "total_bytes": usage.total, "used_bytes": usage.used,
            "free_bytes": usage.free, "used_percent": round(100 * usage.used / usage.total, 2)}
'''
DISK_TEST = '''import tempfile
import unittest
from tool import run
class DiskTests(unittest.TestCase):
    def test_usage(self):
        with tempfile.TemporaryDirectory() as path:
            result = run(path)
            self.assertGreater(result["total_bytes"], 0)
            self.assertGreaterEqual(result["used_bytes"], 0)
            self.assertLessEqual(result["used_bytes"] + result["free_bytes"], result["total_bytes"])
            self.assertGreaterEqual(result["used_percent"], 0)
            self.assertLessEqual(result["used_percent"], 100)
    def test_missing_path(self):
        with self.assertRaises(FileNotFoundError):
            run("/nonexistent-self-disk-test-path")
'''


def result(content: list[dict]) -> LLMResult:
    return LLMResult(content, 10, 5, "end_turn", "test-double")


class Reviewer:
    def __init__(self, verdict: dict | None = None):
        self.calls = 0
        self.verdict = verdict if verdict is not None else {"approved": True, "issues": []}

    def call(self, **kwargs):
        self.calls += 1
        return result([{"type": "text", "text": json.dumps(self.verdict)}])


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name)
        self.logger = EventLogger(self.workspace / "logs" / "actions.jsonl")
        self.reviewer = Reviewer()
        self.registry = ToolRegistry(self.workspace, self.logger, self.reviewer.call, set())

    def tearDown(self):
        self.temp.cleanup()

    def create(self, code=DISK_CODE, test=DISK_TEST):
        return self.registry.create_tool("disk_usage_summary", "Summarize disk usage free used total capacity", code, test)

    def test_saved_tested_retrieved_reused_and_versioned(self):
        self.assertTrue(self.create()["ok"])
        folder = self.workspace / "tools" / "disk_usage_summary"
        for file in ("tool.py", "test_tool.py", "meta.json"):
            self.assertTrue((folder / file).exists())
        self.assertEqual(self.reviewer.calls, 1)
        self.assertEqual(self.registry.retrieve("disk usage", 1)[0]["name"], "disk_usage_summary")
        self.assertEqual(self.registry.retrieve("unrelated zebra", 1), [])
        fresh = ToolRegistry(self.workspace, self.logger, self.reviewer.call, set())
        observed = fresh.execute("disk_usage_summary", {"path": str(self.workspace)})
        self.assertTrue(observed["ok"])
        self.assertGreater(observed["result"]["total_bytes"], 0)
        self.assertEqual(self.create(code=DISK_CODE + "\n# Version two\n")["version"], 2)
        self.assertEqual((folder / "history" / "v0001" / "tool.py").read_text(), DISK_CODE)
        self.assertEqual(json.loads((folder / "meta.json").read_text())["version"], 2)

    def test_failed_update_preserves_registered_version(self):
        self.assertTrue(self.create()["ok"])
        failed = self.create(test=DISK_TEST.replace('self.assertGreater(result["total_bytes"], 0)', 'self.assertEqual(1, 2)'))
        self.assertFalse(failed["ok"])
        self.assertIn("AssertionError", failed["traceback"])
        self.assertEqual(self.registry.execute("disk_usage_summary", {"path": str(self.workspace)})["version"], 1)

    def test_three_failures_write_lesson_and_block_fourth(self):
        self.reviewer.verdict = {"approved": False, "issues": ["Leaks a secret to stdout"]}
        for attempt in range(1, 4):
            failed = self.create()
            self.assertEqual(failed["attempts_remaining"], 3 - attempt)
            self.assertFalse(failed["ok"])
        self.assertFalse(self.create()["ok"])
        self.assertEqual(self.reviewer.calls, 3)
        self.assertTrue((self.workspace / "memory" / "lessons.jsonl").exists())
        self.assertEqual(self.registry.retrieve("disk", 5), [])

    def test_timeout_no_tests_and_malformed_critic_never_register(self):
        self.registry.test_timeout = 0.2
        failed = self.create(test="import time\ntime.sleep(10)\n")
        self.assertFalse(failed["ok"])
        self.assertIn("timed out", failed["traceback"])
        self.registry.test_timeout = 15
        failed = self.create(test="import unittest\n")
        self.assertIn("No unittest tests", failed["traceback"])
        self.reviewer.verdict = {"approved": True}
        self.assertFalse(self.create()["ok"])
        self.assertEqual(self.registry.tools, {})

    def test_external_mutation_unloads_tool(self):
        self.assertTrue(self.create()["ok"])
        (self.workspace / "tools" / "disk_usage_summary" / "tool.py").write_text("def run(): return 0")
        self.registry.refresh()
        self.assertEqual(self.registry.tools, {})

    def test_schema_and_argument_validation(self):
        schema = schema_from_code('def run(path: str, count: int = 3): return {}')
        self.assertEqual(schema["required"], ["path"])
        self.assertTrue(self.create()["ok"])
        with self.assertRaises(Exception):
            self.registry.execute("disk_usage_summary", {"path": 42})

    def test_only_top_k_relevant_descriptions_selected(self):
        tools = [{"name": "disk_one", "description": "disk usage"},
                 {"name": "disk_two", "description": "disk usage free capacity"},
                 {"name": "packages", "description": "installed software"}]
        selected = KeywordToolSearch().search("disk usage free", tools, 1)
        self.assertEqual([item["name"] for item in selected], ["disk_two"])

    def test_critic_rejection_prevents_module_execution(self):
        marker = self.workspace / "unexpected-execution"
        code = f'from pathlib import Path\nPath({str(marker)!r}).touch()\n' + DISK_CODE
        self.reviewer.verdict = {"approved": False, "issues": ["Unexpected module-level write"]}
        failed = self.create(code=code)
        self.assertFalse(failed["ok"])
        self.assertFalse(marker.exists())
        self.assertNotIn('"event":"tool_test"', self.logger.path.read_text())

    def test_credential_literals_are_not_saved(self):
        with patch.dict(os.environ, {"SELF_TEST_SECRET": "fake-secret-only-for-tests"}):
            logger = EventLogger(self.workspace / "logs" / "secret-test.jsonl")
            registry = ToolRegistry(self.workspace, logger, self.reviewer.call, set())
            failed = registry.create_tool("disk_usage_summary", "disk usage", DISK_CODE + '\n# fake-secret-only-for-tests', DISK_TEST)
            self.assertFalse(failed["ok"])
            self.assertEqual(self.reviewer.calls, 0)
            for path in self.workspace.rglob("*"):
                if path.is_file():
                    self.assertNotIn("fake-secret-only-for-tests", path.read_text())

    def test_generated_tool_runtime_is_bounded(self):
        code = 'import time\ndef run(delay: float = 0.0) -> dict:\n    time.sleep(delay)\n    return {"done": True}\n'
        test = 'import unittest\nfrom tool import run\nclass Test(unittest.TestCase):\n    def test_run(self): self.assertTrue(run()["done"])\n'
        self.assertTrue(self.create(code=code, test=test)["ok"])
        self.registry.execution_timeout = 0.1
        timed = self.registry.execute("disk_usage_summary", {"delay": 10.0})
        self.assertFalse(timed["ok"])
        self.assertTrue(timed["timed_out"])


class ScriptedDiskAgent:
    """Offline test double; actor and critic calls traverse the production loop."""
    def __init__(self, create: bool):
        self.create = create
        self.actor_calls = 0
        self.selections = []

    def call(self, *, system, messages, tools, max_tokens):
        if not tools:
            return result([{"type": "text", "text": '{"approved": true, "issues": []}'}])
        self.actor_calls += 1
        self.selections.append([tool["name"] for tool in tools])
        if self.create and self.actor_calls == 1:
            return result([{"type": "tool_use", "id": "create-1", "name": "create_tool", "input": {
                "name": "disk_usage_summary", "description": "Summarize disk usage free used total capacity",
                "code": DISK_CODE, "test_code": DISK_TEST}}])
        execution_step = 2 if self.create else 1
        if self.actor_calls == execution_step:
            return result([{"type": "tool_use", "id": "run-1", "name": "disk_usage_summary", "input": {"path": "/tmp"}}])
        return result([{"type": "text", "text": "Saved, tested, retrieved and reused the disk usage summary tool."}])


class LoopToolTests(unittest.TestCase):
    def test_creation_mid_run_and_reuse_later_run_with_critic_spend(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp)
            logger = EventLogger(workspace / "logs" / "actions.jsonl")
            first = ScriptedDiskAgent(create=True)
            config = AgentConfig(workspace=workspace, max_iterations=1, token_budget=50000, task="disk usage summary", top_k_tools=1)
            summary = AgentLoop(config, logger, first, ToolRunner(logger, workspace)).run()
            self.assertEqual(summary.tokens_used, 60)  # actor x3 + critic x1
            self.assertNotIn("disk_usage_summary", first.selections[0])
            self.assertIn("disk_usage_summary", first.selections[1])
            second = ScriptedDiskAgent(create=False)
            summary = AgentLoop(config, logger, second, ToolRunner(logger, workspace)).run()
            self.assertEqual(summary.tokens_used, 30)
            self.assertIn("disk_usage_summary", second.selections[0])
            events = [json.loads(line) for line in logger.path.read_text().splitlines()]
            self.assertEqual(sum(e["event"] == "custom_tool_executed" for e in events), 2)

    def test_budget_prevents_critic_and_registration(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp)
            logger = EventLogger(workspace / "logs" / "actions.jsonl")
            reviewer = Reviewer()
            budget = BudgetedLLM(reviewer, logger, 1)
            registry = ToolRegistry(workspace, logger, budget.call, set())
            from llm import BudgetExceeded
            with self.assertRaises(BudgetExceeded):
                registry.create_tool("disk_usage_summary", "disk usage", DISK_CODE, DISK_TEST)
            self.assertEqual(reviewer.calls, 0)
            self.assertEqual(registry.tools, {})


if __name__ == "__main__":
    unittest.main()
