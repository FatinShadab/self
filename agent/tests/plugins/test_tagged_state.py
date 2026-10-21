"""Comprehensive acceptance tests for Prompt 14: Plugin-tagged state.

Covers:
1. Tags default to plugin=core, body=container for legacy/missing data.
2. Disable and re-enable round trip (plan, memory, map, tools, identity section).
3. Failed re-enable path (goals stay suspended, event logged).
4. Suspended goal exemptions: stale-item pruning, consolidation over max_items,
   boot-time pruning, and archive purging.
5. Removal with and without purge, ignoring _archive during discovery and hashing.
6. Zero-plugin prompt match with golden prompts.
7. Single-pass migration, byte-for-byte restore, and audit trail hash chain integrity.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any

from agent.body.container import ContainerBody
from agent.identity.identity import IdentityStore
from agent.infra.audit_trail import AuditTrail
from agent.infra.event_log import EventLogger
from agent.infra.migration import (
    deterministic_summary,
    restore_migration_p14,
    run_migration_p14,
    sha256_file,
)
from agent.learning.learning import LearningStore
from agent.learning.plan import (
    PlanStore,
    consolidate_plan_items,
    visible_plan_items,
)
from agent.plugins.manager import PluginManager, compute_plugin_hash
from agent.runtime.loop import (
    AgentConfig,
    AgentLoop,
    assemble_system_prompt,
    SYSTEM_PROMPT,
)
from agent.session.conversation import assemble_conversation_system_prompt
from agent.tools.base_tools import ToolRunner
from agent.tools.tool_registry import ToolRegistry


class ScriptedMockLLM:
    def __init__(self) -> None:
        self.call_history: list[dict[str, Any]] = []
        self.tokens_used = 0
        self.base_model = "mock-model"
        self.provider = "mock-provider"

    def call(self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]], max_tokens: int):
        from agent.llm.llm import LLMResult
        self.call_history.append({"system": system, "messages": messages, "tools": tools})
        return LLMResult(
            content=[{"type": "text", "text": "Cycle 1 report: all tasks complete."}],
            input_tokens=15,
            output_tokens=15,
            stop_reason="end_turn",
            model="mock-model",
        )


class TaggedStateAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp())
        self.workspace = self.temp_dir / "workspace"
        self.workspace.mkdir(parents=True)
        self.state_dir = self.workspace / "state"
        self.state_dir.mkdir(parents=True)
        self.config_dir = self.temp_dir / "config"
        self.config_dir.mkdir(parents=True)
        self.shipped_dir = self.temp_dir / "shipped"
        self.shipped_dir.mkdir(parents=True)
        self.logger = EventLogger(self.workspace / "logs" / "actions.jsonl")

        self.plugin_manager = PluginManager(
            workspace=self.workspace,
            config_dir=self.config_dir,
            shipped_dir=self.shipped_dir,
            logger=self.logger,
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_sample_plugin(self, name: str = "custom_sensor") -> Path:
        plugin_dir = self.workspace / "plugins" / name
        plugin_dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "name": name,
            "version": "1.0.0",
            "core_api": ">=1.0.0,<2.0.0",
            "kind": "skill",
            "description": "Custom sensor plugin for testing.",
            "tools": [
                {
                    "name": "read_temp",
                    "description": "Read ambient temperature sensor.",
                    "input_schema": {"type": "object", "properties": {}},
                }
            ],
            "sensors": [],
            "actions": [],
            "starting_goal_seeds": ["Calibrate custom sensor"],
            "embodiment": "Equipped with custom thermal and environment telemetry.",
            "identity_notes": ["I value calibrated sensor readings over unverified guesses."],
        }
        (plugin_dir / "plugin.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        (plugin_dir / "plugin.py").write_text(
            "def read_temp(**kwargs):\n    return {'ok': True, 'temp_c': 23.5}\n",
            encoding="utf-8",
        )
        return plugin_dir

    # -------------------------------------------------------------------------
    # Test 1: Disable and re-enable round trip across all state types
    # -------------------------------------------------------------------------
    def test_disable_and_reenable_round_trip(self) -> None:
        p_dir = self._create_sample_plugin("custom_sensor")
        self.plugin_manager.enable_by_human("custom_sensor")

        learning = LearningStore(self.workspace, self.logger)
        learning.initialize()
        plan_store = PlanStore(self.workspace, self.logger)
        plan_store.initialize()
        identity_store = IdentityStore(self.workspace, self.logger)
        identity_store.initialize()

        # Connect stores to plugin manager
        self.plugin_manager.plan_store = plan_store
        self.plugin_manager.learning_store = learning
        self.plugin_manager.sync_at_cycle_boundary()

        # 1. Tag state items with custom_sensor
        plan_store.update_plan(
            action="add",
            reason="Testing plugin tagging",
            goal="Calibrate custom sensor reading",
            plugin="custom_sensor",
            body="container",
            source="plugin:custom_sensor",
        )
        learning.append_memory(
            what_was_tried="Checked thermal sensor",
            outcome="completed",
            lesson="Temperature was stable at 23.5 C",
            tags=["sensor", "temp"],
            plugin="custom_sensor",
            body="container",
        )
        learning.update_map(
            [{"key": "ambient_temp", "value": 23.5, "confidence": "high", "evidence": "sensor reading"}],
            plugin="custom_sensor",
            body="container",
        )
        identity_store.set_plugin_embodiment("custom_sensor", "Sensor embodiment active.")

        # Verify active state while enabled
        active_plugins = set(self.plugin_manager.active_plugins.keys())
        self.assertIn("custom_sensor", active_plugins)
        self.assertIn("Calibrate custom sensor", plan_store.prompt_summary(active_plugins))
        self.assertIn("ambient_temp", learning.map_context(active_plugins))
        self.assertIn("Checked thermal sensor", learning.retrieve_memories("sensor", active_plugins=active_plugins))
        self.assertIn("[custom_sensor] Sensor embodiment active.", identity_store.prompt_context(active_plugins))

        # 2. Disable plugin at cycle boundary
        self.plugin_manager.disable_by_human("custom_sensor")
        self.plugin_manager.sync_at_cycle_boundary()

        # Verify state becomes inactive (excluded from retrieval & prompts, kept on disk)
        active_plugins_disabled = set(self.plugin_manager.active_plugins.keys())
        self.assertNotIn("custom_sensor", active_plugins_disabled)

        # Plan goal status is suspended
        suspended_items = [it for it in plan_store.items if it.get("plugin") == "custom_sensor"]
        self.assertEqual(len(suspended_items), 1)
        self.assertEqual(suspended_items[0]["status"], "suspended: plugin disabled")
        self.assertNotIn("Calibrate custom sensor", plan_store.prompt_summary(active_plugins_disabled))

        # Map and memory retrieval exclude disabled plugin facts
        self.assertNotIn("ambient_temp", learning.map_context(active_plugins_disabled))
        self.assertNotIn("Checked thermal sensor", learning.retrieve_memories("sensor", active_plugins=active_plugins_disabled))
        self.assertNotIn("Sensor embodiment active", identity_store.prompt_context(active_plugins_disabled))

        # They are kept on disk, never deleted
        raw_map = json.loads((self.state_dir / "map.json").read_text(encoding="utf-8"))
        self.assertIn("ambient_temp", raw_map["entries"])
        raw_mem = (self.state_dir / "memory.jsonl").read_text(encoding="utf-8")
        self.assertIn("custom_sensor", raw_mem)

        # 3. Successful Re-enable at cycle boundary
        self.plugin_manager.enable_by_human("custom_sensor")
        self.plugin_manager.sync_at_cycle_boundary()

        # Goals resume with note 're-verify: plugin was disabled'
        resumed_items = [it for it in plan_store.items if it.get("plugin") == "custom_sensor"]
        self.assertEqual(resumed_items[0]["status"], "todo")
        self.assertIn("re-verify: plugin was disabled", resumed_items[0]["why"])

        # Map facts from that body/plugin get confidence 'stale'
        re_map = json.loads((self.state_dir / "map.json").read_text(encoding="utf-8"))
        self.assertEqual(re_map["entries"]["ambient_temp"]["confidence"], "stale")

        # Inclusions return
        active_plugins_reenabled = set(self.plugin_manager.active_plugins.keys())
        self.assertIn("Calibrate custom sensor", plan_store.prompt_summary(active_plugins_reenabled))
        self.assertIn("ambient_temp", learning.map_context(active_plugins_reenabled))

    # -------------------------------------------------------------------------
    # Test 2: Failed re-enable path keeps goals suspended and logs event
    # -------------------------------------------------------------------------
    def test_failed_reenable_path_keeps_goals_suspended(self) -> None:
        p_dir = self._create_sample_plugin("broken_sensor")
        self.plugin_manager.enable_by_human("broken_sensor")

        plan_store = PlanStore(self.workspace, self.logger)
        plan_store.initialize()
        self.plugin_manager.plan_store = plan_store
        self.plugin_manager.sync_at_cycle_boundary()

        plan_store.update_plan(
            action="add",
            reason="Testing broken plugin",
            goal="Test broken plugin",
            plugin="broken_sensor",
            source="plugin:broken_sensor",
        )

        # Disable
        self.plugin_manager.disable_by_human("broken_sensor")
        self.plugin_manager.sync_at_cycle_boundary()
        self.assertEqual(plan_store.items[1]["status"], "suspended: plugin disabled")

        # Corrupt the plugin code so hash verification or load fails
        (p_dir / "plugin.py").write_text("SYNTAX ERROR def broken(: ;", encoding="utf-8")

        # Try to re-enable in config without updating hash or with corrupt code
        cfg = self.plugin_manager.read_config()
        cfg["plugins"]["broken_sensor"]["enabled"] = True
        self.plugin_manager.write_config(cfg)

        # Sync at cycle boundary
        self.plugin_manager.sync_at_cycle_boundary()

        # Goal MUST remain suspended
        self.assertEqual(plan_store.items[1]["status"], "suspended: plugin disabled")
        self.assertNotIn("broken_sensor", self.plugin_manager.active_plugins)

        # Check that hash mismatch or load failure event was logged
        log_text = (self.workspace / "logs" / "actions.jsonl").read_text(encoding="utf-8")
        self.assertTrue("plugin_hash_mismatch" in log_text or "plugin_load_failed" in log_text)

    # -------------------------------------------------------------------------
    # Test 3: Suspended goals exemptions (stale pruning, consolidation, boot, archive)
    # -------------------------------------------------------------------------
    def test_suspended_goals_exempt_from_all_pruning_and_purging_paths(self) -> None:
        plan_store = PlanStore(self.workspace, self.logger, max_items=4)
        plan_store.initialize()

        # Add an active goal, a suspended goal, and a completed goal
        plan_store.items = [
            {
                "id": "goal-1",
                "goal": "Normal active goal",
                "status": "todo",
                "priority": 2,
                "created_cycle": 1,
                "updated_cycle": 1,
                "plugin": "core",
                "body": "container",
            },
            {
                "id": "goal-2",
                "goal": "Plugin dependent goal",
                "status": "suspended: plugin disabled",
                "priority": 2,
                "created_cycle": 1,
                "updated_cycle": 1,
                "plugin": "custom_sensor",
                "body": "container",
            },
            {
                "id": "goal-3",
                "goal": "Finished goal",
                "status": "done",
                "priority": 2,
                "created_cycle": 1,
                "updated_cycle": 1,
                "plugin": "core",
                "body": "container",
            },
        ]
        plan_store._save_atomic(diff="Test setup", reason="setup")

        # Path 1: Archive purging
        # Completed goal-3 should be purged to plan_archive.jsonl, suspended goal-2 must remain in plan.json
        plan_store.hygiene(cycle=2)
        remaining_ids = [it["id"] for it in plan_store.items]
        self.assertIn("goal-2", remaining_ids)
        self.assertNotIn("goal-3", remaining_ids)
        archive_text = (self.state_dir / "plan_archive.jsonl").read_text(encoding="utf-8")
        self.assertIn("Finished goal", archive_text)
        self.assertNotIn("Plugin dependent goal", archive_text)

        # Path 2: Stale-item pruning
        # Stale cycle threshold is 5. Cycle 10 would mark normal items stale, but NOT suspended items.
        plan_store.hygiene(cycle=10, max_stale_cycles=5)
        goal_1 = [it for it in plan_store.items if it["id"] == "goal-1"][0]
        goal_2 = [it for it in plan_store.items if it["id"] == "goal-2"][0]
        self.assertEqual(goal_1["status"], "stale")
        self.assertEqual(goal_2["status"], "suspended: plugin disabled")

        # Path 3: Consolidation over max_items
        # Add goals exceeding max_items (4). Suspended items must be preserved intact without consolidation.
        for i in range(10):
            plan_store.items.append({
                "id": f"excess-{i}",
                "goal": f"Excess goal {i}",
                "status": "todo",
                "priority": 3,
                "created_cycle": 10,
                "updated_cycle": 10,
                "plugin": "core",
                "body": "container",
            })
        consolidated = consolidate_plan_items(plan_store.items, max_items=4)
        cons_ids = [it.get("id") for it in consolidated]
        self.assertIn("goal-2", cons_ids)

        # Path 4: Boot-time pruning (coordinator _recover_budget_blocked_plan)
        from agent.session.coordinator import WakeCoordinator

        class WakeFakeLLM:
            def call(self, **kwargs: Any) -> Any:
                return None

        coord = WakeCoordinator(self.workspace, llm_client=WakeFakeLLM())
        coord.plan = [
            {"step": "Review token budget limit for next run", "why": "Token limit", "status": "todo"},
            {"step": "Suspended plugin goal", "status": "suspended: plugin disabled"},
        ]
        coord._recover_budget_blocked_plan()
        coord_steps = [it.get("step") for it in coord.plan]
        self.assertIn("Suspended plugin goal", coord_steps)

    # -------------------------------------------------------------------------
    # Test 4: Removal with and without purge, ignoring _archive in discovery/hash
    # -------------------------------------------------------------------------
    def test_removal_with_and_without_purge(self) -> None:
        p_dir = self._create_sample_plugin("to_remove")
        self.plugin_manager.enable_by_human("to_remove")

        # 1. Removal without purge (default -> archives to workspace/plugins/_archive/<name>-<ts>/)
        ok = self.plugin_manager.remove_plugin("to_remove", purge=False)
        self.assertTrue(ok)
        self.assertFalse(p_dir.exists())

        archive_dir = self.workspace / "plugins" / "_archive"
        self.assertTrue(archive_dir.exists())
        archived_folders = list(archive_dir.iterdir())
        self.assertEqual(len(archived_folders), 1)
        self.assertTrue(archived_folders[0].name.startswith("to_remove-"))

        # Discovery MUST ignore _archive
        discovered = self.plugin_manager.discover()
        self.assertNotIn("_archive", discovered)
        self.assertNotIn("to_remove", discovered)

        # Hashing MUST ignore _archive
        p_dir2 = self._create_sample_plugin("active_p")
        # Put an _archive directory inside a plugin directory to test hashing exclusion
        (p_dir2 / "_archive").mkdir()
        (p_dir2 / "_archive" / "dummy.txt").write_text("archive data", encoding="utf-8")
        hash_with_archive = compute_plugin_hash(p_dir2)
        shutil.rmtree(p_dir2 / "_archive")
        hash_without_archive = compute_plugin_hash(p_dir2)
        self.assertEqual(hash_with_archive, hash_without_archive)

        # 2. Removal with purge and confirmation (permanently deletes, does not archive)
        p_dir3 = self._create_sample_plugin("to_purge")
        # Attempt without confirmation -> should default to archive, not purge
        archive_count_before = len(list(archive_dir.iterdir()))
        self.plugin_manager.remove_plugin("to_purge", purge=True, confirmed=False)
        self.assertEqual(len(list(archive_dir.iterdir())), archive_count_before + 1)

        # With confirmation -> purges
        p_dir4 = self._create_sample_plugin("to_purge_confirmed")
        archive_count_before = len(list(archive_dir.iterdir()))
        ok_purge = self.plugin_manager.remove_plugin("to_purge_confirmed", purge=True, confirmed=True)
        self.assertTrue(ok_purge)
        self.assertFalse(p_dir4.exists())
        self.assertEqual(len(list(archive_dir.iterdir())), archive_count_before)

    # -------------------------------------------------------------------------
    # Test 5: Zero-plugin golden prompt fidelity & legacy untagged data
    # -------------------------------------------------------------------------
    def test_zero_plugin_golden_prompts_and_legacy_untagged_data(self) -> None:
        container_body = ContainerBody()
        assembled_sys = assemble_system_prompt(container_body)
        assembled_conv = assemble_conversation_system_prompt(container_body)

        self.assertEqual(assembled_sys, SYSTEM_PROMPT)

        # Legacy untagged data handling
        learning = LearningStore(self.workspace, self.logger)
        learning.initialize()
        # Write legacy untagged memory line
        legacy_mem = {"timestamp": "2026-10-15T10:00:00Z", "what_was_tried": "Explored container", "outcome": "completed", "lesson": "Old lesson", "tags": ["old"]}
        (self.state_dir / "memory.jsonl").write_text(json.dumps(legacy_mem) + "\n", encoding="utf-8")

        # Retrieval treats missing tag as plugin=core, body=container
        res = learning.retrieve_memories("container")
        self.assertIn("Explored container", res)
        entries = learning.memory_entries()
        self.assertEqual(entries[0]["plugin"], "core")
        self.assertEqual(entries[0]["body"], "container")

        # Identity prompt context matches without active plugins
        id_store = IdentityStore(self.workspace, self.logger)
        id_store.initialize()
        prompt_ctx = id_store.prompt_context()
        self.assertIn("## Persistent identity", prompt_ctx)
        self.assertNotIn("## Active plugin embodiment", prompt_ctx)

    # -------------------------------------------------------------------------
    # Test 6: Single-pass migration, byte-for-byte restore, and audit hash chain
    # -------------------------------------------------------------------------
    def test_migration_and_byte_for_byte_restore_with_audit_trail_integrity(self) -> None:
        # Create legacy untagged files
        (self.state_dir / "memory.jsonl").write_text(
            json.dumps({"what_was_tried": "Legacy test", "outcome": "completed", "lesson": "A" * 1000, "tags": ["legacy"]}) + "\n",
            encoding="utf-8",
        )
        (self.state_dir / "map.json").write_text(
            json.dumps({"schema_version": 1, "entries": {"kernel": {"value": "Linux", "confidence": "high", "evidence": "uname"}}}),
            encoding="utf-8",
        )
        (self.state_dir / "plan.json").write_text(
            json.dumps({"schema_version": 1, "plan_version": 1, "items": [{"id": "goal-1", "goal": "Legacy goal", "status": "todo"}]}),
            encoding="utf-8",
        )
        (self.state_dir / "identity.json").write_text(
            json.dumps({"name": "SELF", "human_name": None, "name_context": None, "traits": [], "values": [], "voice": "calm", "interests": ["exploring"], "open_questions_about_self": []}),
            encoding="utf-8",
        )

        # Audit trail creation
        audit = AuditTrail(self.state_dir / "audit_trail.jsonl", self.logger)
        h1 = audit.append("action_allowed", action="read_file", level="L0_OBSERVE")
        h2 = audit.append("action_executed", action="read_file", level="L0_OBSERVE")

        # Verify audit chain before migration
        valid, count, msg = audit.verify()
        self.assertTrue(valid)
        self.assertEqual(count, 2)

        # Record pre-migration hashes
        orig_mem_hash = sha256_file(self.state_dir / "memory.jsonl")
        orig_map_hash = sha256_file(self.state_dir / "map.json")
        orig_plan_hash = sha256_file(self.state_dir / "plan.json")
        orig_id_hash = sha256_file(self.state_dir / "identity.json")
        orig_audit_hash = sha256_file(self.state_dir / "audit_trail.jsonl")

        # Run Migration
        migration_stats = run_migration_p14(self.workspace)
        backup_path = migration_stats["backup_path"]

        # Verify backup manifest existence and contents: only backup_manifest.json is written
        self.assertTrue((Path(backup_path) / "backup_manifest.json").exists())
        self.assertFalse((Path(backup_path) / "manifest.json").exists())

        # Verify migration results
        # 1. Audit trail was NEVER touched or rewritten!
        self.assertEqual(sha256_file(self.state_dir / "audit_trail.jsonl"), orig_audit_hash)
        valid, count, msg = audit.verify()
        self.assertTrue(valid)

        # 2. memory.jsonl lesson was bounded and report pointer added
        mem_after = json.loads((self.state_dir / "memory.jsonl").read_text(encoding="utf-8").strip())
        self.assertEqual(mem_after["plugin"], "core")
        self.assertEqual(mem_after["body"], "container")
        self.assertLessEqual(len(mem_after["lesson"]), 280)
        self.assertTrue(mem_after["report_path"].startswith("state/reports/"))
        report_file = self.workspace / mem_after["report_path"]
        self.assertTrue(report_file.exists())
        self.assertEqual(report_file.read_text(encoding="utf-8"), "A" * 1000)

        # 3. map.json has schema_version=2 and tags
        map_after = json.loads((self.state_dir / "map.json").read_text(encoding="utf-8"))
        self.assertEqual(map_after["schema_version"], 2)
        self.assertEqual(map_after["entries"]["kernel"]["plugin"], "core")

        # 3b. Test idempotency: consecutive migration run on already migrated state
        second_stats = run_migration_p14(self.workspace)
        mem_second = json.loads((self.state_dir / "memory.jsonl").read_text(encoding="utf-8").strip())
        self.assertEqual(mem_second["lesson"], mem_after["lesson"])
        self.assertEqual(mem_second["report_path"], mem_after["report_path"])

        # 4. Perform disable and re-enable, appending to audit trail
        audit.append("plugin_disabled", action="disable", level="L1_REVERSIBLE")
        audit.append("plugin_enabled", action="enable", level="L1_REVERSIBLE")
        valid, count, msg = audit.verify()
        self.assertTrue(valid)
        self.assertEqual(count, 4)

        # 5. Restore pre-migration files byte-for-byte
        restore_result = restore_migration_p14(self.workspace, backup_path)
        self.assertTrue(restore_result["verified"])

        # Check byte-for-byte identity against originals!
        self.assertEqual(sha256_file(self.state_dir / "memory.jsonl"), orig_mem_hash)
        self.assertEqual(sha256_file(self.state_dir / "map.json"), orig_map_hash)
        self.assertEqual(sha256_file(self.state_dir / "plan.json"), orig_plan_hash)
        self.assertEqual(sha256_file(self.state_dir / "identity.json"), orig_id_hash)

        # Audit trail still verifies
        valid, count, msg = audit.verify()
        self.assertTrue(valid)
