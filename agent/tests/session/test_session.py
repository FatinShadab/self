"""SELF test session module."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from agent.infra.event_log import EventLogger
from agent.identity.identity import IdentityStore
from agent.llm.llm import LLMResult
from agent.session.session import HumanInbox, SessionStore
from agent.ui.wake import cardiac_monitor_frame, cardiac_monitor_intensity, escape_rich_markup, WakeCoordinator, clamped_plan_height, normalized_plan, visible_plan_items


class WakeFakeLLM:
    def __init__(self) -> None:
        self.calls = 0

    def call(self, **kwargs: Any) -> LLMResult:
        self.calls += 1
        system = str(kwargs.get("system", ""))
        if "durable handoff" in system:
            text = json.dumps({
                "summary": "I verified the saved state and continued safely.",
                "plan": [{"step": "Inspect state", "why": "keep facts current", "priority": 2, "status": "todo"}],
                "mood_of_run": "exploring", "failures_and_lessons": [], "open_questions": [],
            })
        else:
            text = "Completed a bounded wake-up exploration cycle."
        return LLMResult(content=[{"type": "text", "text": text}], input_tokens=4, output_tokens=3, stop_reason="end_turn", model="fake")


class SessionTests(unittest.TestCase):
    def test_escape_rich_markup_keeps_bracketed_tool_output_literal(self) -> None:
        from rich.text import Text
        from textual.widgets import Static

        message = "step: [bold]Cycle 8[/bold] [/usr/lib/apt/apt.systemd.daily update] ["
        escaped = escape_rich_markup(message)
        panel = "[b]Plan[/b]\n1. (todo) " + escaped

        self.assertEqual(Text.from_markup(panel).plain, f"Plan\n1. (todo) {message}")

        # This is the same rendering path used by the activity log. In the
        # pinned Textual version, ``markup=False`` does not stop Static from
        # parsing a string, so pass the escaped content explicitly.
        self.assertEqual(Static(escaped, markup=True).render_str(escaped).plain, message)

    def test_cardiac_monitor_frame_keeps_a_fixed_ascii_canvas(self) -> None:
        blank = cardiac_monitor_frame(0)
        pulse = cardiac_monitor_frame(6)
        wide_pulse = cardiac_monitor_frame(6, 48)

        self.assertEqual([len(row) for row in blank.splitlines()], [6, 6, 6])
        self.assertEqual([len(row) for row in pulse.splitlines()], [6, 6, 6])
        self.assertEqual([len(row) for row in wide_pulse.splitlines()], [48, 48, 48])
        self.assertIn("|", pulse)
        self.assertIn("/", pulse)
        self.assertIn("\\", pulse)

    def test_cardiac_monitor_intensity_tracks_agent_state(self) -> None:
        stopped = cardiac_monitor_intensity("WORKING", stopped=True)
        thinking = cardiac_monitor_intensity("THINKING")
        working = cardiac_monitor_intensity("USING TOOL")

        self.assertEqual((stopped.pulse_height, stopped.tick_stride), (0, 0))
        self.assertLess(thinking.pulse_height, working.pulse_height)
        self.assertLess(thinking.tick_stride / thinking.tick_divisor, working.tick_stride / working.tick_divisor)
        self.assertNotIn("|", cardiac_monitor_frame(0, 48, pulse_height=stopped.pulse_height))

    def test_runtime_snapshot_tracks_current_activity(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            coordinator = WakeCoordinator(temp, llm_client=WakeFakeLLM())
            coordinator._event_listener({"event": "command_started", "command": "printf hello"})
            snapshot = coordinator.runtime_snapshot()
            self.assertEqual(snapshot["current_activity"], "$ printf hello")
            self.assertEqual(snapshot["activity"][-1], "$ printf hello")

    def test_stop_suppresses_late_chat_summaries(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            coordinator = WakeCoordinator(temp, llm_client=WakeFakeLLM())
            messages: list[tuple[str, str]] = []
            coordinator.on_chat = lambda message, kind: messages.append((message, kind))
            coordinator.stop_requested = True
            coordinator._event_listener({"event": "cycle_completed", "cycle": 1, "report": "retrying test"})
            coordinator._event_listener({"event": "session_summary", "message": "session complete"})
            self.assertEqual(messages, [])

    def test_recovery_removes_stale_daily_budget_plan_item(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            coordinator = WakeCoordinator(temp, llm_client=WakeFakeLLM())
            coordinator.plan = [{
                "priority": 1,
                "status": "todo",
                "step": "Obtain a decision from the human on increasing the token budget for the next run.",
                "why": "The old budget blocker is unresolved.",
            }]
            coordinator._recover_budget_blocked_plan()
            self.assertNotIn("token budget", coordinator.plan[0]["step"].lower())

    def test_boot_prunes_stale_plan_before_the_ui_can_render_it(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state = root / "state"
            state.mkdir(parents=True)
            (state / "handoff.json").write_text(json.dumps({
                "plan": [{
                    "priority": 1,
                    "status": "todo",
                    "step": "Obtain a decision from the human on increasing the token budget for the next run.",
                    "why": "Old per-run blocker.",
                }],
            }), encoding="utf-8")
            coordinator = WakeCoordinator(root, llm_client=WakeFakeLLM())
            coordinator.boot()
            self.assertNotIn("token budget", coordinator.plan[0]["step"].lower())

    def test_plan_panel_filters_completed_items(self) -> None:
        visible = visible_plan_items([
            {"step": "Finished inspection", "status": "completed"},
            {"step": "Continue mapping", "status": "todo"},
            {"step": "Achieved check", "status": "achieved"},
        ])
        self.assertEqual([item["step"] for item in visible], ["Continue mapping"])

    def test_normalized_plan_drops_completed_items_from_durable_state(self) -> None:
        normalized = normalized_plan([
            {"step": "Finished inspection", "status": "completed"},
            {"step": "Continue mapping", "status": "todo"},
        ])
        self.assertEqual([item["step"] for item in normalized], ["Continue mapping"])

    def test_plan_height_clamp_preserves_space_for_the_activity_panel(self) -> None:
        self.assertEqual(clamped_plan_height(1, 40), 5)
        self.assertEqual(clamped_plan_height(99, 40), 34)
        self.assertEqual(clamped_plan_height(16, 40), 16)

    def test_inbox_is_persistent_and_consumed_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logger = EventLogger(root / "logs" / "actions.jsonl")
            inbox = HumanInbox(root, logger)
            inbox.add("prioritize disk inspection")
            self.assertEqual(inbox.consume(), ["prioritize disk inspection"])
            self.assertEqual(inbox.consume(), [])

    def test_corrupt_handoff_falls_back_to_last_good(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logger = EventLogger(root / "logs" / "actions.jsonl")
            store = SessionStore(root, logger)
            info = store.start()
            handoff = {"summary": "last good", "discoveries": [], "tools_created": [], "failures_and_lessons": [], "open_questions": [], "plan": [], "pending_human_requests": [], "mood_of_run": "exploring"}
            store.checkpoint(info["session_id"], handoff, 1, 2)
            store.handoff.write_text("{not json", encoding="utf-8")
            loaded, recovered = store.load_handoff()
            self.assertTrue(recovered)
            self.assertEqual(loaded["summary"], "last good")

    def test_unfinished_active_session_is_recorded_as_crash(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logger = EventLogger(root / "logs" / "actions.jsonl")
            store = SessionStore(root, logger)
            first = store.start()
            store.checkpoint(first["session_id"], {"summary": "checkpoint", "discoveries": [], "tools_created": [], "failures_and_lessons": [], "open_questions": [], "plan": [], "pending_human_requests": [], "mood_of_run": "exploring"}, 4, 20)
            second = store.start()
            rows = [json.loads(line) for line in store.sessions.read_text().splitlines()]
            self.assertTrue(second["crash"])
            self.assertEqual(rows[-1]["end_reason"], "crash")

    def test_oversize_handoff_is_bounded_with_explicit_overflow(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logger = EventLogger(root / "logs" / "actions.jsonl")
            store = SessionStore(root, logger, handoff_cap=2_000)
            data = {"summary": "x" * 4_000, "long_term_summary": "y" * 4_000, "discoveries": ["z" * 1_000] * 10, "tools_created": [], "failures_and_lessons": ["q" * 1_000] * 10, "open_questions": [], "plan": [], "pending_human_requests": [], "mood_of_run": "exploring"}
            bounded = store._bounded_handoff(data)
            self.assertLessEqual(len(json.dumps(bounded).encode("utf-8")), 2_000)
            self.assertTrue(bounded["compression_pending"])
            self.assertTrue((root / "state" / "handoff_overflow.json").exists())

    def test_headless_wake_writes_handoff_journal_and_session(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fake = WakeFakeLLM()
            coordinator = WakeCoordinator(root, max_iterations=1, token_budget=10_000, llm_client=fake)
            summary = coordinator.run()
            self.assertEqual(summary.iterations, 1)
            handoff = json.loads((root / "state" / "handoff.json").read_text())
            self.assertIn("verified the saved state", handoff["summary"])
            self.assertIn("session", (root / "state" / "journal.md").read_text())
            row = json.loads((root / "state" / "sessions.jsonl").read_text().splitlines()[-1])
            self.assertEqual(row["end_reason"], "clean_shutdown")
            self.assertGreaterEqual(fake.calls, 3)  # wake reflection, actor, shutdown reflection

    def test_later_wake_uses_human_name_and_stored_voice(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first = WakeCoordinator(root, max_iterations=1, token_budget=10_000, llm_client=WakeFakeLLM())
            first.run()
            identity = IdentityStore(root, EventLogger(root / "logs" / "actions.jsonl"))
            identity.set_name("Atlas", "human-name")

            second = WakeCoordinator(root, max_iterations=1, token_budget=10_000, llm_client=WakeFakeLLM())
            second.run()
            narrations = [
                json.loads(line).get("message", "")
                for line in (root / "logs" / "actions.jsonl").read_text(encoding="utf-8").splitlines()
                if json.loads(line).get("event") == "narration"
            ]
            self.assertTrue(any("Atlas is awake" in message for message in narrations))
            self.assertTrue(any("I speak plainly about what I observed" in message for message in narrations))

    def test_name_context_is_included_in_read_only_conversation_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            coordinator = WakeCoordinator(root, llm_client=WakeFakeLLM())
            coordinator.identity.set_name("Atlas", "session-a")
            self.assertIn("mapping", coordinator.conversation_context())
            self.assertIn("soft cultural/style cue", coordinator.conversation_context())


if __name__ == "__main__":
    unittest.main()
