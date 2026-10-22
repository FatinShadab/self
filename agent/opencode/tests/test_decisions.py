"""Unit and integration tests for Self build route decisions, learning loop, and stats."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agent.helper_models.model_decisions import ModelDecisions
from agent.helper_models.model_outcomes import BuildOutcomes
from agent.infra.event_log import EventLogger
from agent.infra.file_lock import locked_file
from agent.opencode.wrapper import OpencodeDelegator
from agent.tools.base_tools import ToolRunner

FAKE_OPENCODE_PATH = str(Path(__file__).resolve().parent / "fake_opencode.py")


class TestBuildDecisionsAndLearning(unittest.TestCase):
    """Verify decision checkpoints, outcome logs, imbalance stats, and startup resilience."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.workspace = Path(self.tmpdir) / "workspace"
        self.workspace.mkdir()

        # Seed workspace layout
        (self.workspace / ".env").write_text("ANTHROPIC_API_KEY=secret_ant_key\n")
        (self.workspace / "state").mkdir()
        (self.workspace / "logs").mkdir()
        (self.workspace / "workspace" / "tools").mkdir(parents=True)
        (self.workspace / "workspace" / "scratch").mkdir(parents=True)
        (self.workspace / "README.md").write_text("# Project Root\n")

        # Config file for opencode
        cfg_dir = self.workspace / "scripts" / "opencode"
        cfg_dir.mkdir(parents=True)
        self.config_file = cfg_dir / "config.json"
        self.config_file.write_text(
            '{\n  "models": ["groq/llama-3.3-70b-versatile", "google/gemini-2.0-flash"],\n'
            '  "providers": {"groq": {}, "google": {}, "huggingface": {}}\n}\n'
        )

        # Environment variables
        self.orig_env = os.environ.copy()
        os.environ["OPENCODE_GROQ_API_KEY"] = "gsk_valid_key"
        os.environ["OPENCODE_GOOGLE_API_KEY"] = "AIza_valid_key"
        os.environ["OPENCODE_HF_TOKEN"] = "hf_valid_key"
        os.environ["FAKE_OPENCODE_MODE"] = "success"

        self.python_bin = sys.executable
        self.logger = EventLogger(self.workspace / "logs" / "actions.jsonl")
        self.model_decisions = ModelDecisions(
            self.workspace, self.logger, None, None, "test_session_id"
        )

        self.delegator = OpencodeDelegator(
            workspace=self.workspace,
            config_path=self.config_file,
            binary_path=self.python_bin,
            allowed_roots=["workspace/tools", "workspace/scratch"],
            model_decisions=self.model_decisions,
        )

        # Mock sandbox execution to invoke fake_opencode.py via Python
        self.real_run_in_sb = self.delegator.sandbox_manager.run_in_sandbox

        def mock_run_in_sb(cmd, sandbox_path, env, timeout_seconds=1800, shell=False):
            if isinstance(cmd, list) and cmd and cmd[0] == self.python_bin and FAKE_OPENCODE_PATH not in cmd:
                real_cmd = [self.python_bin, FAKE_OPENCODE_PATH] + cmd[1:]
                return self.real_run_in_sb(real_cmd, sandbox_path, env, timeout_seconds, shell=False)
            return self.real_run_in_sb(cmd, sandbox_path, env, timeout_seconds, shell=shell)

        self.delegator.sandbox_manager.run_in_sandbox = mock_run_in_sb

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.orig_env)
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_delegate_then_apply_writes_decision_and_outcome_records(self):
        """Verify delegate_coding auto-records build route and apply writes outcome record."""
        acceptance_cmd = f'"{self.python_bin}" -c "print(\'ok\')"'

        res = self.delegator.delegate_coding(
            spec="Synthesize a helper tool in workspace/tools",
            route_reasons="I chose to delegate this syntax synthesis to opencode.",
            target_dirs=["workspace/tools"],
            acceptance_check=acceptance_cmd,
        )
        self.assertTrue(res["ok"])
        self.assertEqual(res["status"], "completed")
        delegation_id = res["delegation_id"]

        # Check that a decision record was written with origin 'agent' and route 'opencode'
        decisions = self.model_decisions.last_decisions(limit=10)
        route_decisions = [d for d in decisions if d.get("task_type") == "build_route"]
        self.assertTrue(len(route_decisions) >= 1)
        latest_dec = route_decisions[-1]
        self.assertEqual(latest_dec["route"], "opencode")
        self.assertEqual(latest_dec["origin"], "agent")
        self.assertIn("Synthesize a helper tool", latest_dec["task"])

        # Before apply: outcome not yet written as accepted
        apply_res = self.delegator.apply_delegation(delegation_id)
        self.assertTrue(apply_res["ok"])
        self.assertTrue(apply_res["applied"])

        # Check outcome log
        outcomes = self.model_decisions.build_outcomes.last_outcomes(limit=10)
        self.assertTrue(len(outcomes) >= 1)
        latest_outcome = outcomes[-1]
        self.assertEqual(latest_outcome["task_id"], delegation_id)
        self.assertEqual(latest_outcome["route"], "opencode")
        self.assertEqual(latest_outcome["result"], "accepted")
        self.assertTrue(latest_outcome["acceptance_passed"])
        self.assertIsNone(latest_outcome["forced_by"])

    def test_unavailable_instructs_self_and_forced_route_excluded_from_imbalance_stats(self):
        """When opencode is unavailable, plain instructions are returned and forced route is excluded from stats."""
        # Force all providers throttled
        self.delegator.status_tracker.record_failure("groq", "throttled", "Rate limit", reset_seconds=3600)
        self.delegator.status_tracker.record_failure("google", "throttled", "Rate limit", reset_seconds=3600)
        self.delegator.status_tracker.record_failure("huggingface", "throttled", "Rate limit", reset_seconds=3600)

        res = self.delegator.delegate_coding(
            spec="Build a custom data parser",
            route_reasons="Need external coder",
            target_dirs=["workspace/tools"],
            acceptance_check="exit 0",
        )
        self.assertFalse(res["ok"])
        self.assertEqual(res["status"], "unavailable")

        # Instruction text must tell Self plainly about availability and to call record_build_route with forced_by
        msg = res.get("message", "")
        self.assertIn("opencode is unavailable until about", msg)
        self.assertIn("forced_by=opencode_unavailable", msg)

        # Check that unavailable outcome was auto-recorded
        outcomes = self.model_decisions.build_outcomes.last_outcomes(limit=10)
        unavail_outcomes = [o for o in outcomes if o.get("result") == "unavailable"]
        self.assertTrue(len(unavail_outcomes) >= 1)

        # Now simulate Self deciding to do the work itself because opencode was unavailable
        forced_dec = self.model_decisions.record_build_route(
            task="Build a custom data parser",
            route="self",
            reasons="Opencode was unavailable; doing it myself",
            expected_effort="medium",
            forced_by="opencode_unavailable",
        )
        self.assertEqual(forced_dec["origin"], "forced:opencode_unavailable")
        self.assertEqual(forced_dec["route"], "self")

        # Record outcome for self route
        self.model_decisions.record_build_outcome(
            task_id="Build a custom data parser",
            result="accepted",
            notes="Implemented cleanly myself",
            forced_by="opencode_unavailable",
        )

        # Check build_route_stats: forced records MUST be excluded from preference stats counts
        stats = self.model_decisions.build_route_stats(limit=10)
        # Only non-forced records are in counts; our forced record must not count as self preference
        self.assertEqual(stats["counts"]["self"], 0)
        # But forced record is still shown in recent_records with its forced label
        recent_text = "\n".join(stats["recent_records"])
        self.assertIn("forced:opencode_unavailable", recent_text)

    def test_build_route_stats_cap_enforced_with_many_records(self):
        """build_route_stats output stays strictly bounded under the 3000-char cap with many records."""
        # Insert 100 historical build outcome records
        for i in range(100):
            route = "self" if i % 2 == 0 else "opencode"
            self.model_decisions.build_outcomes.append(
                task_id=f"historical_task_{i:03d}",
                route=route,
                reasons=f"Reasoning for task {i} with a detailed explanation of requirements and choices",
                expected_effort="high",
                result="accepted" if i % 3 != 0 else "failed",
                acceptance_passed=i % 3 != 0,
                duration=12.5 + i,
                retries=0,
                forced_by="opencode_unavailable" if i % 10 == 0 else None,
            )

        stats = self.model_decisions.build_route_stats(limit=50)
        serialized = json.dumps(stats, ensure_ascii=False)
        self.assertLessEqual(len(serialized), 3000)

        # Core fields must be populated
        self.assertTrue(stats["ok"])
        self.assertIn("self", stats["counts"])
        self.assertIn("opencode", stats["counts"])
        self.assertIn("self", stats["pass_rate"])
        self.assertIn("opencode", stats["pass_rate"])
        self.assertIn("self", stats["median_duration_seconds"])
        self.assertIn("opencode", stats["median_duration_seconds"])
        self.assertTrue(len(stats["recent_records"]) > 0)

    def test_imbalance_note_threshold(self):
        """Imbalance note appears when >80% of last 10 non-forced records are one route, but not below."""
        # 1. 8 out of 10 are opencode (exactly 80% -> below threshold of 'more than 80%')
        for i in range(8):
            self.model_decisions.build_outcomes.append(
                task_id=f"task_op_{i}",
                route="opencode",
                reasons="Delegate",
                expected_effort="low",
                result="accepted",
                acceptance_passed=True,
                duration=5.0,
            )
        for i in range(2):
            self.model_decisions.build_outcomes.append(
                task_id=f"task_self_{i}",
                route="self",
                reasons="Self",
                expected_effort="low",
                result="accepted",
                acceptance_passed=True,
                duration=2.0,
            )

        stats_80 = self.model_decisions.build_route_stats(limit=10)
        self.assertIsNone(stats_80["note"])

        # 2. Add 9 more opencode records: now the last 10 records contain 1 self and 9 opencode (90% > 80%)
        for i in range(9):
            self.model_decisions.build_outcomes.append(
                task_id=f"task_op_extra_{i}",
                route="opencode",
                reasons="Delegate again",
                expected_effort="low",
                result="accepted",
                acceptance_passed=True,
                duration=4.5,
            )

        stats_90 = self.model_decisions.build_route_stats(limit=10)
        self.assertIsNotNone(stats_90["note"])
        self.assertIn("mostly used one route lately", stats_90["note"])

    def test_startup_works_with_opencode_missing(self):
        """Startup and status checks succeed gracefully when opencode executable is missing."""
        delegator_missing = OpencodeDelegator(
            workspace=self.workspace,
            binary_path="/opt/nonexistent/bin/opencode",
            model_decisions=self.model_decisions,
        )

        self.assertFalse(delegator_missing.is_installed())
        st = delegator_missing.status()
        self.assertTrue(st["ok"])
        self.assertFalse(st["installed"])
        self.assertFalse(st["usable"])
        self.assertEqual(st["reason"], "opencode not installed")

        # Attempting delegation with missing binary returns unavailable with clear guidance
        res = delegator_missing.delegate_coding(
            spec="Do some work",
            route_reasons="Want to delegate",
            target_dirs=["workspace/tools"],
            acceptance_check="exit 0",
        )
        self.assertFalse(res["ok"])
        self.assertEqual(res["status"], "unavailable")
        self.assertIn("opencode is not installed", res["message"])

    def test_tool_runner_record_build_route_and_stats(self):
        """ToolRunner properly exposes record_build_route, record_build_outcome, and build_route_stats."""
        runner = ToolRunner(self.logger, self.workspace)
        runner.model_decisions = self.model_decisions

        # 1. record_build_route
        route_res = runner.record_build_route(
            task="create_scaffold",
            route="self",
            reasons="I prefer to write this directly.",
            expected_effort="low",
        )
        self.assertEqual(route_res["route"], "self")
        self.assertEqual(route_res["origin"], "agent")

        # 2. record_build_outcome
        outcome_res = runner.record_build_outcome(
            task_id="create_scaffold",
            result="accepted",
            notes="Completed without error.",
        )
        self.assertEqual(outcome_res["result"], "accepted")
        self.assertEqual(outcome_res["route"], "self")

        # 3. build_route_stats
        stats_res = runner.build_route_stats(limit=5)
        self.assertTrue(stats_res["ok"])
        self.assertEqual(stats_res["counts"]["self"], 1)


if __name__ == "__main__":
    unittest.main()
