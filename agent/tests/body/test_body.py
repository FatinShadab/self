"""Unit tests for agent.body package and ContainerBody implementation."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.body.base import Body, BodyDescription, Capability
from agent.body.container import ContainerBody, ContainerMetrics
from agent.infra.event_log import EventLogger
from agent.tools.base_tools import ToolRunner


class TestBodyInterfaceAndContainerBody(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name)
        self.logger = EventLogger(self.workspace / "events.jsonl")
        self.body = ContainerBody(
            workspace=self.workspace,
            logger=self.logger,
            core_root=self.workspace / "core",
            agent_root=self.workspace / "agent",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_describe_returns_valid_description(self) -> None:
        desc = self.body.describe()
        self.assertIsInstance(desc, BodyDescription)
        self.assertIn("Linux container", desc.embodiment_text)
        self.assertIn("expected Linux container", desc.embodiment_clause)
        self.assertTrue(len(desc.default_interests) >= 3)
        self.assertIn("You have not been told where you run", desc.initial_orientation_task)
        self.assertEqual(self.body.initial_orientation_task(), desc.initial_orientation_task)

    def test_capabilities_schema_and_types(self) -> None:
        caps = self.body.capabilities()
        self.assertTrue(len(caps) >= 6)
        names = {cap.name for cap in caps}
        expected = {"run_shell", "read_file", "write_file", "list_dir", "http_get", "probe_local_ollama"}
        self.assertTrue(expected.issubset(names))
        for cap in caps:
            self.assertIsInstance(cap, Capability)
            self.assertTrue(cap.risk_class in {"executes", "reads", "writes", "network"})
            d = cap.to_dict()
            self.assertEqual(d["name"], cap.name)
            self.assertEqual(d["risk_class"], cap.risk_class)

    def test_sense_metrics_and_uptime(self) -> None:
        telemetry = self.body.sense()
        self.assertIsInstance(telemetry, dict)
        self.assertIn("uptime", telemetry)
        self.assertIn("metrics", telemetry)
        self.assertIn("orientation_changes", telemetry)
        metrics = telemetry["metrics"]
        self.assertIn("cpu", metrics)
        self.assertIn("ram", metrics)
        self.assertIn("disk", metrics)

    def test_health_check(self) -> None:
        status = self.body.health()
        self.assertIsInstance(status, dict)
        self.assertTrue(status.get("ok"))
        self.assertEqual(status.get("status"), "healthy")
        self.assertIn("uptime_seconds", status)


    def test_emergency_stop_creates_stop_file(self) -> None:
        self.assertFalse((self.workspace / "STOP").exists())
        self.body.emergency_stop()
        self.assertTrue((self.workspace / "STOP").exists())

    def test_act_file_operations(self) -> None:
        test_file = str(self.workspace / "test.txt")
        # Write file via act
        write_res = self.body.act("write_file", path=test_file, content="hello world")
        self.assertTrue(write_res.get("ok"))
        self.assertTrue((self.workspace / "test.txt").exists())

        # Read file via act
        read_res = self.body.act("read_file", path=test_file)
        self.assertTrue(read_res.get("ok"))
        self.assertEqual(read_res.get("content"), "hello world")

        # List dir via act
        list_res = self.body.act("list_dir", path=str(self.workspace))
        self.assertTrue(list_res.get("ok"))
        entries = [e["name"] for e in list_res.get("entries", [])]
        self.assertIn("test.txt", entries)

    @patch("agent.body.container.run_process")
    def test_act_shell_execution(self, mock_run_process: unittest.mock.MagicMock) -> None:
        mock_run_process.return_value = {"exit_code": 0, "output": "body test output", "timed_out": False, "ok": True}
        res = self.body.act("run_shell", cmd="echo 'body test'")
        self.assertIsInstance(res, dict)
        self.assertTrue(res.get("ok"))
        self.assertIn("body test output", res.get("output", ""))
        mock_run_process.assert_called_once()

    def test_tool_runner_delegates_to_body(self) -> None:
        runner = ToolRunner(self.logger, self.workspace, body=self.body)
        self.assertEqual(runner.body, self.body)

        del_file = str(self.workspace / "delegated.txt")
        # Write file via ToolRunner.execute
        write_res = runner.execute("write_file", {"path": del_file, "content": "via tool runner"})
        self.assertTrue(write_res.get("ok"))
        self.assertTrue((self.workspace / "delegated.txt").exists())

        # Read file via ToolRunner.execute
        read_res = runner.execute("read_file", {"path": del_file})
        self.assertTrue(read_res.get("ok"))
        self.assertEqual(read_res.get("content"), "via tool runner")


if __name__ == "__main__":
    unittest.main()
