"""Unit tests verifying that crashing plugins never bring down the core."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from agent.infra.event_log import EventLogger
from agent.plugins.manager import PluginManager


class CrashingPluginTests(unittest.TestCase):
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

    def test_syntax_error_in_plugin_code_logs_plugin_load_failed(self) -> None:
        plugin_dir = self.workspace / "plugins" / "broken_syntax"
        plugin_dir.mkdir(parents=True)
        manifest = {
            "name": "broken_syntax",
            "version": "0.1.0",
            "core_api": ">=1.0.0,<2.0.0",
            "kind": "skill",
            "description": "Broken syntax plugin",
            "tools": [{"name": "broken_tool", "description": "broken"}],
            "sensors": [],
            "actions": [],
            "starting_goal_seeds": [],
            "embodiment": "Broken embodiment",
        }
        (plugin_dir / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
        # Write invalid Python syntax
        (plugin_dir / "plugin.py").write_text("def broken(: syntax error here!\n", encoding="utf-8")

        self.manager.discover()
        self.assertIn("broken_syntax", self.manager.discovered)

        # Attempt to load
        plugin = self.manager.discovered["broken_syntax"]
        loaded = self.manager.load_plugin(plugin)
        self.assertFalse(loaded)
        self.assertIsNotNone(plugin.load_error)

        # Check actions.jsonl for plugin_load_failed event
        events = [
            json.loads(line)
            for line in (self.workspace / "logs" / "actions.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        fail_events = [e for e in events if e.get("event") == "plugin_load_failed"]
        self.assertTrue(len(fail_events) >= 1)
        self.assertEqual(fail_events[0]["plugin"], "broken_syntax")

    def test_on_enable_crash_logs_plugin_load_failed_and_does_not_enable(self) -> None:
        plugin_dir = self.workspace / "plugins" / "crashing_enable"
        plugin_dir.mkdir(parents=True)
        manifest = {
            "name": "crashing_enable",
            "version": "0.1.0",
            "core_api": ">=1.0.0,<2.0.0",
            "kind": "skill",
            "description": "Crashing on_enable plugin",
            "tools": [{"name": "noop", "description": "noop"}],
            "sensors": [],
            "actions": [],
            "starting_goal_seeds": [],
            "embodiment": "Crashing on_enable embodiment",
        }
        (plugin_dir / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
        (plugin_dir / "plugin.py").write_text(
            "def on_enable(ctx):\n    raise RuntimeError('Explosion inside on_enable!')\n",
            encoding="utf-8",
        )

        self.manager.enable_by_human("crashing_enable")
        # Sync at cycle boundary catches the crash
        self.manager.sync_at_cycle_boundary()

        # Plugin was NOT enabled
        self.assertNotIn("crashing_enable", self.manager.active_plugins)

        # plugin_load_failed was logged
        events = [
            json.loads(line)
            for line in (self.workspace / "logs" / "actions.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        fail_events = [e for e in events if e.get("event") == "plugin_load_failed" and e.get("plugin") == "crashing_enable"]
        self.assertTrue(len(fail_events) >= 1)
        self.assertIn("Explosion inside on_enable", fail_events[0]["error"])

    def test_crashing_tool_handler_returns_safe_error_dict(self) -> None:
        plugin_dir = self.workspace / "plugins" / "crashing_tool"
        plugin_dir.mkdir(parents=True)
        manifest = {
            "name": "crashing_tool",
            "version": "0.1.0",
            "core_api": ">=1.0.0,<2.0.0",
            "kind": "skill",
            "description": "Plugin with crashing tool",
            "tools": [{"name": "fail_now", "description": "always fails"}],
            "sensors": [],
            "actions": [],
            "starting_goal_seeds": [],
            "embodiment": "Crashing tool embodiment",
        }
        (plugin_dir / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
        (plugin_dir / "tools.py").write_text(
            "def fail_now(**kwargs):\n    raise ZeroDivisionError('Division by zero in tool handler')\n",
            encoding="utf-8",
        )

        self.manager.enable_by_human("crashing_tool")
        self.manager.sync_at_cycle_boundary()
        self.assertIn("crashing_tool", self.manager.active_plugins)

        # Executing the crashing tool returns structured error, does not raise
        result = self.manager.execute_plugin_tool("crashing_tool.fail_now", {})
        self.assertFalse(result.get("ok"))
        self.assertIn("Division by zero", result.get("error", ""))
