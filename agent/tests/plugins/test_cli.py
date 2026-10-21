"""Unit tests for the Plugin SDK Command-Line Interface (agent.plugins)."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from agent.plugins.cli import (
    cmd_check,
    cmd_list,
    cmd_new,
    cmd_validate,
    main,
)
from agent.plugins.manifest import CORE_API_VERSION


class PluginCLITests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp())
        self.workspace = self.temp_dir / "workspace"
        self.workspace.mkdir(parents=True)
        self.config_dir = self.temp_dir / "config"
        self.config_dir.mkdir(parents=True)
        template_candidates = [
            Path(__file__).resolve().parents[3] / "plugins" / "_template",
            Path(__file__).resolve().parents[2] / "plugins" / "_template",
            Path("/opt/agent/plugins/_template"),
        ]
        self.template_dir = next((c for c in template_candidates if c.exists() and (c / "plugin.json").exists()), template_candidates[0])

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_new_scaffolds_plugin_and_updates_manifest(self) -> None:
        dest = self.workspace / "plugins"
        dest.mkdir(parents=True)

        exit_code = cmd_new(
            name="awesome_plugin",
            dest_dir=dest,
            template_dir=self.template_dir,
        )
        self.assertEqual(exit_code, 0)

        plugin_folder = dest / "awesome_plugin"
        self.assertTrue(plugin_folder.exists())
        self.assertTrue((plugin_folder / "plugin.json").exists())
        self.assertTrue((plugin_folder / "plugin.py").exists())
        self.assertTrue((plugin_folder / "tests" / "test_plugin.py").exists())

        # Check manifest customization
        manifest = json.loads((plugin_folder / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["name"], "awesome_plugin")
        self.assertIn("awesome_plugin", manifest["embodiment"])

    def test_new_refuses_overwrite(self) -> None:
        dest = self.workspace / "plugins"
        dest.mkdir(parents=True)
        (dest / "existing_plugin").mkdir(parents=True)

        stderr_buf = StringIO()
        with patch("sys.stderr", stderr_buf):
            exit_code = cmd_new(
                name="existing_plugin",
                dest_dir=dest,
                template_dir=self.template_dir,
            )
        self.assertEqual(exit_code, 1)
        self.assertIn("already exists", stderr_buf.getvalue())

    def test_new_validates_name_constraints(self) -> None:
        invalid_names = [
            "",
            "bad name spaces",
            "_leading_underscore",
            ".leading_dot",
            "special$char!",
            "template",
            "core",
            "archive",
        ]
        for bad_name in invalid_names:
            stderr_buf = StringIO()
            with patch("sys.stderr", stderr_buf):
                exit_code = cmd_new(
                    name=bad_name,
                    dest_dir=self.workspace / "plugins",
                    template_dir=self.template_dir,
                )
            self.assertEqual(exit_code, 1, f"Expected {bad_name!r} to be rejected")

    def test_validate_static_success_and_json_output(self) -> None:
        # Scaffold a valid plugin
        dest = self.workspace / "plugins"
        dest.mkdir(parents=True)
        cmd_new("valid_tool", dest_dir=dest, template_dir=self.template_dir)
        plugin_path = dest / "valid_tool"

        # Validate with text output
        stdout_buf = StringIO()
        with patch("sys.stdout", stdout_buf):
            code = cmd_validate(plugin_path, output_json=False)
        self.assertEqual(code, 0)
        self.assertIn("PASS:", stdout_buf.getvalue())

        # Validate with JSON output
        stdout_buf = StringIO()
        with patch("sys.stdout", stdout_buf):
            code = cmd_validate(plugin_path, output_json=True)
        self.assertEqual(code, 0)
        data = json.loads(stdout_buf.getvalue())
        self.assertTrue(data["valid"])
        self.assertEqual(data["plugin"], "valid_tool")
        self.assertEqual(data["errors"], [])

    def test_validate_never_executes_or_imports_plugin_code(self) -> None:
        """Verify validate is purely static and never imports plugin code."""
        dest = self.workspace / "plugins"
        dest.mkdir(parents=True)
        cmd_new("syntax_error_plugin", dest_dir=dest, template_dir=self.template_dir)
        plugin_path = dest / "syntax_error_plugin"

        # Write invalid Python syntax into plugin.py
        (plugin_path / "plugin.py").write_text("INVALID PYTHON SYNTAX def broken(: ; {{{", encoding="utf-8")

        # Static validation only checks schema and file presence; it must NOT crash on syntax error
        stdout_buf = StringIO()
        with patch("sys.stdout", stdout_buf):
            code = cmd_validate(plugin_path, output_json=True)
        self.assertEqual(code, 0)
        data = json.loads(stdout_buf.getvalue())
        self.assertTrue(data["valid"])

    def test_validate_catches_schema_collisions_and_missing_tests(self) -> None:
        plugin_path = self.workspace / "plugins" / "broken_plugin"
        plugin_path.mkdir(parents=True)

        # 1. Missing fields
        manifest = {
            "name": "broken_plugin",
            "version": "1.0.0",
            # missing core_api
            "kind": "skill",
            "description": "desc",
            "tools": [{"name": "run_shell"}],  # core collision!
            "sensors": [],
            "actions": [],
            "starting_goal_seeds": [],
            "embodiment": "emb",
        }
        (plugin_path / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")

        stdout_buf = StringIO()
        with patch("sys.stdout", stdout_buf):
            code = cmd_validate(plugin_path, output_json=True)
        self.assertEqual(code, 1)
        data = json.loads(stdout_buf.getvalue())
        self.assertFalse(data["valid"])
        errors_text = " ".join(data["errors"])
        self.assertIn("core_api", errors_text)
        self.assertIn("collides with reserved core tool", errors_text)
        self.assertIn("tests folder missing", errors_text)

    def test_list_and_check_ignore_template_and_archive(self) -> None:
        ws_plugins = self.workspace / "plugins"
        ws_plugins.mkdir(parents=True)

        # Create a valid plugin, a _template, and an _archive
        cmd_new("active_plugin", dest_dir=ws_plugins, template_dir=self.template_dir)
        (ws_plugins / "_template").mkdir(parents=True)
        (ws_plugins / "_template" / "plugin.json").write_text('{"name": "_template"}', encoding="utf-8")
        (ws_plugins / "_archive").mkdir(parents=True)
        (ws_plugins / "_archive" / "old_plugin").mkdir(parents=True)
        (ws_plugins / "_archive" / "old_plugin" / "plugin.json").write_text('{"name": "old_plugin"}', encoding="utf-8")

        # 1. Test list --json
        stdout_buf = StringIO()
        with patch("sys.stdout", stdout_buf):
            code = cmd_list(
                workspace_dir=self.workspace,
                config_dir=self.config_dir,
                shipped_dir=self.temp_dir / "empty_shipped",
                output_json=True,
            )
        self.assertEqual(code, 0)
        listed = json.loads(stdout_buf.getvalue())
        listed_names = {item["name"] for item in listed}
        self.assertIn("active_plugin", listed_names)
        self.assertNotIn("_template", listed_names)
        self.assertNotIn("old_plugin", listed_names)

        # 2. Test check --json
        stdout_buf = StringIO()
        with patch("sys.stdout", stdout_buf):
            code = cmd_check(
                workspace_dir=self.workspace,
                shipped_dir=self.temp_dir / "empty_shipped",
                output_json=True,
                current_api="1.0.0",
            )
        self.assertEqual(code, 0)
        checked = json.loads(stdout_buf.getvalue())
        self.assertTrue(checked["all_compatible"])
        checked_names = {p["name"] for p in checked["plugins"]}
        self.assertIn("active_plugin", checked_names)
        self.assertNotIn("_template", checked_names)
        self.assertNotIn("old_plugin", checked_names)

    def test_check_returns_exit_1_on_incompatible_plugin(self) -> None:
        ws_plugins = self.workspace / "plugins"
        ws_plugins.mkdir(parents=True)
        cmd_new("incompatible_plugin", dest_dir=ws_plugins, template_dir=self.template_dir)

        # Modify core_api to be incompatible with 1.0.0
        m_file = ws_plugins / "incompatible_plugin" / "plugin.json"
        data = json.loads(m_file.read_text(encoding="utf-8"))
        data["core_api"] = ">=2.0.0"
        m_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

        stdout_buf = StringIO()
        with patch("sys.stdout", stdout_buf):
            code = cmd_check(
                workspace_dir=self.workspace,
                shipped_dir=self.temp_dir / "empty_shipped",
                output_json=True,
                current_api="1.0.0",
            )
        self.assertEqual(code, 1)
        checked = json.loads(stdout_buf.getvalue())
        self.assertFalse(checked["all_compatible"])

    def test_main_cli_entrypoint_dispatch(self) -> None:
        # Test CLI main parser directly
        dest = self.workspace / "plugins"
        dest.mkdir(parents=True)

        # 1. new
        code = main(["new", "cli_test_plugin", "--dest", str(dest), "--template", str(self.template_dir)])
        self.assertEqual(code, 0)

        # 2. validate
        code = main(["validate", str(dest / "cli_test_plugin"), "--json"])
        self.assertEqual(code, 0)

        # 3. list
        code = main(["list", "--workspace", str(self.workspace), "--config", str(self.config_dir), "--json"])
        self.assertEqual(code, 0)

        # 4. check
        code = main(["check", "--workspace", str(self.workspace), "--json"])
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
