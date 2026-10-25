"""Mock tests for routing chat to autonomous loop, noted decisions, and startup version checks.

Verifies:
1. Plain chat lands in HumanInbox with kind "chat" (prefixed "Human said: ...") and is shown to the loop.
2. A "noted" decision is logged with a reason and creates no unnecessary plan goal.
3. Conversation context includes recent decisions and top plan items.
4. Memory migration removes old framing, keeps backups, and preserves unrelated lines.
5. Startup self-check logs code_version and warns on suspected stale image.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest

from agent.tests.test_helpers import ensure_test_base_model

ensure_test_base_model()
from pathlib import Path
from typing import Any

from agent.infra.event_log import EventLogger
from agent.learning.memory_migration import migrate_memory_store
from agent.learning.plan import PlanStore
from agent.llm.llm import LLMResult
from agent.runtime.loop import AgentConfig, AgentLoop
from agent.session.session import HumanInbox
from agent.tools.base_tools import ToolRunner
from agent.ui.version_check import compute_agent_source_hash, verify_startup_code_version
from agent.ui.wake import WakeCoordinator


class FakeScriptedLLM:
    """Mock LLM capturing prompts and returning valid cycle reports."""

    def __init__(self) -> None:
        self.model = "mock-autonomy"
        self.provider = "mock"
        self.last_system: str | None = None
        self.last_messages: list[dict[str, Any]] = []

    def call(self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]], max_tokens: int, **kwargs: Any) -> LLMResult:
        self.last_system = system
        self.last_messages = messages
        return LLMResult(
            [{"type": "text", "text": "I reviewed the status and took note of the input."}],
            input_tokens=10,
            output_tokens=15,
            stop_reason="end_turn",
            model=self.model,
        )


class ChatAutonomyTests(unittest.TestCase):
    """Test suite for ordinary chat routing, decisions, and image version verification."""

    def test_plain_chat_lands_in_inbox_with_kind_chat_and_is_shown_to_loop(self) -> None:
        """Verify plain chat message is added with kind 'chat' and reaches loop input prompt."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logger = EventLogger(root / "logs" / "actions.jsonl")
            coord = WakeCoordinator(root, max_iterations=1)
            fake_llm = FakeScriptedLLM()
            coord._llm = fake_llm

            # Route ordinary chat message
            coord.receive_human_input("Human said: Hello SELF, how are you?", kind="chat")

            # Verify inbox file record has kind="chat"
            inbox_file = root / "state" / "human_input.jsonl"
            self.assertTrue(inbox_file.exists())
            records = [json.loads(line) for line in inbox_file.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["kind"], "chat")
            self.assertEqual(records[0]["text"], "Human said: Hello SELF, how are you?")

            # Run a 1-cycle loop to verify the human message reaches loop's prompt
            runner = ToolRunner(logger, root)
            runner.identity = coord.identity
            loop = AgentLoop(
                AgentConfig(
                    workspace=root,
                    max_iterations=1,
                    input_provider=coord.inbox.consume,
                    session_id="test-session",
                ),
                logger,
                fake_llm,
                runner,
            )
            loop.run()

            # Verify prompt seen by LLM includes the chat input under human inputs to weigh
            user_msg = fake_llm.last_messages[0]["content"]
            self.assertIn("Human inputs to weigh since the prior cycle:", user_msg)
            self.assertIn("Human said: Hello SELF, how are you?", user_msg)
            self.assertIn("accepted, modified, declined, deferred, or noted", user_msg)

    def test_noted_decision_logged_with_reason_and_no_unnecessary_plan_item(self) -> None:
        """Verify 'noted' decision requires reason, logs event, and adds no goal item."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logger = EventLogger(root / "logs" / "actions.jsonl")
            store = PlanStore(root, logger)
            store.initialize("test seed")
            initial_goals_count = len(store.items)

            # Rejection on empty reason
            err_res = store.record_human_input_decision("just saying hi", "noted", reason="")
            self.assertFalse(err_res["ok"])
            self.assertIn("reason", err_res["error"])

            # Valid noted decision
            res = store.record_human_input_decision(
                "just saying hi",
                "noted",
                reason="Casual greeting; no operational change needed.",
                cycle=2,
            )
            self.assertTrue(res["ok"])
            self.assertEqual(res["decision"], "noted")
            self.assertIsNone(res.get("goal_id"))

            # Plan items count should remain unchanged
            self.assertEqual(len(store.items), initial_goals_count)

            # Verify persisted in plan.json
            reloaded = PlanStore(root, logger)
            self.assertTrue(reloaded.load())
            self.assertEqual(len(reloaded.human_input_decisions), 1)
            decision_rec = reloaded.human_input_decisions[0]
            self.assertEqual(decision_rec["decision"], "noted")
            self.assertEqual(decision_rec["input"], "just saying hi")
            self.assertEqual(decision_rec["reason"], "Casual greeting; no operational change needed.")

            # Verify actions.jsonl logged event
            events = [
                json.loads(line) for line in (root / "logs" / "actions.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            decision_events = [e for e in events if e.get("event") == "human_input_decision"]
            self.assertEqual(len(decision_events), 1)
            self.assertEqual(decision_events[0]["decision"], "noted")
            self.assertEqual(decision_events[0]["reason"], "Casual greeting; no operational change needed.")
            plan_events = [e for e in events if e.get("event") == "plan_updated" and e.get("cycle") == 2]
            self.assertEqual(len(plan_events), 1)
            self.assertEqual(plan_events[0]["plan_version"], res["plan_version"])

    def test_conversation_context_includes_recent_decisions_and_top_plan(self) -> None:
        """Verify conversation context includes recent decisions and top active plan items."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logger = EventLogger(root / "logs" / "actions.jsonl")
            coord = WakeCoordinator(root, max_iterations=1)
            coord.boot()

            # Record a human input decision in plan_store
            coord.plan_store.record_human_input_decision(
                "inspect /tmp",
                "accepted",
                reason="Valid request to inspect temporary filesystem",
                priority=1,
                cycle=1,
            )

            context = coord.conversation_context()
            self.assertIn("Active plan items:", context)
            self.assertIn("Recent human input decisions:", context)
            self.assertIn("inspect /tmp", context)
            self.assertIn("Valid request to inspect temporary filesystem", context)

    def test_memory_migration_removes_old_framing_and_preserves_backup(self) -> None:
        """Verify migrate_memory_store removes old subservient framing while keeping backup."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state_dir = root / "state"
            state_dir.mkdir(parents=True, exist_ok=True)
            mem_path = state_dir / "memory.jsonl"

            # Create test records: one normal, two with old framing phrases
            rec1 = {"timestamp": "2026-10-17T01:00:00Z", "what_was_tried": "test1", "outcome": "completed", "lesson": "All good.", "tags": ["tag1"]}
            rec2 = {
                "timestamp": "2026-10-17T02:00:00Z",
                "what_was_tried": "Cycle 6: standing exploration goal",
                "outcome": "completed",
                "lesson": "Raw data – ensures we have the source text for verification.",
                "tags": ["service", "us"],
            }
            rec3 = {
                "timestamp": "2026-10-17T03:00:00Z",
                "what_was_tried": "Cycle 12",
                "outcome": "completed",
                "lesson": "This ensures we can continue mapping without waiting for a new tool.",
                "tags": ["find"],
            }
            with mem_path.open("w", encoding="utf-8") as f:
                for r in (rec1, rec2, rec3):
                    f.write(json.dumps(r) + "\n")

            # Run migration
            result = migrate_memory_store(root)
            self.assertTrue(result["ok"])
            self.assertEqual(len(result["changes"]), 2)

            # Check backup exists
            backup_files = list(state_dir.glob("memory.jsonl.*.bak"))
            self.assertTrue(len(backup_files) >= 1)

            # Verify migrated content
            new_lines = [json.loads(l) for l in mem_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(new_lines), 3)

            # Unrelated line unchanged
            self.assertEqual(new_lines[0]["lesson"], "All good.")

            # Changed lines no longer have old phrases
            self.assertNotIn("ensures we have", new_lines[1]["lesson"])
            self.assertIn("ensures the agent retains the source text", new_lines[1]["lesson"])
            self.assertNotIn("us", new_lines[1]["tags"])

            self.assertNotIn("ensures we can continue", new_lines[2]["lesson"])
            self.assertIn("ensures I can continue", new_lines[2]["lesson"])

    def test_startup_self_check_logs_code_version_and_warns_on_stale_image(self) -> None:
        """Verify startup self-check logs code_version and warns on hash mismatch."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logger = EventLogger(root / "logs" / "actions.jsonl")

            # 1. Normal startup check
            info = verify_startup_code_version(logger)
            self.assertTrue(info["plan_store_present"])
            self.assertIsInstance(info["source_hash"], str)
            self.assertFalse(info["stale_image_suspected"])

            # 2. Check logged event
            events = [
                json.loads(line) for line in (root / "logs" / "actions.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            version_events = [e for e in events if e.get("event") == "code_version"]
            self.assertEqual(len(version_events), 1)
            self.assertTrue(version_events[0]["plan_store_present"])
            self.assertEqual(version_events[0]["source_hash"], info["source_hash"])

            # 3. Simulate host passing a mismatching source hash
            old_env = os.environ.get("HOST_AGENT_SOURCE_HASH")
            try:
                os.environ["HOST_AGENT_SOURCE_HASH"] = "mismatched_deadbeef12345678"
                info2 = verify_startup_code_version(logger)
                self.assertTrue(info2["stale_image_suspected"])

                events2 = [
                    json.loads(line) for line in (root / "logs" / "actions.jsonl").read_text(encoding="utf-8").splitlines()
                ]
                stale_events = [e for e in events2 if e.get("event") == "stale_image_suspected"]
                self.assertEqual(len(stale_events), 1)
                self.assertEqual(stale_events[0]["expected_hash"], "mismatched_deadbeef12345678")
            finally:
                if old_env is None:
                    os.environ.pop("HOST_AGENT_SOURCE_HASH", None)
                else:
                    os.environ["HOST_AGENT_SOURCE_HASH"] = old_env


if __name__ == "__main__":
    unittest.main()
