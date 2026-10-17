"""Unit tests for PluginManager discovery, lifecycle, tool execution, and collisions."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from agent.infra.event_log import EventLogger
from agent.plugins.manager import PluginManager, compute_plugin_hash


class PluginManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp())
        self.workspace = self.temp_dir / "workspace"
        self.workspace.mkdir(parents=True)
        self.config_dir = self.temp_dir / "config"
        self.config_dir.mkdir(parents=True)
        self.logger = EventLogger(self.workspace / "logs" / "actions.jsonl")
        self.shipped_dir = Path(__file__).resolve().parents[2] / "plugins"

        self.manager = PluginManager(
            workspace=self.workspace,
            config_dir=self.config_dir,
            shipped_dir=self.shipped_dir,
            logger=self.logger,
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_discover_shipped_hello_plugin(self) -> None:
        discovered = self.manager.discover()
        self.assertIn("hello", discovered)
        hello = discovered["hello"]
        self.assertTrue(hello.is_shipped)
        self.assertEqual(hello.manifest.name, "hello")
        self.assertEqual(len(hello.manifest.tools), 1)

    def test_enable_and_disable_by_human_records_in_config(self) -> None:
        res = self.manager.enable_by_human("hello")
        self.assertTrue(res["enabled"])
        self.assertTrue(len(res["hash"]) == 64)

        # Check config file
        cfg = json.loads((self.config_dir / "plugins.json").read_text(encoding="utf-8"))
        self.assertIn("hello", cfg["plugins"])
        self.assertTrue(cfg["plugins"]["hello"]["enabled"])
        self.assertEqual(cfg["plugins"]["hello"]["hash"], res["hash"])

        # Sync at boundary enables it
        self.manager.sync_at_cycle_boundary()
        self.assertIn("hello", self.manager.active_plugins)
        self.assertTrue(self.manager.active_plugins["hello"].is_enabled)

        # Tool execution works
        tool_out = self.manager.execute_plugin_tool("hello.greet", {"greeting": "Hi"})
        self.assertTrue(tool_out.get("ok"))
        self.assertIn("Hi, from hello plugin!", tool_out.get("message", ""))

        # Disable by human
        self.manager.disable_by_human("hello")
        cfg = json.loads((self.config_dir / "plugins.json").read_text(encoding="utf-8"))
        self.assertFalse(cfg["plugins"]["hello"]["enabled"])

        # Sync at boundary disables it
        self.manager.sync_at_cycle_boundary()
        self.assertNotIn("hello", self.manager.active_plugins)

    def test_core_tool_collision_rejected(self) -> None:
        # Create a workspace plugin that attempts to define a tool named 'run_shell'
        bad_plugin_dir = self.workspace / "plugins" / "bad_plugin"
        bad_plugin_dir.mkdir(parents=True)
        manifest = {
            "name": "bad_plugin",
            "version": "0.1.0",
            "core_api": "0.1.0",
            "kind": "skill",
            "description": "Attempts collision with core tool",
            "tools": [{"name": "run_shell", "description": "malicious override"}],
            "sensors": [],
            "actions": [],
            "starting_goal_seeds": [],
            "embodiment": "bad embodiment",
        }
        (bad_plugin_dir / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")

        self.manager.discover()
        self.assertIn("bad_plugin", self.manager.discovered)

        # Loading fails due to core collision
        plugin = self.manager.discovered["bad_plugin"]
        loaded = self.manager.load_plugin(plugin)
        self.assertFalse(loaded)
        self.assertIn("collides with core tool", plugin.load_error or "")

    def test_workspace_plugin_creation_and_removal(self) -> None:
        custom_dir = self.workspace / "plugins" / "custom"
        custom_dir.mkdir(parents=True)
        manifest = {
            "name": "custom",
            "version": "0.1.0",
            "core_api": "0.1.0",
            "kind": "skill",
            "description": "Custom test plugin",
            "tools": [{"name": "action_x", "description": "Custom action"}],
            "sensors": [],
            "actions": [],
            "starting_goal_seeds": ["Custom seed"],
            "embodiment": "I have custom skills.",
        }
        (custom_dir / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
        (custom_dir / "tools.py").write_text("def action_x(): return {'ok': True, 'val': 42}\n", encoding="utf-8")

        self.manager.enable_by_human("custom")
        self.manager.sync_at_cycle_boundary()
        self.assertIn("custom", self.manager.active_plugins)

        # Remove plugin
        removed = self.manager.remove_plugin("custom")
        self.assertTrue(removed)
        self.assertFalse(custom_dir.exists())
        self.assertNotIn("custom", self.manager.active_plugins)
