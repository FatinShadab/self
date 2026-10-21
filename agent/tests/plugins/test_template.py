"""Unit tests for the starter template skeleton (plugins/_template)."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agent.body.sim import SimBody
from agent.infra.event_log import EventLogger
from agent.plugins.cli import cmd_new, cmd_validate
from agent.plugins.manager import PluginManager, compute_plugin_hash


class PluginTemplateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp())
        self.workspace = self.temp_dir / "workspace"
        self.workspace.mkdir(parents=True)
        self.config_dir = self.temp_dir / "config"
        self.config_dir.mkdir(parents=True)
        self.logger = EventLogger(self.workspace / "logs" / "actions.jsonl")
        candidates = [
            Path(__file__).resolve().parents[3] / "plugins" / "_template",
            Path(__file__).resolve().parents[2] / "plugins" / "_template",
            Path("/opt/agent/plugins/_template"),
        ]
        self.template_dir = next((c for c in candidates if c.exists() and (c / "plugin.json").exists()), candidates[0])

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_template_skeleton_exists_and_contains_minimal_working_files(self) -> None:
        self.assertTrue(self.template_dir.exists(), "plugins/_template must exist at repo root")
        self.assertTrue((self.template_dir / "plugin.json").exists())
        self.assertTrue((self.template_dir / "plugin.py").exists())
        self.assertTrue((self.template_dir / "tests").is_dir())
        self.assertTrue((self.template_dir / "tests" / "test_plugin.py").exists())

    def test_template_not_discovered_or_loadable_from_template_location(self) -> None:
        # If template directory is copied into shipped or workspace directory with its original name
        shipped = self.temp_dir / "shipped"
        shipped.mkdir(parents=True)
        shutil.copytree(self.template_dir, shipped / "_template")

        ws_plugins = self.workspace / "plugins"
        ws_plugins.mkdir(parents=True)
        shutil.copytree(self.template_dir, ws_plugins / "_template")

        mgr = PluginManager(
            workspace=self.workspace,
            config_dir=self.config_dir,
            shipped_dir=shipped,
            logger=self.logger,
        )
        discovered = mgr.discover()
        self.assertNotIn("_template", discovered)

        # Hash computation also ignores _template
        root_hash_before = compute_plugin_hash(shipped / "_template")
        self.assertTrue(len(root_hash_before) == 64)

    def test_template_copied_under_another_name_loads_and_passes_tests(self) -> None:
        ws_plugins = self.workspace / "plugins"
        ws_plugins.mkdir(parents=True)

        # Scaffold via cmd_new
        code = cmd_new("my_sim_plugin", dest_dir=ws_plugins, template_dir=self.template_dir)
        self.assertEqual(code, 0)

        plugin_folder = ws_plugins / "my_sim_plugin"
        self.assertTrue(plugin_folder.exists())

        # 1. Passes static validation
        val_code = cmd_validate(plugin_folder)
        self.assertEqual(val_code, 0)

        # 2. Passes its own unit tests
        res = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", str(plugin_folder / "tests")],
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0, f"Template unit tests failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}")

        # 3. Loads cleanly in PluginManager
        mgr = PluginManager(
            workspace=self.workspace,
            config_dir=self.config_dir,
            shipped_dir=self.temp_dir / "empty_shipped",
            logger=self.logger,
        )
        mgr.enable_by_human("my_sim_plugin")
        mgr.sync_at_cycle_boundary()

        self.assertIn("my_sim_plugin", mgr.active_plugins)
        active = mgr.active_plugins["my_sim_plugin"]
        self.assertTrue(active.is_loaded)
        self.assertTrue(active.is_enabled)

        # Execute sample tool
        tool_out = mgr.execute_plugin_tool("my_sim_plugin.sample_tool", {"message": "Test ping"})
        self.assertTrue(tool_out.get("ok"))
        self.assertEqual(tool_out.get("echo"), "Test ping")

        # 4. Verifies integration with SimBody
        scenario = {
            "name": "plugin_template_scenario",
            "sensors": {
                "sim_sensor": {"eval_key": "ready"}
            },
            "actions": {
                "sim_action": {"permission_level": "L0", "risk_class": "reads"}
            },
        }
        body = SimBody(scenario=scenario, workspace=self.workspace)
        body.state["ready"] = True
        sensor_res = body.sense()
        self.assertTrue(sensor_res.get("sim_sensor"))
        action_res = body.act("sim_action")
        self.assertTrue(action_res.get("ok"))


if __name__ == "__main__":
    unittest.main()
