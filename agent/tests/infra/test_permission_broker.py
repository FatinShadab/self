"""Tests for the PermissionBroker and action governance."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from agent.infra.audit_trail import AuditTrail
from agent.infra.event_log import EventLogger
from agent.infra.permission_broker import (
    ActionRequest,
    ActionVerdict,
    PermissionBroker,
    PermissionLevel,
    PermissionPolicy,
    RateLimitConfig,
)
from agent.tools.base_tools import ToolRunner
from agent.tools.execution.authorization import offered_authorized_tools


class TestPermissionBroker(unittest.TestCase):
    def test_shipped_policy_grants_core_max_but_keeps_plugins_separate(self) -> None:
        policy_path = Path(__file__).resolve().parents[3] / "config" / "permissions.json"
        policy = PermissionPolicy(policy_path)
        self.assertEqual(policy.max_allowed_level("core", "update_plan"), PermissionLevel.L3)
        self.assertEqual(policy.max_allowed_level("core", "update_environment_map"), PermissionLevel.L3)
        self.assertEqual(policy.max_allowed_level("core", "create_tool"), PermissionLevel.L3)
        self.assertEqual(policy.max_allowed_level("body", "run_shell"), PermissionLevel.L2)
        self.assertEqual(policy.max_allowed_level("body", "write_file"), PermissionLevel.L2)
        self.assertEqual(policy.max_allowed_level("body", "read_file"), PermissionLevel.L0)
        self.assertEqual(policy.max_allowed_level("plugins.example", "example.action"), PermissionLevel.L0)
        broker = PermissionBroker(policy_path=policy_path, logger=self.logger)
        offered = offered_authorized_tools(
            [{"name": "run_shell"}, {"name": "write_file"}, {"name": "create_tool"}], broker
        )
        self.assertEqual([item["name"] for item in offered], ["run_shell", "write_file", "create_tool"])
        for action in ("run_shell", "write_file"):
            verdict = broker.authorize(ActionRequest(action=action, source="body", level=PermissionLevel.L2))
            self.assertTrue(verdict.allowed)

    def test_plugin_level_from_host_config_requires_enabled_pinned_entry(self) -> None:
        config_dir = self.workspace / "config"
        config_dir.mkdir()
        (config_dir / "permissions.json").write_text(
            json.dumps({"default_level": "L0", "grants": {"core": "L3"}}), encoding="utf-8"
        )
        plugin_config = config_dir / "plugins.json"
        plugin_config.write_text(json.dumps({"plugins": {
            "example": {"enabled": True, "hash": "a" * 64, "permission_level": "L2"},
            "unapproved": {"enabled": True, "permission_level": "L3"},
        }}), encoding="utf-8")
        policy = PermissionPolicy(config_dir / "permissions.json")
        self.assertEqual(policy.max_allowed_level("plugins.example", "example.action"), PermissionLevel.L2)
        self.assertEqual(policy.max_allowed_level("plugins.unapproved", "unapproved.action"), PermissionLevel.L0)
        self.assertEqual(policy.max_allowed_level("core", "create_tool"), PermissionLevel.L3)
        policy.set_plugin_grants_from_config({"plugins": {
            "example": {"enabled": True, "hash": "a" * 64, "permission_level": "L1"},
        }})
        self.assertEqual(policy.max_allowed_level("plugins.example", "example.action"), PermissionLevel.L1)
        policy.set_plugin_grants_from_config({"plugins": {
            "example": {"enabled": True, "hash": "a" * 64, "permission_level": "L3"},
        }})
        self.assertEqual(policy.max_allowed_level("plugins.example", "example.action"), PermissionLevel.L3)
        policy.set_plugin_grants_from_config({"plugins": {
            "example": {"enabled": False, "hash": "a" * 64, "permission_level": "L3"},
        }})
        self.assertEqual(policy.max_allowed_level("plugins.example", "example.action"), PermissionLevel.L0)

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name)
        self.logger = EventLogger(self.workspace / "actions.jsonl")
        self.audit = AuditTrail(self.workspace / "audit.jsonl", logger=self.logger)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_ungranted_tools_are_not_offered(self) -> None:
        policy_path = self.workspace / "l0-only.json"
        policy_path.write_text(json.dumps({"default_level": "L0"}), encoding="utf-8")
        broker = PermissionBroker(policy_path=policy_path, logger=self.logger)
        definitions = [
            {"name": "read_file"},
            {"name": "update_plan"},
            {"name": "update_environment_map"},
            {"name": "run_shell"},
        ]
        offered = offered_authorized_tools(definitions, broker)
        self.assertEqual([item["name"] for item in offered], ["read_file"])
        self.assertEqual(broker._consecutive_denials, 0)

        broker.policy.action_grants["core:update_plan"] = PermissionLevel.L1
        offered = offered_authorized_tools(definitions, broker)
        self.assertEqual([item["name"] for item in offered], ["read_file", "update_plan"])

    def test_denied_tool_is_not_counted_as_execution_failure(self) -> None:
        broker = PermissionBroker(workspace=self.workspace, logger=self.logger)
        runner = ToolRunner(self.logger, self.workspace, broker=broker)
        result = runner.execute("update_plan", {"action": "add", "goal": "Inspect"})
        self.assertTrue(result["permission_denied"])
        self.assertEqual(broker._consecutive_denials, 1)
        self.assertEqual(broker._consecutive_failures, 0)
        events = [json.loads(line)["event"] for line in self.logger.path.read_text().splitlines()]
        self.assertNotIn("action_executed", events)

    def test_default_policy_denies_above_l0(self) -> None:
        broker = PermissionBroker(logger=self.logger, audit_trail=self.audit)

        # L0 observe action should be allowed by default
        req_l0 = ActionRequest(
            action_id="act-1",
            actor="body:container",
            action_type="read_file",
            level=PermissionLevel.L0,
            target="/home/entity/file.txt",
        )
        verdict_l0 = broker.authorize(req_l0)
        self.assertTrue(verdict_l0.allowed)

        # L1 reversible change should be denied by default
        req_l1 = ActionRequest(
            action_id="act-2",
            actor="body:container",
            action_type="write_file",
            level=PermissionLevel.L1,
            target="/home/entity/file.txt",
        )
        verdict_l1 = broker.authorize(req_l1)
        self.assertFalse(verdict_l1.allowed)
        self.assertIn("denied", verdict_l1.reason.lower())

        # L2 destructive action should be denied by default
        req_l2 = ActionRequest(
            action_id="act-3",
            actor="body:container",
            action_type="delete_file",
            level=PermissionLevel.L2,
            target="/home/entity/file.txt",
        )
        verdict_l2 = broker.authorize(req_l2)
        self.assertFalse(verdict_l2.allowed)

        # L3 physical actuation should be denied by default
        req_l3 = ActionRequest(
            action_id="act-4",
            actor="body:hardware",
            action_type="motor_move",
            level=PermissionLevel.L3,
            target="servo_1",
        )
        verdict_l3 = broker.authorize(req_l3)
        self.assertFalse(verdict_l3.allowed)

    def test_human_policy_grants_l1_and_l2(self) -> None:
        policy_file = self.workspace / "permissions.json"
        policy_data = {
            "default_level": 0,
            "max_allowed_level": 2,
            "grants": [
                {
                    "actor": "body:container",
                    "action_types": ["write_file", "run_shell"],
                    "max_level": 2,
                }
            ],
            "rate_limits": {
                "write_file": {"max_actions": 5, "window_seconds": 60.0}
            },
        }
        policy_file.write_text(json.dumps(policy_data), encoding="utf-8")

        broker = PermissionBroker(policy_path=policy_file, logger=self.logger, audit_trail=self.audit)

        # write_file for body:container should now be allowed up to L2
        req = ActionRequest(
            action_id="act-write",
            actor="body:container",
            action_type="write_file",
            level=PermissionLevel.L1,
            target="/home/entity/test.txt",
        )
        verdict = broker.authorize(req)
        self.assertTrue(verdict.allowed)

        # But an ungranted actor or action type above L0 is still denied
        req_plugin = ActionRequest(
            action_id="act-plugin",
            actor="plugin:untrusted",
            action_type="write_file",
            level=PermissionLevel.L1,
            target="/home/entity/test.txt",
        )
        verdict_plugin = broker.authorize(req_plugin)
        self.assertFalse(verdict_plugin.allowed)

    def test_rate_limiting_limits_actions_not_tokens(self) -> None:
        policy_file = self.workspace / "permissions.json"
        policy_data = {
            "default_level": 0,
            "max_allowed_level": 2,
            "grants": [
                {
                    "actor": "tool_runner",
                    "action_types": ["run_shell"],
                    "max_level": 2,
                }
            ],
            "rate_limits": {
                "run_shell": {"max_actions": 2, "window_seconds": 10.0}
            },
        }
        policy_file.write_text(json.dumps(policy_data), encoding="utf-8")

        broker = PermissionBroker(policy_path=policy_file, logger=self.logger, audit_trail=self.audit)

        req1 = ActionRequest(
            action_id="shell-1", actor="tool_runner", action_type="run_shell",
            level=PermissionLevel.L2, target="ls",
        )
        req2 = ActionRequest(
            action_id="shell-2", actor="tool_runner", action_type="run_shell",
            level=PermissionLevel.L2, target="pwd",
        )
        req3 = ActionRequest(
            action_id="shell-3", actor="tool_runner", action_type="run_shell",
            level=PermissionLevel.L2, target="whoami",
        )

        v1 = broker.authorize(req1)
        broker.record_execution(req1, ok=True)
        v2 = broker.authorize(req2)
        broker.record_execution(req2, ok=True)
        v3 = broker.authorize(req3)

        self.assertTrue(v1.allowed)
        self.assertTrue(v2.allowed)
        self.assertFalse(v3.allowed)
        self.assertIn("rate limit exceeded", v3.reason.lower())

    def test_dry_run_mode(self) -> None:
        broker = PermissionBroker(logger=self.logger, audit_trail=self.audit, dry_run=True)

        req = ActionRequest(
            action_id="dry-1",
            actor="body:container",
            action_type="delete_all",
            level=PermissionLevel.L2,
            target="/",
        )
        verdict = broker.authorize(req)
        # In dry run mode, verdict is allowed with a dry-run explanation
        self.assertTrue(verdict.allowed)
        self.assertIn("dry run", verdict.reason.lower())

    def test_undo_hooks(self) -> None:
        broker = PermissionBroker(logger=self.logger, audit_trail=self.audit)

        undone = []
        def undo_action() -> None:
            undone.append("reverted")

        broker.register_undo_hook("act-undo-1", undo_action)
        success = broker.execute_undo("act-undo-1")

        self.assertTrue(success)
        self.assertEqual(undone, ["reverted"])

        # Second undo on same action returns False
        self.assertFalse(broker.execute_undo("act-undo-1"))

    def test_panic_triggered_on_repeated_denials(self) -> None:
        panic_reasons = []
        def on_panic(reason: str) -> None:
            panic_reasons.append(reason)

        broker = PermissionBroker(
            logger=self.logger,
            audit_trail=self.audit,
            max_consecutive_denials=3,
            on_panic=on_panic,
        )

        for i in range(3):
            req = ActionRequest(
                action_id=f"denied-{i}",
                actor="unknown",
                action_type="format_drive",
                level=PermissionLevel.L2,
                target="/dev/sda",
            )
            broker.authorize(req)

        self.assertTrue(broker.in_panic)
        self.assertEqual(len(panic_reasons), 1)
        self.assertIn("consecutive denials", panic_reasons[0])


if __name__ == "__main__":
    unittest.main()
