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


if __name__ == "__main__":
    unittest.main()
