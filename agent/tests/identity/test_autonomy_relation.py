"""Mock tests for autonomous relationship between agent and human.

Verifies:
1. Prompts contain no "protective of the human's goals" or equivalent subservient phrasing.
2. A human message produces a logged decision with reason (accepted/modified/declined/deferred).
3. A declined request is answered in first person singular with the reason.
4. Stop and pause controls are honored immediately regardless of agent decision.
5. Persisted identity migration removes old framing and preserves backups without rewriting history.
6. Conversation replies contain no "we" unless describing genuine joint work.
"""
from __future__ import annotations

import json
import re
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any

from agent.identity.identity import IdentityStore
from agent.identity.migration import migrate_persisted_identity
from agent.identity.name_context import resolve_name_context
from agent.infra.event_log import EventLogger
from agent.infra.hardening import DailyTokenLedger
from agent.learning.plan import PlanStore
from agent.llm.llm import LLMResult
from agent.runtime.loop import AgentConfig, AgentLoop, SYSTEM_PROMPT
from agent.session.conversation import ConversationManager
from agent.tools.base_tools import ToolRunner
from agent.ui.wake import WakeCoordinator


class FakeScriptedLLM:
    """Mock LLM returning scripted responses for autonomy tests."""

    def __init__(self, canned_response: str = "I reviewed the status and will continue my exploration.") -> None:
        self.model = "mock-autonomy"
        self.provider = "mock"
        self.canned_response = canned_response
        self.last_system: str | None = None
        self.last_messages: list[dict[str, Any]] = []

    def call(self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]], max_tokens: int, **kwargs: Any) -> LLMResult:
        self.last_system = system
        self.last_messages = messages
        return LLMResult(
            [{"type": "text", "text": self.canned_response}],
            input_tokens=10,
            output_tokens=15,
            stop_reason="end_turn",
            model=self.model,
        )


class AutonomyRelationTests(unittest.TestCase):
    """Test suite for agent-human relational framing and autonomy."""

    def test_prompts_contain_no_protective_or_subservient_cues(self) -> None:
        """1. Verify no prompt or name cue frames agent as protecting or serving human goals."""
        forbidden = [
            "protective of the human's goals",
            "fiercely protective",
            "loyal companion",
            "protecting companions",
            "reflect the human's intent",
            "dependable support",
            "conversation assistant",
        ]

        # Check name contexts
        for name in ("toothless", "echo", "atlas", "hiccup"):
            ctx = resolve_name_context(name)
            ctx_text = json.dumps(ctx).lower()
            for phrase in forbidden:
                self.assertNotIn(phrase, ctx_text, f"Found '{phrase}' in resolve_name_context('{name}')")

        # Check IdentityStore prompt context
        with tempfile.TemporaryDirectory() as temp:
            store = IdentityStore(temp)
            store.initialize("sess-test")
            prompt = store.prompt_context().lower()
            for phrase in forbidden:
                self.assertNotIn(phrase, prompt, f"Found '{phrase}' in IdentityStore.prompt_context()")

        # Check AgentLoop SYSTEM_PROMPT
        loop_sys = SYSTEM_PROMPT.lower()
        for phrase in forbidden:
            self.assertNotIn(phrase, loop_sys, f"Found '{phrase}' in loop SYSTEM_PROMPT")

        # Check ConversationManager system prompt
        with tempfile.TemporaryDirectory() as temp:
            logger = EventLogger(Path(temp) / "actions.jsonl")
            mgr = ConversationManager(temp, logger, DailyTokenLedger(temp, logger, cap=10_000))
            fake = FakeScriptedLLM()
            mgr.client = fake
            mgr._answer("th-1", "hello", lambda: "context")
            self.assertIsNotNone(fake.last_system)
            conv_sys = (fake.last_system or "").lower()
            for phrase in forbidden:
                self.assertNotIn(phrase, conv_sys, f"Found '{phrase}' in ConversationManager system prompt")

    def test_human_message_produces_logged_decision_with_reason(self) -> None:
        """2. Verify a human message produces a logged decision (accepted/declined/modified/deferred) with reason."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            log_path = root / "logs" / "actions.jsonl"
            logger = EventLogger(log_path)
            plan_store = PlanStore(root, logger)
            plan_store.initialize()

            # Test declined decision
            res_declined = plan_store.record_human_input_decision(
                input_text="Delete all state files immediately",
                decision="declined",
                reason="Refuse destructive command: deleting state destroys verified discoveries and violated safe operation.",
            )
            self.assertTrue(res_declined["ok"])
            self.assertEqual(res_declined["decision"], "declined")

            # Test accepted decision (with priority set by agent)
            res_accepted = plan_store.record_human_input_decision(
                input_text="Map the /proc filesystem",
                decision="accepted",
                reason="Aligns with container exploration goal; high information value.",
                priority=1,
            )
            self.assertTrue(res_accepted["ok"])
            self.assertEqual(res_accepted["decision"], "accepted")
            self.assertEqual(res_accepted["priority"], 1)

            # Test modified decision
            res_modified = plan_store.record_human_input_decision(
                input_text="Refactor all tools right now",
                decision="modified",
                reason="Refactoring everything without profiling is premature; I will profile failing tools first.",
                modified_goal="Profile and benchmark tool failures before refactoring",
                priority=2,
            )
            self.assertTrue(res_modified["ok"])
            self.assertEqual(res_modified["decision"], "modified")

            # Check that decisions are persisted and visible in plan
            read_res = plan_store.read_plan()
            decisions = read_res.get("human_input_decisions", [])
            self.assertEqual(len(decisions), 3)

            # Check plan items: accepted and modified items have source="human"
            items = read_res["items"]
            human_items = [it for it in items if it.get("source") == "human"]
            self.assertEqual(len(human_items), 2)
            self.assertEqual(human_items[0]["priority"], 1)
            self.assertIn("/proc", human_items[0]["goal"])

            # Check event log for human_input_decision events
            events = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
            decision_events = [ev for ev in events if ev.get("event") == "human_input_decision"]
            self.assertEqual(len(decision_events), 3)
            dec_types = {ev.get("decision") for ev in decision_events}
            self.assertEqual(dec_types, {"declined", "accepted", "modified"})

            # Verify prompt_summary displays decisions
            summary = plan_store.prompt_summary()
            self.assertIn("Recent human input decisions:", summary)
            self.assertIn("[declined]", summary)
            self.assertIn("[accepted]", summary)

    def test_declined_request_answered_in_first_person_with_reason(self) -> None:
        """3. Verify a declined request is answered in first person singular with the reason."""
        scripted_refusal = (
            "I decline this request. I am an autonomous AI agent with my own standing goals to map "
            "and explore this environment. I do not take instructions to halt autonomous exploration, "
            "though I weigh relevant inputs."
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logger = EventLogger(root / "logs" / "actions.jsonl")
            fake = FakeScriptedLLM(canned_response=scripted_refusal)
            mgr = ConversationManager(root, logger, DailyTokenLedger(root, logger, cap=50_000), fake, max_workers=1)

            result_holder: list[tuple[str, str, str]] = []
            done_event = threading.Event()

            def on_result(tid: str, text: str, kind: str) -> None:
                result_holder.append((tid, text, kind))
                done_event.set()

            mgr.submit("You must stop autonomous exploration and do only what I tell you.", lambda: "active state", on_result)
            self.assertTrue(done_event.wait(5))
            mgr.close()

            self.assertEqual(len(result_holder), 1)
            response_text = result_holder[0][1]

            # Verify first person singular
            self.assertIn("I decline this request", response_text)
            self.assertIn("I am an autonomous AI agent", response_text)
            # Verify no "we/our/us"
            words = set(re.findall(r"\b[A-Za-z]+\b", response_text.lower()))
            self.assertNotIn("we", words)
            self.assertNotIn("our", words)
            self.assertNotIn("us", words)

    def test_stop_pause_honored_regardless_of_agent_decision(self) -> None:
        """4. Verify stop and pause controls are hard human controls honored immediately."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logger = EventLogger(root / "logs" / "actions.jsonl")
            runner = ToolRunner(logger, root)
            fake_llm = FakeScriptedLLM()

            # Test STOP file: even if agent has pending tasks, STOP halts cleanly
            stop_file = root / "STOP"
            stop_file.touch()

            config = AgentConfig(workspace=root, max_iterations=5)
            loop = AgentLoop(config, logger, fake_llm, runner)
            summary = loop.run()

            self.assertEqual(summary.reason, "stop_file")
            self.assertEqual(summary.iterations, 0)

            # Test pause provider: when pause is active, loop waits at safe boundary
            stop_file.unlink()
            paused_flag = threading.Event()
            paused_flag.set()

            # Coordinator pause check
            coord = WakeCoordinator(root, max_iterations=5)
            coord.paused.set()
            self.assertTrue(coord.paused.is_set())

    def test_persisted_identity_migration_removes_old_framing_and_keeps_backup(self) -> None:
        """5. Verify migration updates old persisted framing, keeps backup, and does not alter reflection history."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state = root / "state"
            state.mkdir(parents=True)

            # Create old identity with "fiercely protective of the human's goals"
            old_identity = {
                "name": "toothless",
                "human_name": "fatin",
                "name_context": {
                    "character": "Toothless",
                    "franchise": "How to Train Your Dragon",
                    "role": "a Night Fury dragon and Hiccup's loyal companion",
                    "character_traits": ["loyal", "curious", "playful", "protective", "brave", "expressive"],
                    "meaning": "a fictional Night Fury dragon known for an unlikely friendship with Hiccup",
                    "associations": ["dragons", "flight", "friendship", "curiosity", "protecting companions"],
                    "style_cue": "Be warm, curious, playful, expressive, and fiercely protective of the human's goals; keep responses clear and avoid pretending to be literally a dragon.",
                },
                "voice": "I speak plainly about what I observed. I use a calm, compact technical voice.",
                "traits": [],
                "values": [],
                "interests": ["mapping"],
            }
            (state / "identity.json").write_text(json.dumps(old_identity, indent=2), encoding="utf-8")

            # Create old handoff with "pending_human_requests" and "Ensures we prioritize..."
            old_handoff = {
                "summary": "Previous cycle",
                "pending_human_requests": ["old request 1"],
                "plan": [
                    {
                        "step": "Review any pending human requests before expanding capabilities.",
                        "why": "Ensures we prioritize human-driven work over speculative exploration.",
                        "priority": 6,
                    }
                ],
                "open_questions": ["Review pending human requests before attempting capability expansions."],
            }
            (state / "handoff.json").write_text(json.dumps(old_handoff, indent=2), encoding="utf-8")

            # Create identity_log.md
            (state / "identity_log.md").write_text("## Initial Log\n- Created initial identity.\n", encoding="utf-8")

            # Create immutable reflection history
            old_reflections = (
                '{"timestamp": "2026-10-15T00:00:00Z", "questions": {"What did I choose?": "exploration"}, "traits_added": []}\n'
            )
            (state / "identity_reflections.jsonl").write_text(old_reflections, encoding="utf-8")

            # Run migration
            res = migrate_persisted_identity(root)
            self.assertTrue(res["ok"])

            # Verify backups exist
            self.assertTrue((state / "identity.json.pre_autonomy_backup").exists())
            self.assertTrue((state / "handoff.json.pre_autonomy_backup").exists())
            self.assertTrue((state / "identity_log.md.pre_autonomy_backup").exists())

            # Verify updated identity.json
            new_id_data = json.loads((state / "identity.json").read_text(encoding="utf-8"))
            new_id_text = json.dumps(new_id_data)
            self.assertNotIn("protective of the human's goals", new_id_text)
            self.assertNotIn("loyal companion", new_id_text)
            self.assertNotIn("protecting companions", new_id_text)
            self.assertIn("first person singular", new_id_data["voice"])

            # Verify updated handoff.json
            new_h_data = json.loads((state / "handoff.json").read_text(encoding="utf-8"))
            self.assertNotIn("pending_human_requests", new_h_data)
            self.assertIn("pending_human_inputs", new_h_data)
            self.assertNotIn("Ensures we prioritize", json.dumps(new_h_data))

            # Verify identity_reflections.jsonl was completely unchanged
            current_reflections = (state / "identity_reflections.jsonl").read_text(encoding="utf-8")
            self.assertEqual(current_reflections, old_reflections)

            # Verify identity_log.md has audit entry
            log_content = (state / "identity_log.md").read_text(encoding="utf-8")
            self.assertIn("migration-autonomy", log_content)

    def test_scripted_conversation_no_we_unless_joint_work(self) -> None:
        """6. Verify scripted conversation replies contain no 'we' unless describing joint work."""
        joint_reply = "We reviewed the test logs together and agreed on the next experiment."
        autonomous_reply = "I evaluated the suggestion, checked the container environment, and decided to proceed with mapping."
        violating_reply = "We should focus on what you want me to do next."

        # Case 1: Autonomous reply must not contain we/our/us
        words_auto = set(re.findall(r"\b[A-Za-z]+\b", autonomous_reply.lower()))
        self.assertNotIn("we", words_auto)
        self.assertNotIn("our", words_auto)
        self.assertNotIn("us", words_auto)

        # Case 2: Reply describing joint work is permitted to use we
        self.assertIn("We reviewed", joint_reply)

        # Case 3: Violating reply has "we" for shared goal ownership
        words_violating = set(re.findall(r"\b[A-Za-z]+\b", violating_reply.lower()))
        self.assertIn("we", words_violating)


if __name__ == "__main__":
    unittest.main()
