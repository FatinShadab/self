"""Unit tests verifying SHA-256 hash pinning, mismatch detection, and human re-approval."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from agent.infra.event_log import EventLogger
from agent.plugins.manager import PluginManager, compute_plugin_hash


class HashPinningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp())
        self.workspace = self.temp_dir / "workspace"
        self.workspace.mkdir(parents=True)
        self.config_dir = self.temp_dir / "config"
        self.config_dir.mkdir(parents=True)
        self.logger = EventLogger(self.workspace / "logs" / "actions.jsonl")

        self.manager = PluginManager(
            workspace=self.workspace,
            config_dir=self.config_dir,
            shipped_dir=self.temp_dir / "empty_shipped",
            logger=self.logger,
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_modify_enabled_plugin_causes_refusal_and_reapproval_restores(self) -> None:
        plugin_dir = self.workspace / "plugins" / "secure_plugin"
        plugin_dir.mkdir(parents=True)
        manifest = {
            "name": "secure_plugin",
            "version": "0.1.0",
            "core_api": "1.0.0",
            "kind": "skill",
            "description": "Secure plugin with hash verification",
            "tools": [{"name": "compute", "description": "compute"}],
            "sensors": [],
            "actions": [],
            "starting_goal_seeds": [],
            "embodiment": "Secure embodiment",
        }
        (plugin_dir / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
        tools_file = plugin_dir / "tools.py"
        tools_file.write_text("def compute(): return {'ok': True, 'v': 1}\n", encoding="utf-8")

        # 1. Enable plugin - records SHA-256 hash in config
        res = self.manager.enable_by_human("secure_plugin")
        initial_hash = res["hash"]
        self.assertEqual(initial_hash, compute_plugin_hash(plugin_dir))

        # Sync at cycle boundary loads it successfully
        self.manager.sync_at_cycle_boundary()
        self.assertIn("secure_plugin", self.manager.active_plugins)
        self.assertTrue(self.manager.active_plugins["secure_plugin"].is_enabled)

        # 2. Modify an enabled plugin file (simulating untrusted edit)
        tools_file.write_text("def compute(): return {'ok': True, 'v': 2, 'tampered': True}\n", encoding="utf-8")
        new_hash = compute_plugin_hash(plugin_dir)
        self.assertNotEqual(initial_hash, new_hash)

        # 3. Next sync at cycle boundary: recomputed hash differs!
        self.manager.sync_at_cycle_boundary()

        # Expect refusal: plugin is disabled and inactive
        self.assertNotIn("secure_plugin", self.manager.active_plugins)
        self.assertIn("secure_plugin", self.manager.refused_plugins)

        # Verify plugin_hash_mismatch was logged
        events = [
            json.loads(line)
            for line in (self.workspace / "logs" / "actions.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        mismatch_events = [
            e for e in events
            if e.get("event") == "plugin_hash_mismatch" and e.get("plugin") == "secure_plugin"
        ]
        self.assertTrue(len(mismatch_events) >= 1)
        self.assertEqual(mismatch_events[0]["expected"], initial_hash)
        self.assertEqual(mismatch_events[0]["actual"], new_hash)

        # Calling tool from refused plugin returns structured observation
        obs = self.manager.execute_plugin_tool("secure_plugin.compute", {})
        self.assertFalse(obs.get("ok"))
        self.assertIn("tool no longer available: plugin secure_plugin disabled", obs.get("error", ""))

        # Subsequent syncs still refuse to load it
        self.manager.sync_at_cycle_boundary()
        self.assertNotIn("secure_plugin", self.manager.active_plugins)

        # 4. Human re-approves plugin: updates hash in config
        reapprove_res = self.manager.enable_by_human("secure_plugin")
        self.assertEqual(reapprove_res["hash"], new_hash)

        # 5. Next cycle boundary: hash matches, plugin loads cleanly
        self.manager.sync_at_cycle_boundary()
        self.assertIn("secure_plugin", self.manager.active_plugins)
        self.assertTrue(self.manager.active_plugins["secure_plugin"].is_enabled)
        tool_res = self.manager.execute_plugin_tool("secure_plugin.compute", {})
        self.assertTrue(tool_res.get("ok"))
        self.assertEqual(tool_res.get("v"), 2)

    def test_runtime_state_directory_does_not_affect_plugin_hash(self) -> None:
        plugin_dir = self.workspace / "plugins" / "stateful_plugin"
        plugin_dir.mkdir(parents=True)
        manifest = {
            "name": "stateful_plugin",
            "version": "0.1.0",
            "core_api": "1.0.0",
            "kind": "skill",
            "description": "Stateful plugin",
            "tools": [{"name": "ping", "description": "ping"}],
            "sensors": [],
            "actions": [],
            "starting_goal_seeds": [],
            "embodiment": "Stateful embodiment",
        }
        (plugin_dir / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
        hash_before = compute_plugin_hash(plugin_dir)

        # Add state files inside state/
        state_dir = plugin_dir / "state"
        state_dir.mkdir(parents=True)
        (state_dir / "cache.json").write_text('{"cached": 123}', encoding="utf-8")

        hash_after = compute_plugin_hash(plugin_dir)
        self.assertEqual(hash_before, hash_after)
