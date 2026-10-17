"""SELF test plan module."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from agent.infra.event_log import EventLogger
from agent.learning.plan import (
    PlanStore,
    SEED_STANDING_GOAL,
    consolidate_plan_items,
    visible_plan_items,
)
from agent.llm.llm import LLMResult
from agent.runtime.loop import AgentConfig, AgentLoop, STANDING_GOAL, SYSTEM_PROMPT
from agent.tools.base_tools import ToolRunner
from agent.ui.wake import WakeCoordinator


class ScriptedLLM:
    """Mock LLM returning sequential predetermined LLMResult responses."""

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = list(responses)
        self.call_count = 0
        self.received_messages: list[list[dict[str, Any]]] = []
        self.tokens_used = 0

    def call(self, **kwargs: Any) -> LLMResult:
        self.call_count += 1
        messages = kwargs.get("messages", [])
        self.received_messages.append(messages)
        if not self.responses:
            return LLMResult(
                content=[{"type": "text", "text": "No more responses configured."}],
                input_tokens=10,
                output_tokens=5,
                stop_reason="end_turn",
                model="mock-scripted",
            )
        resp = self.responses.pop(0)
        content: list[dict[str, Any]] = []
        if "text" in resp:
            content.append({"type": "text", "text": resp["text"]})
        if "tool_calls" in resp:
            for tc in resp["tool_calls"]:
                content.append({
                    "type": "tool_use",
                    "id": tc.get("id", f"call_{self.call_count}"),
                    "name": tc["name"],
                    "input": tc.get("arguments", {}),
                })
        self.tokens_used += 15
        return LLMResult(
            content=content,
            input_tokens=10,
            output_tokens=5,
            stop_reason="tool_use" if "tool_calls" in resp else "end_turn",
            model="mock-scripted",
        )


class PlanTests(unittest.TestCase):
    def test_plan_changes_after_a_cycle(self) -> None:
        """Requirement 7.1: Verify plan changes after a cycle via update_plan tool call."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logger = EventLogger(root / "logs" / "actions.jsonl")
            runner = ToolRunner(logger, root)

            # Round 1: agent reviews plan and calls update_plan
            # Round 2: agent finishes cycle with a textual report
            mock_llm = ScriptedLLM([
                {
                    "text": "I am reviewing the plan and adding a new goal based on startup observations.",
                    "tool_calls": [
                        {
                            "id": "tc1",
                            "name": "update_plan",
                            "arguments": {
                                "action": "add",
                                "goal": "Inventory installed tools",
                                "step": "Run which python and inspect binaries",
                                "priority": 1,
                                "reason": "Need verified tool paths before expanding exploration",
                                "evidence": "Initial environment inspection",
                            },
                        }
                    ],
                },
                {
                    "text": "Added tool inventory goal and completed cycle 1.",
                },
            ])

            config = AgentConfig(
                workspace=root,
                max_iterations=1,
                retrieve_memories=False,
            )
            loop = AgentLoop(config, logger, mock_llm, runner)
            summary = loop.run()

            self.assertEqual(summary.iterations, 1)
            self.assertEqual(loop.plan_store.plan_version, 2)

            # Check persistent state under state/plan.json
            plan_data = json.loads((root / "state" / "plan.json").read_text(encoding="utf-8"))
            self.assertEqual(plan_data["plan_version"], 2)
            goals = [item["goal"] for item in plan_data["items"]]
            self.assertIn("Inventory installed tools", goals)

            # Check actions.jsonl event log for plan_updated
            log_lines = (root / "logs" / "actions.jsonl").read_text(encoding="utf-8").splitlines()
            events = [json.loads(line) for line in log_lines]
            updated_events = [e for e in events if e.get("event") == "plan_updated"]
            self.assertTrue(len(updated_events) >= 1)
            event = updated_events[-1]
            self.assertEqual(event["cycle"], 1)
            self.assertEqual(event["plan_version"], 2)
            self.assertIn("Added goal-2", event["diff"])
            self.assertEqual(event["reason"], "Need verified tool paths before expanding exploration")
            self.assertEqual(event["evidence"], "Initial environment inspection")

    def test_surprise_observation_changes_the_plan(self) -> None:
        """Requirement 7.2: Verify a surprise observation leads the agent to update the plan."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logger = EventLogger(root / "logs" / "actions.jsonl")
            runner = ToolRunner(logger, root)

            # Round 1: agent tries run_shell with non-existent command (returns error)
            # Round 2: agent receives surprise error and updates plan citing the error
            # Round 3: agent concludes cycle
            mock_llm = ScriptedLLM([
                {
                    "text": "Attempting to query package manager.",
                    "tool_calls": [
                        {
                            "id": "tc1",
                            "name": "run_shell",
                            "arguments": {"command": "apt-get --version"},
                        }
                    ],
                },
                {
                    "text": "The tool failed because apt-get is absent. Updating the plan.",
                    "tool_calls": [
                        {
                            "id": "tc2",
                            "name": "update_plan",
                            "arguments": {
                                "action": "edit",
                                "id": "goal-1",
                                "status": "blocked",
                                "reason": "apt-get command failed with exit 127",
                                "evidence": "apt-get: not found",
                                "next_steps": "Query pip directly instead of apt",
                            },
                        }
                    ],
                },
                {
                    "text": "Plan successfully updated to use pip. Concluding cycle.",
                },
            ])

            config = AgentConfig(
                workspace=root,
                max_iterations=1,
                retrieve_memories=False,
            )
            loop = AgentLoop(config, logger, mock_llm, runner)
            summary = loop.run()

            self.assertEqual(summary.iterations, 1)

            # Verify plan item was updated with blocked status and new next_steps
            item = loop.plan_store.items[0]
            self.assertEqual(item["status"], "blocked")
            self.assertEqual(item["next_steps"], "Query pip directly instead of apt")
            self.assertEqual(item["evidence"], "apt-get: not found")

            # Verify plan_updated was logged with evidence citing the surprise observation
            log_lines = (root / "logs" / "actions.jsonl").read_text(encoding="utf-8").splitlines()
            events = [json.loads(line) for line in log_lines]
            updated_events = [e for e in events if e.get("event") == "plan_updated"]
            self.assertTrue(len(updated_events) >= 1)
            event = updated_events[-1]
            self.assertEqual(event["evidence"], "apt-get: not found")
            self.assertIn("apt-get command failed", event["reason"])

    def test_unchanged_plans_are_logged_with_a_reason(self) -> None:
        """Requirement 7.3: Verify unchanged plans are logged as plan_unchanged with a reason."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logger = EventLogger(root / "logs" / "actions.jsonl")
            runner = ToolRunner(logger, root)

            # Agent reviews plan and decides no updates are needed
            mock_llm = ScriptedLLM([
                {
                    "text": "Reviewed current plan. Current goals remain accurate; no change needed.",
                }
            ])

            config = AgentConfig(
                workspace=root,
                max_iterations=1,
                retrieve_memories=False,
            )
            loop = AgentLoop(config, logger, mock_llm, runner)
            summary = loop.run()

            self.assertEqual(summary.iterations, 1)

            log_lines = (root / "logs" / "actions.jsonl").read_text(encoding="utf-8").splitlines()
            events = [json.loads(line) for line in log_lines]
            unchanged_events = [e for e in events if e.get("event") == "plan_unchanged"]
            self.assertEqual(len(unchanged_events), 1)
            event = unchanged_events[0]
            self.assertEqual(event["cycle"], 1)
            self.assertEqual(event["diff"], "")
            self.assertTrue(bool(event["reason"]))
            self.assertIn("no change needed", event["reason"].lower())
            self.assertEqual(event.get("source"), "harness_auto")

    def test_zero_cycle_sessions_preserve_the_plan(self) -> None:
        """Requirement 7.4: Zero-cycle sessions preserve handoff and plan without shutdown reflection."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state_dir = root / "state"
            state_dir.mkdir(parents=True)

            original_plan = [
                {
                    "id": "goal-keep",
                    "goal": "Verify system architecture and cpu details",
                    "step": "Verify system architecture and cpu details",
                    "status": "todo",
                    "priority": 1,
                    "why": "System discovery",
                    "evidence": "Previous verification",
                    "next_steps": "cat /proc/cpuinfo",
                }
            ]
            initial_handoff = {
                "summary": "Previous run completed successfully with verified system facts.",
                "long_term_summary": "Stable hardware survey",
                "discoveries": ["cpu: 8 cores"],
                "tools_created": [],
                "failures_and_lessons": [],
                "open_questions": [],
                "plan": original_plan,
                "pending_human_requests": [],
                "mood_of_run": "progressing",
            }
            (state_dir / "handoff.json").write_text(json.dumps(initial_handoff), encoding="utf-8")
            (state_dir / "plan.json").write_text(
                json.dumps({
                    "schema_version": 1,
                    "plan_version": 4,
                    "updated_at": "2026-10-17T00:00:00Z",
                    "cycle": 4,
                    "last_diff": "Initial setup",
                    "last_reason": "Seeded",
                    "items": original_plan,
                }),
                encoding="utf-8",
            )

            mock_llm = ScriptedLLM([])
            coordinator = WakeCoordinator(root, llm_client=mock_llm, max_iterations=0)
            coordinator.boot()

            # Execute run_session with max_iterations=0
            summary = coordinator._run_session()
            self.assertEqual(summary.iterations, 0)

            # Verify no reflection was invoked
            self.assertEqual(mock_llm.call_count, 0)

            # Check that zero_cycle_session_preserved event was logged
            log_lines = (root / "logs" / "actions.jsonl").read_text(encoding="utf-8").splitlines()
            events = [json.loads(line) for line in log_lines]
            preserved_events = [e for e in events if e.get("event") == "zero_cycle_session_preserved"]
            self.assertEqual(len(preserved_events), 1)

            # Check that handoff was carried forward unchanged
            current_handoff = coordinator.handoff
            self.assertEqual(current_handoff["summary"], initial_handoff["summary"])
            self.assertNotIn("Session complete after 0 cycle(s)", current_handoff["summary"])
            self.assertEqual(current_handoff["plan"][0]["id"], "goal-keep")
            self.assertEqual(current_handoff["plan"][0]["goal"], "Verify system architecture and cpu details")

            # Check that plan.json was preserved
            saved_plan = json.loads((state_dir / "plan.json").read_text(encoding="utf-8"))
            self.assertEqual(saved_plan["plan_version"], 4)
            self.assertEqual(saved_plan["items"][0]["id"], "goal-keep")

    def test_plan_drives_the_first_action_of_the_next_cycle(self) -> None:
        """Requirement 7.5: The top item in the plan drives the prompt, retrieval, and first action."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logger = EventLogger(root / "logs" / "actions.jsonl")
            runner = ToolRunner(logger, root)

            # Initialize plan with a distinctive top goal
            plan_store = PlanStore(root, logger)
            plan_store.initialize()
            plan_store.update_plan(
                action="add",
                goal="Inspect network routing table",
                step="ip route show",
                next_steps="ip route show",
                priority=1,
                reason="Top priority exploration step",
                evidence="User task setup",
                cycle=1,
            )
            runner.plan_store = plan_store

            # Check top_items and retrieval_query
            top = plan_store.top_items(limit=1)
            self.assertEqual(len(top), 1)
            self.assertEqual(top[0]["goal"], "Inspect network routing table")
            query = plan_store.retrieval_query()
            self.assertIn("Inspect network routing table", query)
            self.assertIn("ip route show", query)

            mock_llm = ScriptedLLM([
                {
                    "text": "Acting on the top plan item: Inspect network routing table.",
                    "tool_calls": [
                        {
                            "id": "tc1",
                            "name": "run_shell",
                            "arguments": {"command": "ip route show"},
                        }
                    ],
                },
                {
                    "text": "Network route inspected; completed cycle.",
                },
            ])

            config = AgentConfig(
                workspace=root,
                max_iterations=1,
                retrieve_memories=False,
            )
            loop = AgentLoop(config, logger, mock_llm, runner)
            summary = loop.run()

            self.assertEqual(summary.iterations, 1)

            # Verify prompt delivered to LLM contained the top plan item
            self.assertTrue(len(mock_llm.received_messages) >= 1)
            first_cycle_prompt = mock_llm.received_messages[0][0]["content"]
            self.assertIn("Inspect network routing table", first_cycle_prompt)
            self.assertIn("ip route show", first_cycle_prompt)

            # Verify first tool action executed was the action from the top plan item
            log_lines = (root / "logs" / "actions.jsonl").read_text(encoding="utf-8").splitlines()
            events = [json.loads(line) for line in log_lines]
            cycle_completed = next(e for e in events if e.get("event") == "cycle_completed")
            first_action = cycle_completed["actions"][0]
            self.assertEqual(first_action["name"], "run_shell")

    def test_plan_hygiene_stale_items_and_consolidation(self) -> None:
        """Requirement 5: Test plan hygiene marking stale items and consolidating over max_items."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logger = EventLogger(root / "logs" / "actions.jsonl")
            store = PlanStore(root, logger, max_items=5)
            store.initialize(seed_task="Primary objective")

            # Item created at cycle 1
            item = store.items[0]
            self.assertEqual(item["status"], "todo")

            # At cycle 7, item hasn't been updated in 6 cycles (> max_stale_cycles=5)
            hygiene_actions = store.hygiene(cycle=7, max_stale_cycles=5)
            self.assertEqual(store.items[0]["status"], "stale")
            self.assertTrue(any("Marked stale" in a for a in hygiene_actions))

            # Add multiple goals to exceed max_items (5)
            for i in range(2, 8):
                store.update_plan(
                    action="add",
                    goal=f"Additional goal {i}",
                    priority=2,
                    reason=f"Expanding scope {i}",
                    cycle=7,
                )

            # Verify plan size is capped by consolidation, never exceeding max_items
            self.assertLessEqual(len(store.items), 5)
            # Verify consolidation item was created rather than dropping goals silently
            item_ids = [it.get("id") for it in store.items]
            has_consolidated = any("consolidated" in str(id_) for id_ in item_ids)
            self.assertTrue(has_consolidated)

    def test_standing_goal_removed_from_prompt_and_seeded_in_plan(self) -> None:
        """Requirement A: SYSTEM_PROMPT lacks 'Standing goal:' and states goals live in plan; plan is seeded."""
        # 1. Check SYSTEM_PROMPT wording
        self.assertNotIn("Standing goal:", SYSTEM_PROMPT)
        self.assertIn("Your goals live in your plan.", SYSTEM_PROMPT)

        # 2. First boot writes standing-goal text as seed item in plan.json
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logger = EventLogger(root / "logs" / "actions.jsonl")
            store = PlanStore(root, logger)
            store.initialize()  # first boot: plan.json does not exist
            self.assertTrue((root / "state" / "plan.json").exists())
            self.assertEqual(len(store.items), 1)
            self.assertEqual(store.items[0]["id"], "goal-1")
            self.assertEqual(store.items[0]["goal"], SEED_STANDING_GOAL)
            self.assertIn("Explore your environment", store.items[0]["goal"])

            # 3. Subsequent boot does not overwrite existing plan
            store.update_plan(action="edit", id="goal-1", goal="Customized goal", reason="Updated by agent")
            store2 = PlanStore(root, logger)
            store2.initialize()
            self.assertEqual(store2.items[0]["goal"], "Customized goal")

    def test_plan_archive_purged_goals_and_read_plan_history(self) -> None:
        """Requirement B: Done/dropped goals are archived to plan_archive.jsonl and read_plan returns history."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logger = EventLogger(root / "logs" / "actions.jsonl")
            runner = ToolRunner(logger, root)
            store = PlanStore(root, logger)
            runner.plan_store = store
            store.initialize()

            # Add two goals, mark one done and one dropped
            store.update_plan(action="add", goal="Goal to complete", reason="testing done", cycle=1)
            store.update_plan(action="add", goal="Goal to drop", reason="testing drop", cycle=1)
            store.update_plan(action="mark_done", id="goal-2", reason="Finished work", evidence="file verified", cycle=2)
            store.update_plan(action="drop", id="goal-3", reason="No longer needed", evidence="irrelevant", cycle=2)

            # Hygiene should purge them to state/plan_archive.jsonl
            actions = store.hygiene(cycle=2)
            self.assertTrue(any("Archived and purged" in a for a in actions))
            archive_file = root / "state" / "plan_archive.jsonl"
            self.assertTrue(archive_file.exists())

            # Read archived records and verify schema
            archive_lines = [json.loads(l) for l in archive_file.read_text(encoding="utf-8").splitlines() if l.strip()]
            self.assertEqual(len(archive_lines), 2)
            for rec in archive_lines:
                for req_key in ("goal", "outcome", "reason", "evidence", "cycle", "timestamp"):
                    self.assertIn(req_key, rec)
            self.assertEqual(archive_lines[0]["goal"], "Goal to complete")
            self.assertEqual(archive_lines[0]["outcome"], "done")
            self.assertEqual(archive_lines[1]["goal"], "Goal to drop")
            self.assertEqual(archive_lines[1]["outcome"], "dropped")

            # Check prompt_summary shows recently archived goals
            summary = store.prompt_summary()
            self.assertIn("Recently archived goals:", summary)
            self.assertIn("Goal to complete", summary)
            self.assertIn("Goal to drop", summary)

            # Check read_plan default does not return history
            res_default = runner.execute("read_plan", {})
            self.assertNotIn("history", res_default)

            # Check read_plan with include_history=True returns history
            res_history = runner.execute("read_plan", {"include_history": True})
            self.assertIn("history", res_history)
            self.assertEqual(len(res_history["history"]), 2)
            self.assertEqual(res_history["history"][0]["goal"], "Goal to complete")

    def test_honest_review_accounting_and_sources(self) -> None:
        """Requirement C: plan_unchanged source distinction ('agent' vs 'harness_auto')."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logger = EventLogger(root / "logs" / "actions.jsonl")
            store = PlanStore(root, logger)
            store.initialize()

            # Agent calls unchanged
            store.update_plan(action="unchanged", reason="Agent confirmed plan is valid", cycle=2)

            # Harness records unchanged
            store.record_unchanged(cycle=3, reason="Harness fallback review")

            events = [json.loads(l) for l in (root / "logs" / "actions.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
            unchanged = [e for e in events if e.get("event") == "plan_unchanged"]
            self.assertEqual(len(unchanged), 2)
            self.assertEqual(unchanged[0]["source"], "agent")
            self.assertEqual(unchanged[0]["cycle"], 2)
            self.assertEqual(unchanged[1]["source"], "harness_auto")
            self.assertEqual(unchanged[1]["cycle"], 3)


if __name__ == "__main__":
    unittest.main()
