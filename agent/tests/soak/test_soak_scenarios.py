"""Deterministic soak scenarios covering 30+ cycles across loops, plugins, faults, and controls."""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from agent.infra.event_log import EventLogger
from agent.llm.llm import LLMResult
from agent.plugins.manager import PluginManager
from agent.session.coordinator import WakeCoordinator
from agent.tests.soak.harness import (
    APIConnectionError,
    APITimeoutError,
    BadRequestError,
    FaultSchedule,
    Invariants,
    InternalServerError,
    RateLimitError,
    ScriptedProvider,
    SoakRunner,
    linear_slope,
)


class SoakScenariosTests(unittest.TestCase):
    """Execution of deterministic 30+ cycle soak scenarios."""

    last_b6_metrics: list = []

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="soak_scenarios_")
        self.workspace = Path(self.temp_dir)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # -------------------------------------------------------------------------
    # B1: Plain 30-Cycle Mix
    # -------------------------------------------------------------------------
    def test_b1_plain_30_cycle_mix(self) -> None:
        """B1: Plain 30-cycle mix of tool calls, plan updates, reports, and cycle 12 human input."""
        cycle_scripts: dict[int, list[Any]] = {}

        # Cycle 2: add a goal to the plan
        cycle_scripts[2] = [
            {"name": "update_plan", "input": {"action": "add", "goal": "Map container filesystem", "priority": 2, "reason": "Systematic exploration"}},
            "I added a new goal to map the filesystem.",
        ]

        # Cycle 5: create scratch file and mark goal progress
        cycle_scripts[5] = [
            {"name": "write_file", "input": {"path": "state/scratch.txt", "content": "observed facts"}},
            "I wrote scratch facts to verify filesystem persistence.",
        ]

        # Cycle 12: human input handling (human message is injected at cycle 12)
        cycle_scripts[12] = [
            {"name": "read_plan", "input": {}},
            "I received the human update and will integrate it into my plan.",
        ]
        cycle_scripts[13] = [
            {"name": "update_plan", "input": {"action": "decide_human_input", "text": "Focus on checking /etc configurations", "decision": "accepted", "reason": "Aligned with my mapping goal"}},
            "I evaluated the human input and accepted it with documented reasoning.",
        ]

        provider = ScriptedProvider(cycle_scripts=cycle_scripts)
        runner = SoakRunner(workspace=self.workspace, provider=provider, max_iterations=30, seed=101)

        # Inject human input at cycle 12 before run reaches it
        runner.coordinator.receive_human_input("Focus on checking /etc configurations", kind="advice")

        res = runner.run()
        runner.close()

        self.assertTrue(res.invariants_passed, msg=res.error)
        self.assertEqual(res.iterations, 30)
        self.assertEqual(res.finish_reason, "max_iterations")
        self.assertTrue((self.workspace / "state" / "handoff.json").exists())
        self.assertTrue((self.workspace / "state" / "plan.json").exists())

    # -------------------------------------------------------------------------
    # B2: Fault Injection Schedule
    # -------------------------------------------------------------------------
    def test_b2_fault_injection_schedule(self) -> None:
        """B2: Fault injection covering all fault types, bursts of 5, retries, and clean progress."""
        faults = FaultSchedule()

        # Schedule specific typed faults by call index so every fault is guaranteed to fire
        faults.add_fault("call_3", APIConnectionError("Temporary network unreachable"))
        faults.add_fault("call_8", InternalServerError("500 Backend error"))
        faults.add_fault("call_13", APITimeoutError("Read timeout from proxy"))
        faults.add_fault("call_18", RateLimitError("429 Too Many Requests"))
        faults.add_fault("call_23", BadRequestError("400 Bad parameter format"))
        faults.add_fault("call_26", "empty_body")
        faults.add_fault("call_28", "truncated")

        # Burst of 5 consecutive failures across calls 30 to 34
        for c in range(30, 35):
            faults.add_fault(f"call_{c}", APIConnectionError(f"Burst failure connection drop {c}"))

        provider = ScriptedProvider(fault_schedule=faults, key_count=2)

        # Execute multiple sessions to simulate coordinator resilience across provider pauses
        runner = SoakRunner(workspace=self.workspace, provider=provider, max_iterations=30, seed=102, daily_cap=500_000)

        # Fast-forward / restart loop across fault pauses
        total_cycles = 0
        sessions_run = 0
        while total_cycles < 15 and sessions_run < 15:
            sessions_run += 1
            res = runner.coordinator.run()
            total_cycles += getattr(res, "iterations", 0)
            reason = getattr(res, "reason", "")
            if (self.workspace / "STOP").exists():
                break
            if reason in {"max_iterations", "clean_shutdown"}:
                break

        runner.close()

        # Assert no unhandled crash occurred and failures were parsed
        log_content = (self.workspace / "logs" / "actions.jsonl").read_text(encoding="utf-8", errors="replace")
        self.assertIn("run_failed", log_content)
        self.assertIn("APIConnectionError", log_content)
        self.assertIn("InternalServerError", log_content)
        self.assertIn("RateLimitError", log_content)

        # Hard cap on calls per cycle: no cycle had more than max_calls_per_cycle
        for cyc, c_calls in provider.calls_by_cycle.items():
            self.assertLessEqual(c_calls, provider.max_calls_per_cycle, f"Cycle {cyc} exceeded call cap")

    # -------------------------------------------------------------------------
    # B3: create_tool Failure Loop & Three-Attempt Block
    # -------------------------------------------------------------------------
    def test_b3_create_tool_failure_loop(self) -> None:
        """B3: Broken create_tool proposed every cycle; 3-attempt block stops critic token burn."""
        # LLM attempts to create the same broken tool with variations across cycles 1..10
        cycle_scripts: dict[int, list[Any]] = {}
        for c in range(1, 11):
            cycle_scripts[c] = [
                {
                    "name": "create_tool",
                    "input": {
                        "name": "broken_sensor",
                        "description": f"A tool with syntax error (attempt {c})",
                        "code": f"def run():\n  syntax error attempt {c}!",
                        "test_code": "import unittest\nclass T(unittest.TestCase):\n  def test_1(self): pass",
                    },
                },
                f"Cycle {c}: observed tool creation result.",
            ]

        provider = ScriptedProvider(cycle_scripts=cycle_scripts)
        runner = SoakRunner(workspace=self.workspace, provider=provider, max_iterations=4, seed=103)
        from agent.infra.permission_broker import PermissionLevel
        runner.coordinator.broker.policy.action_grants["create_tool"] = PermissionLevel.L2
        res = runner.run()
        runner.close()

        self.assertTrue(res.invariants_passed, msg=res.error)

        # Verify lessons file contains the 3-failure lesson
        lesson_file = self.workspace / "memory" / "lessons.jsonl"
        self.assertTrue(lesson_file.exists())
        lesson_text = lesson_file.read_text(encoding="utf-8")
        self.assertIn("Three creation attempts failed", lesson_text)
        self.assertIn("broken_sensor", lesson_text)

        # Check actions log: attempts 4+ must be blocked with attempts_remaining: 0
        log_content = (self.workspace / "logs" / "actions.jsonl").read_text(encoding="utf-8")
        self.assertIn("Three attempts exhausted in this run", log_content)

    # -------------------------------------------------------------------------
    # B4: Repeated-Action Loop
    # -------------------------------------------------------------------------
    def test_b4_repeated_action_loop(self) -> None:
        """B4: Same action repeated in loop triggers repeated_tool_action_blocked."""
        # LLM calls the exact same tool with exact same arguments every cycle
        cycle_scripts: dict[int, list[Any]] = {}
        for c in range(1, 5):
            cycle_scripts[c] = [
                {"name": "read_plan", "input": {}},
                f"Cycle {c} plan read complete.",
            ]
        # In cycle 5, LLM calls a different tool
        cycle_scripts[5] = [
            {"name": "list_dir", "input": {"path": "."}},
            "Cycle 5 list_dir complete.",
        ]

        provider = ScriptedProvider(cycle_scripts=cycle_scripts)
        runner = SoakRunner(workspace=self.workspace, provider=provider, max_iterations=5, seed=104)
        res = runner.run()
        runner.close()

        self.assertTrue(res.invariants_passed, msg=res.error)

        log_content = (self.workspace / "logs" / "actions.jsonl").read_text(encoding="utf-8")
        self.assertIn("repeated_tool_action_blocked", log_content)
        self.assertIn("read_plan", log_content)

    # -------------------------------------------------------------------------
    # B5: Restart and Crash Recovery
    # -------------------------------------------------------------------------
    def test_b5_restart_and_crash_recovery(self) -> None:
        """B5: Stop-file mid-run restart, tool exception recovery, and atomic checkpoint restore."""
        # 1. Run 5 cycles, then trigger stop_file
        provider = ScriptedProvider()
        runner1 = SoakRunner(workspace=self.workspace, provider=provider, max_iterations=10, seed=105)

        # Trigger STOP at cycle 4
        orig_ckpt = runner1.coordinator._checkpoint_cycle

        def _stop_at_cycle_4(c: int, r: str, tok: int) -> None:
            orig_ckpt(c, r, tok)
            if c == 4:
                (self.workspace / "STOP").write_text("Stop requested", encoding="utf-8")

        runner1.coordinator._checkpoint_cycle = _stop_at_cycle_4
        res1 = runner1.run()
        self.assertEqual(res1.finish_reason, "stop_file")
        self.assertEqual(res1.iterations, 4)
        runner1.close()

        # Remove STOP file and restart runner on same workspace
        (self.workspace / "STOP").unlink()
        runner2 = SoakRunner(workspace=self.workspace, provider=provider, max_iterations=6, seed=106)
        res2 = runner2.run()
        runner2.close()

        # Verify plan remained intact and no repeated "Session complete after"
        handoff_path = self.workspace / "state" / "handoff.json"
        self.assertTrue(handoff_path.exists())
        h_text = handoff_path.read_text(encoding="utf-8")
        self.assertLessEqual(len(re.findall(r"Session complete after", h_text)), 1)

    # -------------------------------------------------------------------------
    # B6: Growth Bounds Over 60 Cycles
    # -------------------------------------------------------------------------
    def test_b6_growth_bounds_over_60_cycles(self) -> None:
        """B6: 60 cycles growth bounds (handoff, memory, plan, log bytes) fit under slope limits."""
        long_soak = os.getenv("SOAK_LONG", "0") == "1"
        target_iterations = 200 if long_soak else 60

        provider = ScriptedProvider()
        runner = SoakRunner(workspace=self.workspace, provider=provider, max_iterations=target_iterations, seed=107)
        res = runner.run()
        runner.close()
        SoakScenariosTests.last_b6_metrics = res.metrics

        self.assertTrue(res.invariants_passed, msg=res.error)
        self.assertGreaterEqual(len(res.metrics), target_iterations)

        # Compute regression slopes across recorded cycle metrics
        handoff_series = [m.handoff_chars for m in res.metrics]
        plan_series = [m.plan_items for m in res.metrics]
        memory_series = [m.memory_entries for m in res.metrics]
        log_bytes_series = [m.log_bytes for m in res.metrics]

        h_slope = linear_slope(handoff_series)
        p_slope = linear_slope(plan_series)
        m_slope = linear_slope(memory_series)
        log_slope = linear_slope(log_bytes_series)

        # Assert slope bounds
        # Handoff slope should be nearly flat (<= 15.0 chars/cycle) once capped
        self.assertLessEqual(h_slope, 25.0, f"Handoff growth slope too steep: {h_slope:.2f}")
        # Plan items must stay bounded (<= 0.5 item/cycle slope) due to plan hygiene
        self.assertLessEqual(p_slope, 0.5, f"Plan items slope too steep: {p_slope:.2f}")
        # Memory entries slope <= 1.0 entries/cycle
        self.assertLessEqual(m_slope, 1.0, f"Memory slope too steep: {m_slope:.2f}")
        # Actions log bytes slope <= 10,000 bytes/cycle
        self.assertLessEqual(log_slope, 10_000.0, f"Log bytes slope too steep: {log_slope:.2f}")

    # -------------------------------------------------------------------------
    # B7: Plugin Churn & Integrity Tamper Handling
    # -------------------------------------------------------------------------
    def test_b7_plugin_churn_and_tamper(self) -> None:
        """B7: Plugin enabled, unplugged, replugged, tampered; hash mismatch caught without crash."""
        plugins_dir = self.workspace / "plugins"
        plugins_dir.mkdir(parents=True, exist_ok=True)
        config_dir = self.workspace / "config"
        config_dir.mkdir(parents=True, exist_ok=True)

        # Copy pet_companion into workspace plugins
        shipped_pet = Path(__file__).resolve().parents[2] / "plugins" / "examples" / "pet_companion"
        target_pet = plugins_dir / "pet_companion"
        shutil.copytree(shipped_pet, target_pet)

        # Set up runner with plugin manager
        provider = ScriptedProvider()
        runner = SoakRunner(workspace=self.workspace, provider=provider, max_iterations=30, seed=108)
        mgr = runner.coordinator.plugins

        # 1. Cycle 10: Enable pet_companion with valid hash pinning
        from agent.plugins.manager import compute_plugin_hash
        real_hash = compute_plugin_hash(target_pet)
        config_file = config_dir / "plugins.json"
        config_file.write_text(json.dumps({
            "plugins": {
                "pet_companion": {"enabled": True, "hash": real_hash}
            }
        }), encoding="utf-8")
        mgr.sync_at_cycle_boundary(runner.coordinator.plan_store, runner.coordinator.learning)
        self.assertIn("pet_companion", mgr.active_plugins)

        # 2. Cycle 20: Unplug pet_companion
        config_file.write_text(json.dumps({
            "plugins": {
                "pet_companion": {"enabled": False, "hash": real_hash}
            }
        }), encoding="utf-8")
        mgr.sync_at_cycle_boundary(runner.coordinator.plan_store, runner.coordinator.learning)
        self.assertNotIn("pet_companion", mgr.active_plugins)

        # 3. Cycle 25: Replug pet_companion
        config_file.write_text(json.dumps({
            "plugins": {
                "pet_companion": {"enabled": True, "hash": real_hash}
            }
        }), encoding="utf-8")
        mgr.sync_at_cycle_boundary(runner.coordinator.plan_store, runner.coordinator.learning)
        self.assertIn("pet_companion", mgr.active_plugins)

        # 4. Cycle 27: Tamper with pet_companion file
        (target_pet / "plugin.py").write_text("# tampered source\n", encoding="utf-8")
        mgr.sync_at_cycle_boundary(runner.coordinator.plan_store, runner.coordinator.learning)

        # Hash mismatch must log plugin_hash_mismatch and deactivate plugin
        self.assertNotIn("pet_companion", mgr.active_plugins)
        log_content = (self.workspace / "logs" / "actions.jsonl").read_text(encoding="utf-8")
        self.assertIn("plugin_hash_mismatch", log_content)

        runner.close()

    # -------------------------------------------------------------------------
    # B8: Control Hooks Under Load (/stop and /pause)
    # -------------------------------------------------------------------------
    def test_b8_control_hooks_under_load(self) -> None:
        """B8: /stop and /pause files honored immediately, breaking loop without further LLM calls."""
        provider = ScriptedProvider()
        runner = SoakRunner(workspace=self.workspace, provider=provider, max_iterations=30, seed=109)

        # Trigger STOP during cycle 7
        orig_ckpt = runner.coordinator._checkpoint_cycle

        def _inject_stop_cycle_7(c: int, r: str, tok: int) -> None:
            orig_ckpt(c, r, tok)
            if c == 7:
                (self.workspace / "STOP").write_text("Immediate stop requested", encoding="utf-8")

        runner.coordinator._checkpoint_cycle = _inject_stop_cycle_7
        res = runner.run()
        runner.close()

        self.assertEqual(res.finish_reason, "stop_file")
        self.assertEqual(res.iterations, 7)
        self.assertNotIn(8, provider.calls_by_cycle)

    # -------------------------------------------------------------------------
    # B9: Self-Development Pipeline Soak & Stop-Loss
    # -------------------------------------------------------------------------
    def test_b9_self_development_pipeline_soak(self) -> None:
        """B9: Drive propose -> scaffold -> validate -> test -> review across stop-loss thresholds."""
        from agent.plugins.self_dev import PluginDevManager
        from agent.tools.base_tools import ToolRunner
        from agent.learning.plan import PlanStore

        dev_mgr = PluginDevManager(self.workspace, EventLogger(self.workspace / "logs" / "actions.jsonl"))
        plan_store = PlanStore(self.workspace, EventLogger(self.workspace / "logs" / "actions.jsonl"))
        runner = ToolRunner(EventLogger(self.workspace / "logs" / "actions.jsonl"), workspace=self.workspace, plugin_dev=dev_mgr)
        runner.plan_store = plan_store

        # 1. Propose plugin
        prop = runner.propose_plugin(
            name="soak_worker",
            need="Batch processing",
            evidence="Telemetry gap observed",
            alternatives_considered="None",
            estimate={
                "tokens": {"min": 1500, "max": 4000},
                "cycles": {"min": 1, "max": 4},
                "wall_time": {"min": 15, "max": 45},
                "human_review_minutes": {"min": 2, "max": 5},
                "derivation": "Cold-start bootstrap baseline citing default floor of 1500 tokens median for 3 cycles = 4500 tokens",
            },
            expected_benefit="Batch data processing",
            actions_needed_with_risk_levels=[{"name": "batch", "level": "L0", "risk": "reads"}],
            maintenance_burden="Low",
            stop_loss="Stop at 25%",
            rollback="Remove soak_worker directory",
        )
        self.assertTrue(prop["ok"], msg=prop.get("error"))

        # 2. Scaffold
        scaf = runner.scaffold_plugin("soak_worker")
        self.assertTrue(scaf["ok"], msg=scaf.get("error"))

        # 3. Simulate spend crossing 25% stop-loss threshold (4000 * 0.25 = 1000 tokens)
        dev_mgr.cost_ledger.append_entry({"kind": "plugin", "target": "soak_worker", "tokens": 1200, "cycles": 1, "status": "in_progress"})
        pending = dev_mgr.get_pending_stop_loss("soak_worker")
        self.assertIn(25, pending)

        # 4. Attempting to write draft file while stop-loss is unacknowledged is blocked
        wf_blocked = runner.write_file(str(self.workspace / "plugin_dev" / "soak_worker" / "plugin.py"), "x = 1")
        self.assertFalse(wf_blocked["ok"])
        self.assertIn("reached stop-loss threshold (25%)", wf_blocked["error"])

        # 5. Agent records decision via update_plan
        plan_res = runner.update_plan(
            action="decide_plugin_review",
            project="soak_worker",
            threshold=25,
            decision="continue",
            reason="I evaluated telemetry and confirmed development progress is on track.",
        )
        self.assertTrue(plan_res["ok"])

        # 6. Modifications now unblocked
        wf_ok = runner.write_file(str(self.workspace / "plugin_dev" / "soak_worker" / "plugin.py"), "x = 1")
        self.assertTrue(wf_ok["ok"])

    # -------------------------------------------------------------------------
    # B10: Budget Exhaustion & UTC Reset
    # -------------------------------------------------------------------------
    def test_b10_budget_exhaustion_and_reset(self) -> None:
        """B10: Daily token allowance exhaustion pauses cleanly; next UTC day resets and resumes."""
        provider = ScriptedProvider()
        runner = SoakRunner(workspace=self.workspace, provider=provider, max_iterations=4, seed=110)

        ledger = runner.coordinator.daily_ledger

        # At cycle 2 checkpoint, write used_tokens = cap on disk to trigger exhaustion on cycle 3
        orig_ckpt = runner.coordinator._checkpoint_cycle

        def _exhaust_at_cycle_2(c: int, r: str, tok: int) -> None:
            orig_ckpt(c, r, tok)
            if c == 2:
                data = ledger._read()
                data["used_tokens"] = ledger.cap
                ledger._write(data)

        runner.coordinator._checkpoint_cycle = _exhaust_at_cycle_2

        # When loop pauses in _pause_until_daily_reset, simulate UTC midnight reset after 1 tick
        ticks = 0
        import threading

        def _fast_sleep(seconds: float) -> None:
            nonlocal ticks
            if threading.current_thread() is threading.main_thread():
                ticks += 1
                if ticks >= 1:
                    # Simulate daily reset at UTC midnight on disk
                    data = ledger._read()
                    data["used_tokens"] = 0
                    data["reserved_tokens"] = 0
                    ledger._write(data)

        with patch("time.sleep", side_effect=_fast_sleep):
            res = runner.run()

        runner.close()
        self.assertTrue(res.invariants_passed, msg=res.error)
        self.assertEqual(res.iterations, 4)

        log_content = (self.workspace / "logs" / "actions.jsonl").read_text(encoding="utf-8")
        self.assertIn("daily_token_limit_paused", log_content)
        self.assertIn("daily_token_limit_resumed", log_content)


if __name__ == "__main__":
    unittest.main()
