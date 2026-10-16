"""SELF test learning module."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from agent.tools.base_tools import ToolRunner
from agent.infra.event_log import EventLogger
from agent.learning.learning import LearningStore
from agent.llm.llm import LLMResult
from agent.runtime.loop import AgentConfig, AgentLoop


class QuietLLM:
    def call(self, **_: Any) -> LLMResult:
        return LLMResult(
            content=[{"type": "text", "text": "Verified that local exploration can continue."}],
            input_tokens=7,
            output_tokens=3,
            stop_reason="end_turn",
            model="test",
        )


class LearningStoreTests(unittest.TestCase):
    def test_keyword_and_tag_retrieval(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logger = EventLogger(root / "logs" / "actions.jsonl")
            store = LearningStore(root, logger)
            store.initialize()
            store.append_memory("Measured disk usage", "completed", "Disk statistics are available.", ["disk", "storage"])
            store.append_memory("Listed packages", "completed", "Package inventory needs apt.", ["packages"])
            result = store.retrieve_memories("storage disk summary")
            self.assertIn("Disk statistics", result)
            self.assertNotIn("Package inventory", result)

    def test_map_entries_have_confidence_and_verification_time(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logger = EventLogger(root / "logs" / "actions.jsonl")
            store = LearningStore(root, logger)
            store.initialize()
            store.update_map([{"key": "network_reachability", "value": "example host reachable", "confidence": "medium", "evidence": "HTTP observation"}])
            data = json.loads((root / "state" / "map.json").read_text())
            required = {"os", "packages", "cpu", "ram", "disk", "network_reachability", "discovered_limits", "available_tools"}
            self.assertTrue(required.issubset(data["entries"]))
            for key in required:
                self.assertIn("confidence", data["entries"][key])
                self.assertIn("last_verified", data["entries"][key])
            self.assertEqual(data["entries"]["network_reachability"]["confidence"], "medium")

    def test_python_packages_alias_is_migrated_to_canonical_key(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logger = EventLogger(root / "logs" / "actions.jsonl")
            store = LearningStore(root, logger)
            store.initialize()
            store.update_map([{"key": "python_packages", "value": [{"name": "pip", "version": "1"}], "confidence": "high", "evidence": "pip list"}])
            store.initialize()
            data = json.loads((root / "state" / "map.json").read_text())
            self.assertEqual(data["entries"]["packages"]["value"][0]["name"], "pip")
            self.assertNotIn("python_packages", data["entries"])

    def test_loop_persists_each_cycle_and_compact_notes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logger = EventLogger(root / "logs" / "actions.jsonl")
            summary = AgentLoop(
                AgentConfig(workspace=root, max_iterations=3, token_budget=10_000, task="inspect disk"),
                logger,
                QuietLLM(),
                ToolRunner(logger, root),
            ).run()
            self.assertEqual(summary.iterations, 3)
            records = [json.loads(line) for line in (root / "state" / "memory.jsonl").read_text().splitlines()]
            self.assertEqual(len(records), 3)
            self.assertTrue(all({"what_was_tried", "outcome", "lesson", "tags"}.issubset(record) for record in records))
            self.assertLessEqual(len((root / "state" / "self_notes.md").read_text()), 6_001)

    def test_curriculum_uses_recent_successes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logger = EventLogger(root / "logs" / "actions.jsonl")
            store = LearningStore(root, logger)
            store.initialize()
            for _ in range(6):
                store.append_memory("practice", "completed", "worked", ["practice"])
            self.assertIn("local tool", store.propose_curriculum())


if __name__ == "__main__":
    unittest.main()
