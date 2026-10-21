"""Unit tests for Core API versioning, manifest compatibility ranges, and lifecycle."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from agent.infra.event_log import EventLogger
from agent.learning.plan import PlanStore
from agent.plugins import (
    CORE_API_VERSION,
    PluginManager,
    PluginManifestValidationError,
    compute_plugin_hash,
    is_core_api_compatible,
    parse_manifest,
)


class CoreApiVersionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp())
        self.workspace = self.temp_dir / "workspace"
        self.workspace.mkdir(parents=True)
        self.config_dir = self.temp_dir / "config"
        self.config_dir.mkdir(parents=True)
        self.logger = EventLogger(self.workspace / "logs" / "actions.jsonl")

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_version_file_matches_core_api_constant(self) -> None:
        candidates = [
            Path(__file__).resolve().parents[3] / "VERSION",
            Path(__file__).resolve().parents[2] / "VERSION",
            Path("/opt/agent/VERSION"),
        ]
        version_file = next((c for c in candidates if c.exists()), candidates[0])
        self.assertTrue(version_file.exists(), f"VERSION file must exist (checked {candidates})")
        file_version = version_file.read_text(encoding="utf-8").strip()
        self.assertEqual(CORE_API_VERSION, file_version)
        self.assertEqual(CORE_API_VERSION, "1.1.0")

    def test_range_syntax_compatibility(self) -> None:
        # Standard compound ranges
        self.assertTrue(is_core_api_compatible(">=1.0,<2.0", "1.0.0"))
        self.assertTrue(is_core_api_compatible(">=1.0.0,<2.0.0", "1.0.0"))
        self.assertTrue(is_core_api_compatible(">=1.0.0,<2.0.0", "1.5.2"))
        self.assertFalse(is_core_api_compatible(">=1.0.0,<2.0.0", "2.0.0"))
        self.assertFalse(is_core_api_compatible(">=1.0.0,<2.0.0", "0.9.9"))

        # Caret and tilde
        self.assertTrue(is_core_api_compatible("^1.0.0", "1.2.0"))
        self.assertFalse(is_core_api_compatible("^1.0.0", "2.0.0"))
        self.assertTrue(is_core_api_compatible("~1.0.0", "1.0.9"))
        self.assertFalse(is_core_api_compatible("~1.0.0", "1.1.0"))

        # Exact and equality
        self.assertTrue(is_core_api_compatible("1.0.0", "1.0.0"))
        self.assertTrue(is_core_api_compatible("==1.0.0", "1.0.0"))
        self.assertTrue(is_core_api_compatible("=1.0.0", "1.0.0"))
        self.assertFalse(is_core_api_compatible("1.0.0", "1.0.1"))

        # Wildcards
        self.assertTrue(is_core_api_compatible("*", "1.0.0"))
        self.assertTrue(is_core_api_compatible("any", "1.0.0"))

        # Empty / missing range must evaluate to False
        self.assertFalse(is_core_api_compatible("", "1.0.0"))
        self.assertFalse(is_core_api_compatible("   ", "1.0.0"))

    def test_missing_or_empty_core_api_in_manifest_raises_validation_error(self) -> None:
        manifest = {
            "name": "test_missing_api",
            "version": "1.0.0",
            "kind": "skill",
            "description": "Missing core_api field",
            "tools": [{"name": "tool_a"}],
            "sensors": [],
            "actions": [],
            "starting_goal_seeds": [],
            "embodiment": "I have skills.",
        }
        with self.assertRaises(PluginManifestValidationError) as ctx:
            parse_manifest(manifest)
        self.assertIn("core_api", str(ctx.exception).lower())

        # Empty string core_api
        manifest["core_api"] = ""
        with self.assertRaises(PluginManifestValidationError) as ctx:
            parse_manifest(manifest)
        self.assertIn("core_api", str(ctx.exception).lower())

    def test_incompatible_core_api_rejected_with_clear_message(self) -> None:
        manifest = {
            "name": "future_plugin",
            "version": "1.0.0",
            "core_api": ">=99.0.0",
            "kind": "skill",
            "description": "Requires future core",
            "tools": [{"name": "tool_a"}],
            "sensors": [],
            "actions": [],
            "starting_goal_seeds": [],
            "embodiment": "Future capabilities.",
        }
        with self.assertRaises(PluginManifestValidationError) as ctx:
            parse_manifest(manifest)
        msg = str(ctx.exception)
        self.assertIn("future_plugin", msg)
        self.assertIn(">=99.0.0", msg)
        self.assertIn(CORE_API_VERSION, msg)

    def test_enabled_plugin_becoming_incompatible_preserves_state_and_suspends_goals(self) -> None:
        # Create a workspace plugin
        plugin_dir = self.workspace / "plugins" / "legacy_sensor"
        plugin_dir.mkdir(parents=True)
        manifest = {
            "name": "legacy_sensor",
            "version": "1.0.0",
            "core_api": ">=1.0.0,<2.0.0",
            "kind": "skill",
            "description": "Sensor that will become incompatible",
            "tools": [{"name": "read_metric"}],
            "sensors": [],
            "actions": [],
            "starting_goal_seeds": ["Verify legacy sensor"],
            "embodiment": "I observe legacy sensor telemetry.",
        }
        (plugin_dir / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
        (plugin_dir / "tools.py").write_text("def read_metric(): return {'ok': True, 'm': 100}\n", encoding="utf-8")

        # Create private state inside plugin
        plugin_state_dir = self.workspace / "plugins" / "legacy_sensor" / "state"
        plugin_state_dir.mkdir(parents=True)
        state_file = plugin_state_dir / "historical_cache.json"
        state_file.write_text('{"cached_items": 42}', encoding="utf-8")

        mgr = PluginManager(
            workspace=self.workspace,
            config_dir=self.config_dir,
            shipped_dir=self.temp_dir / "empty_shipped",
            logger=self.logger,
        )

        plan_store = PlanStore(self.workspace, self.logger)
        plan_store.initialize()
        mgr.plan_store = plan_store

        # 1. Enable plugin
        mgr.enable_by_human("legacy_sensor")
        mgr.sync_at_cycle_boundary()
        self.assertIn("legacy_sensor", mgr.active_plugins)

        # Agent adds a goal tagged with this plugin
        plan_store.update_plan(
            action="add",
            reason="Observing legacy sensor",
            goal="Collect telemetry from legacy_sensor",
            plugin="legacy_sensor",
            source="plugin:legacy_sensor",
        )
        self.assertEqual(len(plan_store.items), 2)
        self.assertEqual(plan_store.items[1]["status"], "todo")

        # 2. Simulate core upgrade: plugin's core_api range excludes the new version
        manifest["core_api"] = "<1.0.0"  # Excludes current 1.0.0
        (plugin_dir / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")

        # 3. Next cycle boundary sync
        mgr.sync_at_cycle_boundary()

        # Incompatible plugin is NOT loaded
        self.assertNotIn("legacy_sensor", mgr.active_plugins)

        # Plan goals MUST stay suspended
        self.assertEqual(plan_store.items[1]["status"], "suspended: plugin disabled")

        # Plugin private state is strictly preserved; nothing was deleted
        self.assertTrue(state_file.exists())
        self.assertEqual(state_file.read_text(encoding="utf-8"), '{"cached_items": 42}')

        # plugin_load_failed must have been logged
        events = [
            json.loads(line)
            for line in (self.workspace / "logs" / "actions.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        failed_events = [e for e in events if e.get("event") == "plugin_load_failed" and e.get("plugin") == "legacy_sensor"]
        self.assertTrue(len(failed_events) >= 1)
        self.assertIn("incompatible with core version", failed_events[0].get("error", ""))

    def test_hello_demo_plugin_manifest_update_and_hash_pinning(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        hello_manifest = repo_root / "agent" / "plugins" / "hello" / "plugin.json"
        self.assertTrue(hello_manifest.exists())
        data = json.loads(hello_manifest.read_text(encoding="utf-8"))
        self.assertEqual(data["name"], "hello")
        # Manifest declares core_api compatible with 1.0.0
        self.assertTrue(is_core_api_compatible(data["core_api"], CORE_API_VERSION))

        # Copy hello to workspace to test hash mismatch and re-enable
        ws_hello = self.workspace / "plugins" / "hello"
        shutil.copytree(hello_manifest.parent, ws_hello)

        mgr = PluginManager(
            workspace=self.workspace,
            config_dir=self.config_dir,
            shipped_dir=self.temp_dir / "empty_shipped",
            logger=self.logger,
        )

        # 1. Human enables hello plugin -> pinned hash recorded
        res = mgr.enable_by_human("hello")
        pinned_hash = res["hash"]
        self.assertEqual(pinned_hash, compute_plugin_hash(ws_hello))

        mgr.sync_at_cycle_boundary()
        self.assertIn("hello", mgr.active_plugins)

        # 2. Modify manifest (simulating manifest edit)
        manifest_path = ws_hello / "plugin.json"
        manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest_data["description"] = "Updated description requiring re-pin"
        manifest_path.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")

        new_hash = compute_plugin_hash(ws_hello)
        self.assertNotEqual(pinned_hash, new_hash)

        # 3. Next cycle sync: hash mismatch refuses load
        mgr.sync_at_cycle_boundary()
        self.assertNotIn("hello", mgr.active_plugins)
        self.assertIn("hello", mgr.refused_plugins)

        # 4. Human re-enables / re-pins plugin
        re_pin = mgr.enable_by_human("hello")
        self.assertEqual(re_pin["hash"], new_hash)

        # 5. Next boundary sync: loads successfully
        mgr.sync_at_cycle_boundary()
        self.assertIn("hello", mgr.active_plugins)
        self.assertTrue(mgr.active_plugins["hello"].is_enabled)


if __name__ == "__main__":
    unittest.main()
