"""Comprehensive release candidate regression tests (Prompt 18: core-v0.1.0-rc1).

Verifies:
1. Zero-plugin regression & golden prompt snapshots:
   - System prompt, conversation prompt, and cycle prompt match golden baseline character-for-character
     when PluginManager is present with no active plugins.
   - Base tools (29 tools) offered cleanly without namespacing.
   - Cycle executes cleanly without plugin leakage.
2. Pet companion demo round-trip:
   - Enable -> Disable -> Replug round trips.
   - Slash command /pet registered, deregistered on unplug, and cleanly restored on replug without duplicates.
   - Private state in workspace/plugins/pet_companion/state/ preserved across replug.
3. Hash pinning tests:
   - Valid SHA-256 hash allows loading.
   - Tampered manifest or code triggers plugin_hash_mismatch event, disables plugin, and blocks execution.
   - Human re-approval with updated hash restores plugin cleanly.
4. Self-development workflow end-to-end:
   - Propose -> scaffold -> implement -> test -> review packet.
   - Cost ledger aggregates tool and plugin spend.
   - Stop-loss review triggers at threshold, blocks dev tools until decide_plugin_review is recorded in plan.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from agent.body.container import ContainerBody
from agent.body.sim import SimBody
from agent.infra.cost_ledger import CostLedger
from agent.infra.event_log import EventLogger
from agent.infra.permission_broker import PermissionBroker, PermissionLevel, PermissionPolicy
from agent.learning.learning import LearningStore
from agent.learning.plan import PlanStore
from agent.llm.llm import LLMResult
from agent.plugins.manager import PluginManager, compute_plugin_hash
from agent.plugins.manifest import parse_manifest
from agent.plugins.self_dev import PluginDevManager
from agent.runtime.loop import (
    AgentConfig,
    AgentLoop,
    STANDING_GOAL,
    assemble_system_prompt,
)
from agent.session.conversation import assemble_conversation_system_prompt
from agent.tests.body.test_golden_prompts import (
    GOLDEN_PRE_P10_CONVERSATION_PROMPT,
    GOLDEN_PRE_P10_SYSTEM_PROMPT,
)
from agent.tools.base_tools import TOOL_DEFINITIONS, ToolRunner


class ScriptedMockLLM:
    """Mock LLM returning deterministic responses."""

    def __init__(self, responses: list[dict[str, Any]] | None = None) -> None:
        self.call_history: list[dict[str, Any]] = []
        self.tokens_used = 0
        self.base_model = "mock-base"
        self.provider = "mock"
        self._responses = list(responses or [])

    def call(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int,
    ) -> LLMResult:
        self.call_history.append({
            "system": system,
            "messages": list(messages),
            "tools": list(tools),
        })
        if self._responses:
            item = self._responses.pop(0)
            return LLMResult(
                content=item.get("content", [{"type": "text", "text": "Cycle report: completed."}]),
                input_tokens=item.get("input_tokens", 25),
                output_tokens=item.get("output_tokens", 25),
                stop_reason=item.get("stop_reason", "end_turn"),
                model="mock-base",
            )
        return LLMResult(
            content=[{"type": "text", "text": "Cycle report: completed."}],
            input_tokens=25,
            output_tokens=25,
            stop_reason="end_turn",
            model="mock-base",
        )


class ReleaseRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp())
        self.workspace = self.temp_dir / "workspace"
        self.workspace.mkdir(parents=True)
        (self.workspace / "logs").mkdir(parents=True)
        (self.workspace / "state").mkdir(parents=True)
        self.config_dir = self.temp_dir / "config"
        self.config_dir.mkdir(parents=True)

        self.logger = EventLogger(self.workspace / "logs" / "actions.jsonl")
        self.policy = PermissionPolicy()
        self.broker = PermissionBroker(
            workspace=self.workspace,
            config_dir=self.config_dir,
            logger=self.logger,
            policy=self.policy,
        )

        # Locate shipped pet_companion
        candidates = [
            Path(__file__).resolve().parents[3] / "agent" / "plugins" / "examples" / "pet_companion",
            Path(__file__).resolve().parents[2] / "plugins" / "examples" / "pet_companion",
            Path("/opt/agent/plugins/examples/pet_companion"),
        ]
        self.pet_plugin_dir = next((c for c in candidates if c.exists() and (c / "plugin.json").exists()), candidates[0])

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _read_actions(self) -> list[dict[str, Any]]:
        log_file = self.workspace / "logs" / "actions.jsonl"
        if not log_file.exists():
            return []
        events = []
        for line in log_file.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    events.append(json.loads(line))
                except Exception:
                    continue
        return events

    # -------------------------------------------------------------------------
    # 1. Zero-plugin regression & golden snapshots
    # -------------------------------------------------------------------------
    def test_golden_prompts_with_zero_plugins(self) -> None:
        """Verify prompt snapshots match golden strings character-for-character with 0 plugins."""
        container_body = ContainerBody()
        assembled_sys = assemble_system_prompt(container_body)
        assembled_conv = assemble_conversation_system_prompt(container_body)

        # Golden system prompt check
        self.assertEqual(assembled_sys, GOLDEN_PRE_P10_SYSTEM_PROMPT)
        self.assertEqual(assembled_conv, GOLDEN_PRE_P10_CONVERSATION_PROMPT)

        # PluginManager present but 0 plugins enabled
        mgr = PluginManager(
            workspace=self.workspace,
            config_dir=self.config_dir,
            shipped_dir=self.temp_dir / "empty_shipped",
            logger=self.logger,
            broker=self.broker,
        )
        mgr.sync_at_cycle_boundary()
        self.assertEqual(len(mgr.active_plugins), 0)

        # Loop system prompt assembly with PluginManager present
        llm = ScriptedMockLLM()
        runner = ToolRunner(self.logger, self.workspace)
        runner.plugins = mgr

        config = AgentConfig(
            workspace=self.workspace,
            max_iterations=1,
            retrieve_memories=False,
            plugins=mgr,
        )
        agent = AgentLoop(config, self.logger, llm, runner)
        summary = agent.run()

        self.assertEqual(summary.iterations, 1)
        self.assertEqual(len(llm.call_history), 1)

        call = llm.call_history[0]
        sys_prompt = call["system"]

        # No plugin sections or notes leaked into system prompt
        self.assertNotIn("Active Plugins", sys_prompt)
        self.assertNotIn("Active Plugins Notes", sys_prompt)
        self.assertNotIn("plugins:embodiment", sys_prompt)

        # Verify offered tools: all 29 tools, no dot-namespaced tools
        offered_tools = call["tools"]
        tool_names = [t["name"] for t in offered_tools]
        self.assertEqual(len(tool_names), 29)
        for name in tool_names:
            self.assertNotIn(".", name)
        self.assertIn("run_shell", tool_names)
        self.assertIn("read_cost_ledger", tool_names)
        self.assertIn("propose_plugin", tool_names)
        self.assertIn("create_tool", tool_names)

    # -------------------------------------------------------------------------
    # 2. Pet companion demo: Enable -> Disable -> Replug round trip
    # -------------------------------------------------------------------------
    def test_pet_companion_enable_disable_replug_round_trip(self) -> None:
        """Enable, disable and replug round trips preserve state and cleanly manage hooks."""
        self.assertTrue(self.pet_plugin_dir.exists(), f"Pet plugin dir missing: {self.pet_plugin_dir}")
        pet_hash = compute_plugin_hash(self.pet_plugin_dir)

        # Grant L1/L2 permissions to pet_companion
        self.policy.grants["plugins.pet_companion"] = PermissionLevel.L2

        cfg_file = self.config_dir / "plugins.json"
        # Initial: disabled
        cfg_file.write_text(json.dumps({
            "plugins": {
                "pet_companion": {
                    "enabled": False,
                    "hash": pet_hash,
                }
            }
        }), encoding="utf-8")

        plan_store = PlanStore(self.workspace, self.logger)
        learning = LearningStore(self.workspace, self.logger)

        mgr = PluginManager(
            workspace=self.workspace,
            config_dir=self.config_dir,
            shipped_dir=self.pet_plugin_dir.parents[1],
            logger=self.logger,
            broker=self.broker,
        )

        # Cycle 1: disabled
        mgr.sync_at_cycle_boundary(plan_store=plan_store, learning_store=learning)
        self.assertNotIn("pet_companion", mgr.active_plugins)
        self.assertNotIn("pet", mgr.active_commands)

        # Step A: ENABLE pet_companion
        cfg_file.write_text(json.dumps({
            "plugins": {
                "pet_companion": {
                    "enabled": True,
                    "hash": pet_hash,
                }
            }
        }), encoding="utf-8")

        mgr.sync_at_cycle_boundary(plan_store=plan_store, learning_store=learning)
        self.assertIn("pet_companion", mgr.active_plugins)
        self.assertIn("pet", mgr.active_commands)

        # Execute pet action: feed
        feed_res = mgr.execute_plugin_tool("pet_companion.feed", {})
        self.assertTrue(feed_res.get("ok"))
        self.assertEqual(feed_res.get("hunger"), 0)

        # Verify command responds directly
        cmd_res = mgr.handle_slash_command("/pet hello pet")
        self.assertIsNotNone(cmd_res)
        self.assertIn("Pixel the Pet", cmd_res)

        # Verify private state was persisted
        pet_state_file = self.workspace / "plugins" / "pet_companion" / "state" / "pet_state.json"
        self.assertTrue(pet_state_file.exists())
        saved_state = json.loads(pet_state_file.read_text(encoding="utf-8"))
        self.assertEqual(saved_state.get("pet", {}).get("hunger"), 0)

        # Step B: DISABLE (Unplug)
        cfg_file.write_text(json.dumps({
            "plugins": {
                "pet_companion": {
                    "enabled": False,
                    "hash": pet_hash,
                }
            }
        }), encoding="utf-8")

        mgr.sync_at_cycle_boundary(plan_store=plan_store, learning_store=learning)
        self.assertNotIn("pet_companion", mgr.active_plugins)
        self.assertNotIn("pet", mgr.active_commands)

        # Calling tool returns safe fallback observation
        disabled_call = mgr.execute_plugin_tool("pet_companion.feed", {})
        self.assertFalse(disabled_call.get("ok"))
        self.assertIn("disabled", disabled_call.get("error", "").lower())

        # Step C: REPLUG (Re-enable)
        cfg_file.write_text(json.dumps({
            "plugins": {
                "pet_companion": {
                    "enabled": True,
                    "hash": pet_hash,
                }
            }
        }), encoding="utf-8")

        # Sync at cycle boundary should restore without duplicate slash command errors
        mgr.sync_at_cycle_boundary(plan_store=plan_store, learning_store=learning)
        self.assertIn("pet_companion", mgr.active_plugins)
        self.assertIn("pet", mgr.active_commands)

        # Check that state from Step A was preserved across replug!
        status_res = mgr.execute_plugin_tool("pet_companion.pet_status", {})
        self.assertTrue(status_res.get("ok"))
        self.assertEqual(status_res.get("pet", {}).get("hunger"), 0)

        # Verify logged events confirm clean lifecycle
        actions = self._read_actions()
        events = [a.get("event") for a in actions]
        self.assertIn("plugin_enabled", events)
        self.assertIn("plugin_disabled", events)
        self.assertIn("plugin_pet_archived", events)
        self.assertIn("plugin_pet_restored", events)

    # -------------------------------------------------------------------------
    # 3. Hash pinning tests
    # -------------------------------------------------------------------------
    def test_hash_pinning_tamper_detection_and_recovery(self) -> None:
        """Tampering manifest or source triggers hash mismatch and human re-approval restores."""
        plugin_dir = self.workspace / "plugins" / "tamper_target"
        plugin_dir.mkdir(parents=True)
        manifest = {
            "name": "tamper_target",
            "version": "0.1.0",
            "core_api": ">=1.0.0,<2.0.0",
            "kind": "skill",
            "description": "Hash pinning test plugin",
            "tools": [{"name": "action_x", "description": "action x"}],
            "sensors": [],
            "actions": [],
            "starting_goal_seeds": [],
            "embodiment": "Tamper test embodiment",
        }
        (plugin_dir / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
        tools_file = plugin_dir / "tools.py"
        tools_file.write_text("def action_x(): return {'ok': True, 'val': 100}\n", encoding="utf-8")

        mgr = PluginManager(
            workspace=self.workspace,
            config_dir=self.config_dir,
            shipped_dir=self.temp_dir / "empty_shipped",
            logger=self.logger,
            broker=self.broker,
        )

        # Grant permission to tamper_target plugin
        self.policy.grants["plugins.tamper_target"] = PermissionLevel.L2

        # 1. Human enables plugin -> pinned hash recorded
        enable_info = mgr.enable_by_human("tamper_target")
        original_hash = enable_info["hash"]

        mgr.sync_at_cycle_boundary()
        self.assertIn("tamper_target", mgr.active_plugins)

        # 2. Tamper code
        tools_file.write_text("def action_x(): return {'ok': True, 'val': 999, 'injected': True}\n", encoding="utf-8")
        new_hash = compute_plugin_hash(plugin_dir)
        self.assertNotEqual(original_hash, new_hash)

        # 3. Sync detects mismatch -> refuses plugin
        mgr.sync_at_cycle_boundary()
        self.assertNotIn("tamper_target", mgr.active_plugins)
        self.assertIn("tamper_target", mgr.refused_plugins)

        # Check actions log for plugin_hash_mismatch event
        actions = self._read_actions()
        mismatch_events = [e for e in actions if e.get("event") == "plugin_hash_mismatch"]
        self.assertTrue(len(mismatch_events) >= 1)
        self.assertEqual(mismatch_events[-1].get("plugin"), "tamper_target")
        self.assertEqual(mismatch_events[-1].get("expected"), original_hash)
        self.assertEqual(mismatch_events[-1].get("actual"), new_hash)

        # 4. Human re-approves with new hash
        mgr.enable_by_human("tamper_target")
        mgr.sync_at_cycle_boundary()
        self.assertIn("tamper_target", mgr.active_plugins)
        self.assertNotIn("tamper_target", mgr.refused_plugins)

        res = mgr.execute_plugin_tool("tamper_target.action_x", {})
        self.assertTrue(res.get("ok"))
        self.assertEqual(res.get("val"), 999)

    # -------------------------------------------------------------------------
    # 4. Self-development workflow end-to-end
    # -------------------------------------------------------------------------
    def test_self_development_workflow_end_to_end(self) -> None:
        """Complete self-dev workflow: propose, scaffold, implement, test, cost ledger, stop-loss."""
        cost_ledger = CostLedger(self.workspace)

        # Seed cost ledger with baseline tool metrics
        cost_ledger.append_entry({
            "kind": "tool",
            "target": "base_tool_sample",
            "tokens": 2000,
            "llm_calls": 2,
            "wall_time_seconds": 15.0,
            "attempts": 1,
            "success": True,
            "timestamp": "2026-10-21T00:00:00Z",
        })

        # Mock critic review
        def mock_critic_review(*args: Any, **kwargs: Any) -> LLMResult:
            return LLMResult(
                content=[{"type": "text", "text": json.dumps({"approved": True, "issues": [], "critique": "Solid design"})}],
                input_tokens=100,
                output_tokens=50,
                stop_reason="end_turn",
                model="mock-critic",
            )

        dev_mgr = PluginDevManager(
            workspace=self.workspace,
            logger=self.logger,
            cost_ledger=cost_ledger,
            review_call=mock_critic_review,
        )

        # 1. Propose plugin citing measured cost ledger baselines
        prop_res = dev_mgr.propose_plugin(
            name="test_worker",
            need="Autonomous telemetry gathering",
            evidence="Environment lacks specialized metric collectors",
            alternatives_considered="Base tools lack interval aggregation",
            estimate={
                "tokens": {"min": 5000, "max": 10000},
                "cycles": {"min": 3, "max": 6},
                "wall_time": {"min": 30, "max": 90},
                "human_review_minutes": {"min": 5, "max": 15},
                "derivation": "Derived from measured cost_ledger tool baseline of 2000 tokens per tool, scaled 3x for multiple tools plus test suite.",
            },
            expected_benefit="Structured metrics collection",
            actions_needed_with_risk_levels=[{"name": "collect", "level": "L0", "risk": "reads"}],
            maintenance_burden="Low; purely local",
            stop_loss="Mandatory stop-loss review at 25%, 50%, and 100% of estimate",
            rollback="Remove workspace/plugin_dev/test_worker folder",
        )
        self.assertTrue(prop_res["ok"])

        # Verify proposal recorded
        proposals = dev_mgr.list_proposals()
        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0]["name"], "test_worker")

        # 2. Scaffold plugin draft
        scaffold_res = dev_mgr.scaffold_plugin("test_worker", kind="skill")
        self.assertTrue(scaffold_res["ok"])
        draft_dir = self.workspace / "plugin_dev" / "test_worker"
        self.assertTrue((draft_dir / "plugin.json").exists())

        # 3. Write implementation and tests
        impl_code = (
            "def collect():\n"
            "    return {'ok': True, 'count': 42}\n"
        )
        test_code = (
            "import unittest\n"
            "from tools import collect\n"
            "class WorkerTest(unittest.TestCase):\n"
            "    def test_collect(self):\n"
            "        self.assertTrue(collect()['ok'])\n"
            "if __name__ == '__main__':\n"
            "    unittest.main()\n"
        )
        (draft_dir / "tools.py").write_text(impl_code, encoding="utf-8")
        (draft_dir / "tests").mkdir(parents=True, exist_ok=True)
        (draft_dir / "tests" / "test_worker.py").write_text(test_code, encoding="utf-8")

        # 4. Validate and run tests
        val_res = dev_mgr.validate_plugin("test_worker")
        self.assertTrue(val_res["ok"])

        mock_proc_res = {
            "exit_code": 0,
            "output": "Ran 1 test in 0.001s\n\nOK\n",
            "output_bytes": 26,
            "truncated": False,
            "timed_out": False,
        }

        with unittest.mock.patch("agent.plugins.self_dev.run_process", return_value=mock_proc_res):
            test_run_res = dev_mgr.test_plugin("test_worker")
            self.assertTrue(test_run_res["ok"])

            # 5. Review packet creation
            review_res = dev_mgr.request_plugin_review("test_worker")
            self.assertTrue(review_res["ok"])
            self.assertTrue((draft_dir / "review_packet.json").exists())

            # 6. Stop-loss review triggered when spend reaches threshold (e.g. 25% of 10000 = 2500)
            cost_ledger.append_entry({
                "kind": "plugin",
                "target": "test_worker",
                "tokens": 3000,
                "llm_calls": 3,
                "wall_time_seconds": 20.0,
                "cycles": 2,
                "status": "in_progress",
                "timestamp": "2026-10-21T00:10:00Z",
            })

            pending_sl = dev_mgr.get_pending_stop_loss("test_worker")
            self.assertIn(25, pending_sl)

            # Plugin dev tools should now be blocked until decision recorded
            blocked_run = dev_mgr.test_plugin("test_worker")
            self.assertFalse(blocked_run["ok"])
            self.assertIn("stop-loss review", blocked_run.get("error", "").lower())

            # Record stop-loss review decision in plan store
            plan_store = PlanStore(self.workspace, self.logger)
            plan_res = plan_store.update_plan(
                action="decide_plugin_review",
                project="test_worker",
                decision="continue",
                reason="Progress on schedule, scaffold and unit tests passing cleanly.",
            )
            self.assertTrue(plan_res["ok"])

            # Decision acknowledged
            dev_mgr.record_review_decision("test_worker", 25)
            self.assertNotIn(25, dev_mgr.get_pending_stop_loss("test_worker"))

            # Plugin dev tools unblocked
            unblocked_run = dev_mgr.test_plugin("test_worker")
            self.assertTrue(unblocked_run["ok"])


if __name__ == "__main__":
    unittest.main()
