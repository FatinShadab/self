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
from agent.ui.wake import build_archive_views, cardiac_monitor_frame, cardiac_monitor_intensity, escape_rich_markup, format_conversation_history_view, WakeCoordinator, clamped_plan_height, format_goals_panel, format_starting_plan, normalized_plan, visible_plan_items


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

    def test_format_goals_panel_displays_achieved_and_added_goals_dynamically(self) -> None:
        goals = [
            {"goal": "Inspect current state and verify environment facts", "status": "done", "created_cycle": 1, "updated_cycle": 1},
            {"goal": "Develop reusable tool summarize_map", "status": "in_progress", "created_cycle": 1, "updated_cycle": 2, "priority": 2},
            {"goal": "Critical bug fix", "status": "todo", "created_cycle": 1, "priority": 1},
            {"goal": "Test summarize_map with live data", "status": "todo", "created_cycle": 2, "priority": 3},
        ]
        panel = format_goals_panel(goals, current_activity="tool: ask_model", current_cycle=2)
        self.assertIn("[b]Goals[/b]", panel)
        # Achieved goal must be removed from the main panel
        self.assertNotIn("Inspect current state and verify environment facts", panel)
        # Currently working goal must be on top
        self.assertIn("[cyan]▶ (in progress)[/cyan] Develop reusable tool summarize_map", panel)
        # Priority 1 must be rendered
        self.assertIn("[red]! (p1)[/red] Critical bug fix", panel)
        # In-progress appears before Priority 1
        pos_working = panel.find("Develop reusable tool summarize_map")
        pos_p1 = panel.find("Critical bug fix")
        self.assertLess(pos_working, pos_p1)
        # Priority 1 appears before Priority 3
        pos_p3 = panel.find("Test summarize_map with live data")
        self.assertLess(pos_p1, pos_p3)
        # Now must be removed from the panel
        self.assertNotIn("Now", panel)
        self.assertNotIn("tool: ask_model", panel)

    def test_format_goals_panel_handles_empty_and_caps_long_lists(self) -> None:
        empty_panel = format_goals_panel([])
        self.assertIn("No goals recorded yet", empty_panel)

        all_achieved_panel = format_goals_panel([{"goal": "Task 1", "status": "done"}])
        self.assertIn("All recorded goals achieved", all_achieved_panel)

        many_goals = [
            {"goal": f"Active task {i}", "status": "todo", "priority": 2, "created_cycle": i} for i in range(1, 9)
        ]
        capped_panel = format_goals_panel(many_goals, current_cycle=10)
        # Max 5 unfinished goals shown
        self.assertIn("Active task 1", capped_panel)
        self.assertIn("Active task 5", capped_panel)
        self.assertNotIn("Active task 6", capped_panel)
        self.assertIn("(+3 more pending)", capped_panel)

    def test_build_archive_views_renders_two_columns(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            coordinator = WakeCoordinator(root, llm_client=WakeFakeLLM(), max_iterations=0)
            coordinator.boot()

            # Record an achieved goal in plan_store
            coordinator.plan_store.items = [
                {"id": "goal-1", "goal": "Inventory installed packages", "status": "done", "priority": 1, "why": "grounding", "evidence": "dpkg list", "updated_cycle": 2},
                {"id": "goal-2", "goal": "Explore filesystem", "status": "in_progress", "priority": 2},
            ]
            coordinator.plan_store._save_atomic(diff="update", reason="test")

            # Write a completed session to sessions.jsonl and journal.md
            state_dir = root / "state"
            state_dir.mkdir(parents=True, exist_ok=True)
            sessions_file = state_dir / "sessions.jsonl"
            sessions_file.write_text(json.dumps({
                "session_id": "sess-prev-001",
                "start_time": "2026-10-17T10:00:00Z",
                "end_time": "2026-10-17T10:15:00Z",
                "end_reason": "max_iterations",
                "iteration_count": 5,
                "token_spend": 120,
            }) + "\n", encoding="utf-8")

            journal_file = state_dir / "journal.md"
            journal_file.write_text(
                "## 2026-10-17T10:15:00Z — session sess-prev-001\n\n"
                "Completed initial exploration safely.\n\n"
                "### Next plan\n"
                "- [1] Verify python packages\n"
                "- [2] Explore network connectivity\n\n"
                "End reason: max_iterations\n",
                encoding="utf-8",
            )

            plans_markup, goals_markup = build_archive_views(root, coordinator)

            # Column 1 assertions (Session plans)
            self.assertIn("Session Plans", plans_markup)
            self.assertIn(coordinator.status.session_id, plans_markup)
            self.assertIn("sess-prev-001", plans_markup)
            self.assertIn("Verify python packages", plans_markup)
            self.assertIn("max_iterations", plans_markup)

            # Column 2 assertions (Achieved goals)
            self.assertIn("Achieved Goals", goals_markup)
            self.assertIn("Inventory installed packages", goals_markup)
            self.assertIn("Total Achieved: 1", goals_markup)
            self.assertIn("Evidence: dpkg list", goals_markup)
            # In-progress goal should not be in achieved goals column
            self.assertNotIn("Explore filesystem", goals_markup)

    def test_format_conversation_history_view_pagination_and_empty(self) -> None:
        empty = format_conversation_history_view([])
        self.assertIn("No recorded conversation messages yet", empty)
        self.assertIn("/back", empty)

        # Create 45 messages (simulating ongoing conversation)
        messages = [
            {
                "timestamp": f"2026-10-17T12:{i:02d}:00Z",
                "role": "human" if i % 2 == 1 else "agent",
                "message": f"Message number {i}",
                "kind": "chat" if i % 2 == 1 else "response",
            }
            for i in range(1, 46)
        ]

        # Page 0 (default: latest 20 messages)
        p0 = format_conversation_history_view(messages, page=0, page_size=20, entity_name="SELF")
        self.assertIn("Showing messages 26–45 of 45  (Page 1 of 3)", p0)
        self.assertIn("Message number 26", p0)
        self.assertIn("Message number 45", p0)
        self.assertNotIn("Message number 25", p0)
        self.assertIn("/previous", p0)

        # Page 1 (older 20 messages)
        p1 = format_conversation_history_view(messages, page=1, page_size=20, entity_name="SELF")
        self.assertIn("Showing messages 6–25 of 45  (Page 2 of 3)", p1)
        self.assertIn("Message number 6", p1)
        self.assertIn("Message number 25", p1)
        self.assertNotIn("Message number 5", p1)
        self.assertNotIn("Message number 26", p1)

        # Page 2 (oldest remaining messages)
        p2 = format_conversation_history_view(messages, page=2, page_size=20, entity_name="SELF")
        self.assertIn("Showing messages 1–5 of 45  (Page 3 of 3)", p2)
        self.assertIn("Message number 1", p2)
        self.assertIn("Message number 5", p2)
        self.assertIn("Oldest recorded messages", p2)
        self.assertNotIn("Message number 6", p2)

        # Bad page clamp test
        p_clamped = format_conversation_history_view(messages, page=99, page_size=20)
        self.assertIn("Page 3 of 3", p_clamped)

    def test_conversation_history_file_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            history_file = root / "state" / "conversation_history.jsonl"
            history_file.parent.mkdir(parents=True, exist_ok=True)
            for i in range(1, 26):
                with history_file.open("a", encoding="utf-8") as f:
                    f.write(json.dumps({
                        "timestamp": "2026-10-17T12:00:00Z",
                        "role": "human" if i % 2 == 1 else "agent",
                        "message": f"Historical line {i}",
                        "kind": "chat",
                    }) + "\n")
            lines = [json.loads(line) for line in history_file.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(lines), 25)
            # The latest 20 messages for the main UI:
            recent_20 = lines[-20:]
            self.assertEqual(len(recent_20), 20)
            self.assertEqual(recent_20[0]["message"], "Historical line 6")
            self.assertEqual(recent_20[-1]["message"], "Historical line 25")

    def test_format_starting_plan_renders_session_plan(self) -> None:
        empty = format_starting_plan([])
        self.assertIn("No starting plan recorded", empty)

        plan = [
            {"goal": "Inspect current state and verify environment facts", "status": "todo", "why": "Initial model grounding"},
            {"goal": "Develop reusable tool summarize_map", "status": "todo", "why": "Facilitate inspection"},
        ]
        rendered = format_starting_plan(plan, session_id="session-xyz-123456")
        self.assertIn("Starting Plan", rendered)
        self.assertIn("session-xyz-", rendered)
        self.assertIn("1. (todo) Inspect current state and verify environment facts", rendered)
        self.assertIn("*Why:* Initial model grounding", rendered)
        self.assertIn("2. (todo) Develop reusable tool summarize_map", rendered)

    def test_coordinator_render_starting_plan_and_session_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            coordinator = WakeCoordinator(root, llm_client=WakeFakeLLM(), max_iterations=0)
            coordinator.boot()
            rendered1 = coordinator.render_starting_plan()
            self.assertIn("Starting Plan", rendered1)
            self.assertIn(coordinator.status.session_id[:12], rendered1)
            session_id1 = coordinator.status.session_id

            # End session and start a new session
            coordinator.run()
            # On next boot/run, starting_plan refreshes to the new session
            coordinator.run()
            self.assertNotEqual(coordinator.status.session_id, session_id1)
            rendered2 = coordinator.render_starting_plan()
            self.assertIn(coordinator.status.session_id[:12], rendered2)

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

    def test_handoff_summary_does_not_multiply_session_complete_headers(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            # Run session 1
            first = WakeCoordinator(root, max_iterations=1, token_budget=10_000, llm_client=WakeFakeLLM())
            first.run()

            # Run session 2 with failing LLM so it uses fallback reflection
            class FailingLLM:
                def call(self, **kwargs: Any) -> LLMResult:
                    raise RuntimeError("provider unavailable")

            second = WakeCoordinator(root, max_iterations=1, token_budget=10_000, llm_client=FailingLLM())
            second.run()

            handoff_path = root / "state" / "handoff.json"
            self.assertTrue(handoff_path.exists())
            handoff_text = handoff_path.read_text(encoding="utf-8")
            count = handoff_text.count("Session complete after")
            self.assertLessEqual(count, 1, f"Repeated 'Session complete after' count: {count}")


if __name__ == "__main__":
    unittest.main()
