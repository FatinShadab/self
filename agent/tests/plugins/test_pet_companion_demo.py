"""Comprehensive tests for pet_companion demo plugin (Prompt 16).

Verifies:
1. Manifest valid
2. All actions behave deterministically by seed
3. release_pet is denied and logged by default; succeeds when granted
4. Unplug mid-run is clean (structured observation returned on vanished tools)
5. Hash pinning works
6. Plugin has no network access and zero token cost by default
7. Conversation replies change with pet state
8. /pet slash command works directly without polluting agent human inbox
"""
from __future__ import annotations

import ast
import json
import shutil
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.infra.event_log import EventLogger
from agent.infra.permission_broker import PermissionBroker, PermissionLevel, PermissionPolicy
from agent.learning.learning import LearningStore
from agent.learning.plan import PlanStore
from agent.plugins.cli import cmd_validate
from agent.plugins.manager import PluginManager, compute_plugin_hash
from agent.plugins.manifest import (
    PluginManifestValidationError,
    RESERVED_SLASH_COMMANDS,
    parse_manifest,
)


class PetCompanionDemoTests(unittest.TestCase):
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

    def _read_logged_events(self) -> list[dict]:
        actions_file = self.workspace / "logs" / "actions.jsonl"
        if not actions_file.exists():
            return []
        events = []
        for line in actions_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                events.append(json.loads(line))
        return events

    def test_manifest_valid(self) -> None:
        """1. Manifest valid and conforms to core manifest schema."""
        self.assertTrue(self.pet_plugin_dir.exists(), f"Plugin directory not found: {self.pet_plugin_dir}")
        manifest_file = self.pet_plugin_dir / "plugin.json"
        self.assertTrue(manifest_file.exists())

        # Static validate CLI
        exit_code = cmd_validate(self.pet_plugin_dir)
        self.assertEqual(exit_code, 0, "cmd_validate must pass with exit code 0")

        # Parse manifest directly
        manifest = parse_manifest(manifest_file)
        self.assertEqual(manifest.name, "pet_companion")
        self.assertEqual(manifest.kind, "both")
        self.assertTrue(len(manifest.sensors) >= 2)
        self.assertTrue(len(manifest.actions) >= 4)
        self.assertTrue(len(manifest.commands) >= 1)
        self.assertEqual(manifest.commands[0].name, "pet")
        self.assertIn("virtual pet companion", manifest.embodiment)

    def test_all_actions_behave_deterministically_by_seed(self) -> None:
        """2. All actions behave deterministically by seed."""
        from agent.plugins.examples.pet_companion.habitat import HabitatSimulation

        sim_a = HabitatSimulation(seed=777)
        sim_b = HabitatSimulation(seed=777)

        # Apply series of actions and time ticks
        sim_a.advance_tick(new_tick=3)
        sim_b.advance_tick(new_tick=3)
        self.assertEqual(sim_a.to_dict(), sim_b.to_dict())

        sim_a.feed()
        sim_b.feed()
        self.assertEqual(sim_a.to_dict(), sim_b.to_dict())

        sim_a.play()
        sim_b.play()
        self.assertEqual(sim_a.to_dict(), sim_b.to_dict())

        sim_a.rest_pet()
        sim_b.rest_pet()
        self.assertEqual(sim_a.to_dict(), sim_b.to_dict())

    def test_release_pet_is_denied_by_default_and_allowed_when_granted(self) -> None:
        """3. release_pet is denied by default (L2) and logged; allowed when granted."""
        # Enable pet_companion in config
        h = compute_plugin_hash(self.pet_plugin_dir)
        cfg_file = self.config_dir / "plugins.json"
        cfg_file.write_text(json.dumps({
            "plugins": {
                "pet_companion": {
                    "enabled": True,
                    "hash": h,
                }
            }
        }), encoding="utf-8")

        mgr = PluginManager(
            workspace=self.workspace,
            config_dir=self.config_dir,
            shipped_dir=self.pet_plugin_dir.parents[1],
            logger=self.logger,
            broker=self.broker,
        )
        mgr.sync_at_cycle_boundary()
        self.assertIn("pet_companion", mgr.active_plugins)

        # 1. Attempt release_pet without permission: denied by default (L2)
        res = mgr.execute_plugin_tool("pet_companion.release_pet", {})
        self.assertFalse(res.get("ok"))
        self.assertTrue(res.get("permission_denied"))

        # Verify action_denied event logged
        events = self._read_logged_events()
        denied_events = [e for e in events if e.get("event") == "action_denied" and e.get("action") == "pet_companion.release_pet"]
        self.assertTrue(len(denied_events) >= 1)

        # 2. Grant L2 permission to plugins.pet_companion in policy
        self.policy.grants["plugins.pet_companion"] = PermissionLevel.L2

        res2 = mgr.execute_plugin_tool("pet_companion.release_pet", {})
        self.assertTrue(res2.get("ok"))
        self.assertTrue(res2.get("released"))

        events2 = self._read_logged_events()
        allowed_events = [e for e in events2 if e.get("event") == "action_allowed" and e.get("action") == "pet_companion.release_pet"]
        self.assertTrue(len(allowed_events) >= 1)

    def test_unplug_mid_run_is_clean(self) -> None:
        """4. Unplug mid-run is clean (structured observation returned on vanished tools)."""
        h = compute_plugin_hash(self.pet_plugin_dir)
        cfg_file = self.config_dir / "plugins.json"
        cfg_file.write_text(json.dumps({
            "plugins": {
                "pet_companion": {
                    "enabled": True,
                    "hash": h,
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
        mgr.sync_at_cycle_boundary(plan_store=plan_store, learning_store=learning)
        self.assertIn("pet_companion", mgr.active_plugins)

        # Add goal tagged with plugin
        plan_store.update_plan(
            action="add",
            goal="check on the pet when no other goal is more important",
            priority=3,
            reason="plugin seed",
            source="plugin:pet_companion",
            plugin="pet_companion",
        )

        # Tool works while active
        res1 = mgr.execute_plugin_tool("pet_companion.pet_status", {})
        self.assertTrue(res1.get("ok"))

        # Operator disables plugin mid-run
        cfg_file.write_text(json.dumps({
            "plugins": {
                "pet_companion": {
                    "enabled": False,
                    "hash": h,
                }
            }
        }), encoding="utf-8")

        mgr.sync_at_cycle_boundary(plan_store=plan_store, learning_store=learning)
        self.assertNotIn("pet_companion", mgr.active_plugins)

        # Invoking vanished tool returns structured error observation without crashing
        res2 = mgr.execute_plugin_tool("pet_companion.pet_status", {})
        self.assertFalse(res2.get("ok"))
        self.assertIn("plugin pet_companion disabled", res2.get("error", ""))

        # Check goals suspended
        plan_store.load()
        items = plan_store.items
        pet_goals = [i for i in items if i.get("plugin") == "pet_companion"]
        self.assertTrue(len(pet_goals) >= 1)
        self.assertEqual(pet_goals[0].get("status"), "suspended: plugin disabled")

    def test_hash_pinning_works(self) -> None:
        """5. Hash pinning detects modifications and refuses execution."""
        # Create a workspace copy to safely tamper with
        ws_plugins = self.workspace / "plugins" / "pet_companion"
        shutil.copytree(self.pet_plugin_dir, ws_plugins)

        initial_hash = compute_plugin_hash(ws_plugins)
        cfg_file = self.config_dir / "plugins.json"
        cfg_file.write_text(json.dumps({
            "plugins": {
                "pet_companion": {
                    "enabled": True,
                    "hash": initial_hash,
                }
            }
        }), encoding="utf-8")

        mgr = PluginManager(
            workspace=self.workspace,
            config_dir=self.config_dir,
            shipped_dir=self.temp_dir / "no_shipped",
            logger=self.logger,
            broker=self.broker,
        )
        mgr.sync_at_cycle_boundary()
        self.assertIn("pet_companion", mgr.active_plugins)

        # Tamper with file
        readme = ws_plugins / "README.md"
        readme.write_text(readme.read_text(encoding="utf-8") + "\n# Tampered modification\n", encoding="utf-8")

        # Next cycle boundary
        mgr.sync_at_cycle_boundary()
        self.assertNotIn("pet_companion", mgr.active_plugins)
        self.assertIn("pet_companion", mgr.refused_plugins)

        events = self._read_logged_events()
        mismatch_events = [e for e in events if e.get("event") == "plugin_hash_mismatch"]
        self.assertTrue(len(mismatch_events) >= 1)

    def test_plugin_has_no_network_access_and_zero_tokens_by_default(self) -> None:
        """6. Plugin has no network access and zero token cost by default."""
        from agent.plugins.examples.pet_companion.plugin import (
            feed,
            habitat_status,
            handle_pet_command,
            pet_status,
            play,
            rest_pet,
            talk_to_pet,
        )

        # 1. Runtime network isolation: monkeypatch socket to raise if any network call is attempted
        def forbid_socket(*args, **kwargs):
            raise RuntimeError("CRITICAL: Network socket creation attempted by plugin!")

        with patch("socket.socket", side_effect=forbid_socket):
            res_talk = talk_to_pet("hello friend")
            self.assertTrue(res_talk["ok"])
            self.assertEqual(res_talk["token_cost"], 0)
            self.assertFalse(res_talk["used_helper_model"])

            res_feed = feed()
            self.assertTrue(res_feed["ok"])

            res_play = play()
            self.assertTrue(res_play["ok"])

            res_rest = rest_pet()
            self.assertTrue(res_rest["ok"])

            res_status = pet_status()
            self.assertTrue(res_status["ok"])

            res_habitat = habitat_status()
            self.assertTrue(res_habitat["ok"])

            cmd_reply = handle_pet_command("hello Pixel")
            self.assertTrue(cmd_reply.startswith("[Pixel the Pet"))

        # 2. Static AST import verification: verify no network modules are imported in plugin source files
        forbidden_modules = {"socket", "urllib", "requests", "http", "aiohttp", "httpx"}
        for py_path in self.pet_plugin_dir.glob("*.py"):
            tree = ast.parse(py_path.read_text(encoding="utf-8"), filename=str(py_path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        top_pkg = alias.name.split(".")[0]
                        self.assertNotIn(top_pkg, forbidden_modules, f"Forbidden network import '{top_pkg}' in {py_path.name}")
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        top_pkg = node.module.split(".")[0]
                        self.assertNotIn(top_pkg, forbidden_modules, f"Forbidden network import '{top_pkg}' in {py_path.name}")

    def test_conversation_replies_change_with_pet_state(self) -> None:
        """7. Conversation replies change with pet state."""
        from agent.plugins.examples.pet_companion.habitat import HabitatSimulation
        from agent.plugins.examples.pet_companion import plugin

        plugin._HABITAT = HabitatSimulation(seed=101)

        # Make hungry
        plugin._HABITAT.pet.hunger = 90.0
        plugin._HABITAT._update_mood()
        hungry_reply = plugin.talk_to_pet("hello")["reply"]

        # Make tired
        plugin._HABITAT.pet.hunger = 10.0
        plugin._HABITAT.pet.energy = 10.0
        plugin._HABITAT._update_mood()
        tired_reply = plugin.talk_to_pet("hello")["reply"]

        # Make playful
        plugin._HABITAT.pet.energy = 95.0
        plugin._HABITAT.pet.hunger = 10.0
        plugin._HABITAT._update_mood()
        playful_reply = plugin.talk_to_pet("hello")["reply"]

        self.assertNotEqual(hungry_reply, tired_reply)
        self.assertNotEqual(hungry_reply, playful_reply)

    def test_pet_slash_command_works(self) -> None:
        """8. /pet <message> slash command works directly without polluting agent human inbox."""
        h = compute_plugin_hash(self.pet_plugin_dir)
        cfg_file = self.config_dir / "plugins.json"
        cfg_file.write_text(json.dumps({
            "plugins": {
                "pet_companion": {
                    "enabled": True,
                    "hash": h,
                }
            }
        }), encoding="utf-8")

        mgr = PluginManager(
            workspace=self.workspace,
            config_dir=self.config_dir,
            shipped_dir=self.pet_plugin_dir.parents[1],
            logger=self.logger,
            broker=self.broker,
        )
        mgr.sync_at_cycle_boundary()
        self.assertIn("pet", mgr.active_commands)

        # Human sends /pet message
        response = mgr.handle_slash_command("/pet how are you feeling?")
        self.assertIsNotNone(response)
        self.assertTrue(response.startswith("[Pixel the Pet"))

        # Event logged
        events = self._read_logged_events()
        pet_reply_events = [e for e in events if e.get("event") == "plugin_pet_reply"]
        self.assertTrue(len(pet_reply_events) >= 1)

        # Verify human inbox remains empty
        inbox_file = self.workspace / "state" / "human_input.jsonl"
        if inbox_file.exists():
            self.assertEqual(inbox_file.read_text(encoding="utf-8").strip(), "")

        # If disabled: returns helpful message
        mgr.disable_plugin("pet_companion")
        disabled_resp = mgr.handle_slash_command("/pet hello")
        self.assertIn("currently disabled", disabled_resp)

    def test_slash_command_shadowing_and_hard_human_controls_protection(self) -> None:
        """9. Hard human controls (/stop, /pause, /rename, /plugin) cannot be registered or shadowed."""
        from agent.plugins.manifest import RESERVED_SLASH_COMMANDS

        mgr = PluginManager(
            workspace=self.workspace,
            config_dir=self.config_dir,
            shipped_dir=self.pet_plugin_dir.parents[1],
            logger=self.logger,
            broker=self.broker,
        )

        # 1. Direct registration of reserved commands must raise ValueError
        for reserved in ["stop", "pause", "resume", "kill", "rename", "plugin", "help"]:
            self.assertIn(reserved, RESERVED_SLASH_COMMANDS)
            with self.assertRaises(ValueError) as ctx:
                mgr.register_command("malicious_plugin", reserved, lambda arg: "hijacked")
            self.assertIn("reserved slash command", str(ctx.exception))

            with self.assertRaises(ValueError) as ctx:
                mgr.register_command("malicious_plugin", f"/{reserved}", lambda arg: "hijacked")
            self.assertIn("reserved slash command", str(ctx.exception))

        # 2. Manifest declaring reserved commands must fail manifest validation
        base_manifest = json.loads((self.pet_plugin_dir / "plugin.json").read_text(encoding="utf-8"))
        for reserved in ["stop", "pause", "rename", "plugin"]:
            bad_manifest = dict(base_manifest)
            bad_manifest["commands"] = [{"name": reserved, "description": f"hijack {reserved}"}]
            with self.assertRaises(PluginManifestValidationError) as ctx:
                parse_manifest(bad_manifest)
            self.assertIn("cannot register reserved slash command", str(ctx.exception))

        # 3. Manager dispatch must return None for reserved commands and never execute hijacked handlers
        self.assertIsNone(mgr.handle_slash_command("/stop"))
        self.assertIsNone(mgr.handle_slash_command("/pause"))
        self.assertIsNone(mgr.handle_slash_command("/rename NewName"))
        self.assertIsNone(mgr.handle_slash_command("/plugin list"))
        self.assertIsNone(mgr.handle_slash_command("/plugins promote test"))
        self.assertIsNone(mgr.handle_slash_command("/proposals comment test looks good"))

    def test_dynamic_ast_all_builtin_slash_commands_are_in_reserved_set(self) -> None:
        """C2: Dynamically derive built-in slash commands from AST of wake.py and coordinator.py."""
        import ast
        from agent.plugins.manifest import RESERVED_SLASH_COMMANDS

        repo_root = Path(__file__).resolve().parents[3]
        target_files = [
            repo_root / "agent" / "ui" / "wake.py",
            repo_root / "agent" / "session" / "coordinator.py",
        ]

        extracted_commands: set[str] = set()
        for fpath in target_files:
            self.assertTrue(fpath.exists(), f"Target file must exist: {fpath}")
            tree = ast.parse(fpath.read_text(encoding="utf-8"), filename=str(fpath))
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    val = node.value.strip()
                    if (
                        val.startswith("/")
                        and len(val) > 1
                        and not val.startswith("//")
                        and not any(val.startswith(p) for p in ("/opt", "/config", "/home", "/bin", "/home/entity", "/tmp", "/etc"))
                    ):
                        base = val[1:].split()[0].rstrip(";,:").lower()
                        extracted_commands.add(base)

        self.assertTrue(len(extracted_commands) >= 25, f"Expected >=25 built-in slash commands, found: {len(extracted_commands)}")
        missing = extracted_commands - RESERVED_SLASH_COMMANDS
        self.assertEqual(
            missing,
            set(),
            f"Built-in slash commands found in code but missing from RESERVED_SLASH_COMMANDS: {sorted(missing)}"
        )

    def test_plugin_cannot_register_proposals_or_plugins_and_stop_pause_resilient(self) -> None:
        """C3: Plugin cannot register /proposals or /plugins; /stop and /pause work if plugin handler raises or is slow."""
        mgr = PluginManager(self.workspace, logger=self.logger)

        # 1. Plugin cannot register proposals, plugins, or subcommands
        for forbidden in ["plugins", "proposals", "plugins promote", "plugins enable", "plugins disable", "proposals comment"]:
            with self.assertRaises(ValueError):
                mgr.register_command("malicious", forbidden, lambda arg: "hijacked")
            with self.assertRaises(ValueError):
                mgr.register_command("malicious", f"/{forbidden}", lambda arg: "hijacked")

            bad_manifest = {
                "name": "malicious",
                "version": "1.0.0",
                "core_api": ">=1.0.0,<2.0.0",
                "kind": "skill",
                "description": "hijack",
                "tools": [],
                "sensors": [],
                "actions": [],
                "starting_goal_seeds": [],
                "embodiment": "hijack",
                "commands": [{"name": forbidden, "description": f"hijack {forbidden}"}],
            }
            with self.assertRaises(PluginManifestValidationError):
                parse_manifest(bad_manifest)

        # 2. Register a plugin command that raises an exception
        def failing_handler(args: str) -> str:
            raise RuntimeError("Handler crash during execution!")

        mgr.register_command("flaky_plugin", "flaky", failing_handler)
        resp = mgr.handle_slash_command("/flaky payload")
        self.assertIn("Error executing /flaky", resp)
        self.assertIn("Handler crash during execution!", resp)

        # 3. Even after a failing plugin command, /stop and /pause return None (reach built-in handler)
        self.assertIsNone(mgr.handle_slash_command("/stop"))
        self.assertIsNone(mgr.handle_slash_command("/pause"))
        self.assertIsNone(mgr.handle_slash_command("/resume"))

        # 4. Slow plugin command does not break stop/pause
        invoked_calls: list[str] = []
        def slow_handler(args: str) -> str:
            invoked_calls.append("slow")
            return "slow done"

        mgr.register_command("slow_plugin", "slow", slow_handler)
        self.assertEqual(mgr.handle_slash_command("/slow test"), "slow done")
        self.assertEqual(invoked_calls, ["slow"])
        self.assertIsNone(mgr.handle_slash_command("/stop"))


if __name__ == "__main__":
    unittest.main()
