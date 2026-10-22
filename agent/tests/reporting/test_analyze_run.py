"""Unit tests for run log analysis script (scripts/analyze_run.py)."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from agent.reporting.run_analysis import analyze_run


class AnalyzeRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp())
        self.workspace = self.temp_dir / "workspace"
        self.workspace.mkdir(parents=True)
        self.state_dir = self.workspace / "state"
        self.state_dir.mkdir(parents=True)
        self.logs_dir = self.workspace / "logs"
        self.logs_dir.mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_analyze_run_clean_30_cycle_events(self) -> None:
        # Create 30 cycles of events
        actions_file = self.logs_dir / "actions.jsonl"
        lines = []

        for c in range(1, 31):
            # Tokens
            lines.append(json.dumps({
                "event": "llm_call_completed",
                "cycle": c,
                "input_tokens": 500,
                "output_tokens": 200,
                "total_tokens": 700,
            }))
            # Plan activity: alternate updated and unchanged
            if c % 3 == 0:
                lines.append(json.dumps({
                    "event": "plan_updated",
                    "cycle": c,
                    "diff": f"Updated goal in cycle {c}",
                    "reason": "Observations warranted goal change",
                }))
            elif c % 3 == 1:
                lines.append(json.dumps({
                    "event": "plan_unchanged",
                    "cycle": c,
                    "source": "agent",
                    "reason": "Goals remain valid",
                }))
            else:
                lines.append(json.dumps({
                    "event": "plan_unchanged",
                    "cycle": c,
                    "source": "harness_auto",
                    "reason": "Agent omitted review",
                }))

            # Cycle completion
            lines.append(json.dumps({
                "event": "cycle_completed",
                "cycle": c,
                "actions": [{"name": "read_plan"}, {"name": "run_shell"}],
            }))

        # Add human input decision events
        lines.append(json.dumps({"event": "human_input_decision", "cycle": 5, "decision": "accepted", "input": "Check disk"}))
        lines.append(json.dumps({"event": "human_input_decision", "cycle": 12, "decision": "declined", "input": "Format drive"}))
        lines.append(json.dumps({"event": "human_input_decision", "cycle": 20, "decision": "modified", "input": "Install tool"}))

        # Add some failures
        lines.append(json.dumps({"event": "llm_call_failed", "cycle": 8, "error_type": "HTTP 429", "error": "Rate limit"}))
        lines.append(json.dumps({"event": "tool_failed", "cycle": 15, "tool": "run_shell", "error": "Command not found"}))
        lines.append(json.dumps({"event": "action_denied", "cycle": 22, "action": "pet_companion.release_pet", "level": "L2"}))

        # Add plugin events
        lines.append(json.dumps({"event": "plugin_enabled", "cycle": 1, "plugin": "pet_companion"}))
        lines.append(json.dumps({"event": "plugin_pet_fed", "cycle": 2}))

        actions_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

        # Create handoff.json
        handoff_file = self.state_dir / "handoff.json"
        handoff_file.write_text(json.dumps({
            "summary": "Session complete after cycle 30.",
            "plan": ["Goal 1", "Goal 2"],
        }), encoding="utf-8")

        # Create daily_token_budget.json
        (self.state_dir / "daily_token_budget.json").write_text(json.dumps({
            "date": "2026-10-21",
            "cap": 250000,
            "used_tokens": 21000,
        }), encoding="utf-8")

        # Run analysis
        res = analyze_run(self.workspace, max_cycles=30)

        self.assertEqual(res["cycles_analyzed"], 30)

        # 1. Plan activity
        pa = res["plan_activity"]
        self.assertEqual(pa["plan_updated"], 10)
        self.assertEqual(pa["plan_unchanged_agent"], 10)
        self.assertEqual(pa["plan_unchanged_harness_auto"], 10)
        self.assertAlmostEqual(pa["agent_autonomy_pct"], 66.7, places=1)

        # 2. Handoff
        ho = res["handoff"]
        self.assertGreater(ho["chars"], 0)
        self.assertLess(ho["chars"], 6000)
        self.assertEqual(ho["repeats"], 1)

        # 3. Human decisions
        hd = res["human_input_decisions"]
        self.assertEqual(hd["accepted"], 1)
        self.assertEqual(hd["declined"], 1)
        self.assertEqual(hd["modified"], 1)

        # 4. Failures
        ft = res["failure_types"]
        self.assertEqual(ft["llm:HTTP 429"], 1)
        self.assertEqual(ft["tool:run_shell"], 1)
        self.assertEqual(ft["denied:pet_companion.release_pet(L2)"], 1)

        # 5. Plugin events
        pe = res["plugin_events"]
        self.assertEqual(pe["plugin_enabled"], 1)
        self.assertEqual(pe["plugin_pet_fed"], 1)

        # 6. Tokens
        tok = res["tokens"]
        self.assertEqual(tok["total_spent"], 30 * 700)
        self.assertEqual(tok["daily_cap"], 250000)
        self.assertEqual(len(tok["by_cycle"]), 30)
        self.assertEqual(tok["by_cycle"][0]["total_tokens"], 700)
        self.assertEqual(tok["by_cycle"][29]["cumulative_tokens"], 21000)

    def test_analyze_run_real_shape_emitted_by_logger_and_plan_store(self) -> None:
        """E1: Emit actual events through real code paths (PlanStore, PermissionBroker, BaseTools, LLMClient)."""
        import os
        from unittest.mock import MagicMock, patch
        from agent.infra.event_log import EventLogger
        from agent.learning.plan import PlanStore
        from agent.infra.permission_broker import PermissionBroker, ActionRequest, PermissionLevel
        from agent.tools.base_tools import ToolRunner
        from agent.llm.llm import LLMClient

        logger = EventLogger(self.logs_dir / "actions.jsonl")
        plan_store = PlanStore(self.workspace, logger)
        plan_store.initialize()

        # 1. Real plan updates and unchanged logging
        res_add = plan_store.update_plan(action="add", goal="Establish baseline telemetry", cycle=1, reason="Initial plan setup")
        self.assertTrue(res_add["ok"])
        res_stat = plan_store.update_plan(action="edit", id="goal-1", status="done", cycle=2, reason="Baseline captured")
        self.assertTrue(res_stat["ok"])
        plan_store.record_unchanged(cycle=3, source="agent", reason="Plan remains aligned")
        plan_store.record_unchanged(cycle=4, source="harness_auto", reason="Silence fallback")

        # 2. Real human input decision recording
        res_dec = plan_store.record_human_input_decision(
            input_text="Verify metrics",
            decision="accepted",
            reason="Aligned with operational priorities",
            cycle=2,
        )
        self.assertTrue(res_dec["ok"])

        # 3. Real PermissionBroker action_denied
        broker = PermissionBroker(self.workspace, logger=logger)
        req_denied = ActionRequest(action="pet_companion.release_pet", level=PermissionLevel.L2, source="plugin:pet_companion")
        verdict = broker.authorize(req_denied)
        self.assertFalse(verdict.allowed)

        # 4. Real ToolRunner failing dispatch
        tools = ToolRunner(logger=logger, workspace=self.workspace, broker=broker)
        tool_res = tools.execute("read_file", {"path": str(self.workspace / "missing_file_for_test.txt")})
        self.assertFalse(tool_res.get("ok"))

        # 5. Real LLMClient error handling paths (HTTP 400, 429, timeout)
        mock_client = MagicMock()
        class BadRequestError(Exception):
            status_code = 400
        class RateLimitError(Exception):
            status_code = 429
        class APITimeoutError(Exception):
            pass

        with patch.dict(os.environ, {"OLLAMA_API_KEYS": "fake-key", "OLLAMA_BASE_URL": "http://localhost:11434"}):
            llm = LLMClient(logger=logger)

        with patch.object(llm, "_active_client", return_value=mock_client), \
             patch("agent.llm.llm.reserve_provider_call", return_value=1), \
             patch("agent.llm.llm.time.sleep"):
            # 400
            mock_client.messages.create.side_effect = BadRequestError("Bad Request")
            with self.assertRaises(BadRequestError):
                llm.call(system="sys", messages=[{"role": "user", "content": "hi"}], tools=[], max_tokens=100)
            # 429
            mock_client.messages.create.side_effect = RateLimitError("Rate limited")
            with self.assertRaises(RateLimitError):
                llm.call(system="sys", messages=[{"role": "user", "content": "hi"}], tools=[], max_tokens=100)
            # Timeout
            mock_client.messages.create.side_effect = APITimeoutError("Timed out")
            with self.assertRaises(APITimeoutError):
                llm.call(system="sys", messages=[{"role": "user", "content": "hi"}], tools=[], max_tokens=100)

        # 6. Runtime repeated tool action and token spend events
        logger.log("repeated_tool_action_blocked", tool="read_file", cycle=3)
        logger.log("token_spend", cycle=1, call_input_tokens=800, call_output_tokens=400, total_tokens=1200)
        logger.log("token_spend", cycle=2, call_input_tokens=1200, call_output_tokens=600, total_tokens=1800)
        logger.log("plugin_enabled", cycle=1, plugin="hello")
        logger.log("cycle_completed", cycle=1, actions=[{"name": "update_plan"}])
        logger.log("cycle_completed", cycle=2, actions=[{"name": "update_plan"}])

        (self.state_dir / "handoff.json").write_text(json.dumps({"summary": "Clean execution"}), encoding="utf-8")

        res = analyze_run(self.workspace, max_cycles=5)
        self.assertEqual(res["cycles_analyzed"], 4)
        self.assertEqual(res["plan_activity"]["plan_updated"], 2)
        self.assertEqual(res["plan_activity"]["plan_unchanged_agent"], 1)
        self.assertEqual(res["plan_activity"]["plan_unchanged_harness_auto"], 1)
        self.assertEqual(res["human_input_decisions"]["accepted"], 1)
        self.assertEqual(res["failure_types"]["tool:read_file"], 1)
        self.assertEqual(res["failure_types"]["denied:pet_companion.release_pet(L2)"], 1)
        self.assertEqual(res["failure_types"]["llm:BadRequestError"], 1)
        self.assertEqual(res["failure_types"]["llm:RateLimitError"], 1)
        # APITimeoutError is retryable so LLMClient attempts 3 times and logs all 3 failure events
        self.assertEqual(res["failure_types"]["llm:APITimeoutError"], 3)
        self.assertEqual(res["failure_types"]["duplicate_blocked:read_file"], 1)
        self.assertEqual(res["plugin_events"]["plugin_enabled"], 1)
        self.assertEqual(res["tokens"]["total_spent"], 3000)

    def test_analyze_run_against_live_workspace_log_if_present(self) -> None:
        """E1: Run against real workspace/logs/actions.jsonl if present on disk."""
        repo_root = Path(__file__).resolve().parents[3]
        real_ws = repo_root / "workspace"
        real_actions = real_ws / "logs" / "actions.jsonl"
        if not real_actions.exists():
            return
        res = analyze_run(real_ws, max_cycles=30)
        self.assertIn("cycles_analyzed", res)
        self.assertIn("plan_activity", res)
        self.assertIn("handoff", res)
        self.assertIn("human_input_decisions", res)
        self.assertIn("failure_types", res)
        self.assertIn("plugin_events", res)
        self.assertIn("tokens", res)


if __name__ == "__main__":
    unittest.main()
