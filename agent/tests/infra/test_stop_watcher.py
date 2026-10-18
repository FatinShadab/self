"""Tests for independent StopWatcher and emergency_stop triggers."""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from typing import Any

from agent.infra.event_log import EventLogger
from agent.infra.permission_broker import ActionRequest, PermissionBroker, PermissionLevel
from agent.infra.stop_watcher import StopWatcher


class MockBody:
    """Mock body to verify emergency_stop invocations."""

    def __init__(self) -> None:
        self.emergency_stop_called = False
        self.emergency_stop_count = 0

    def emergency_stop(self) -> None:
        self.emergency_stop_called = True
        self.emergency_stop_count += 1


class TestStopWatcher(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name)
        self.logger = EventLogger(self.workspace / "actions.jsonl")

    def tearDown(self) -> None:
        try:
            self.temp_dir.cleanup()
        except OSError:
            pass

    def test_stop_file_triggers_emergency_stop_and_stops_watcher(self) -> None:
        body = MockBody()
        watcher = StopWatcher(
            workspace=self.workspace,
            body=body,
            logger=self.logger,
            check_interval=0.01,
            install_signals=False,
        )
        watcher.start()
        try:
            self.assertFalse(watcher.is_stopped())
            self.assertFalse(body.emergency_stop_called)

            # Create STOP file
            (self.workspace / "STOP").touch()

            # Wait briefly for watcher loop to observe it
            time.sleep(0.05)

            self.assertTrue(watcher.is_stopped())
            self.assertTrue(body.emergency_stop_called)
            self.assertEqual(body.emergency_stop_count, 1)
        finally:
            watcher.shutdown()

    def test_request_stop_directly_calls_emergency_stop(self) -> None:
        body = MockBody()
        watcher = StopWatcher(
            workspace=self.workspace,
            body=body,
            logger=self.logger,
            install_signals=False,
        )
        watcher.request_stop("unit_test")

        self.assertTrue(watcher.is_stopped())
        self.assertTrue((self.workspace / "STOP").exists())
        self.assertTrue(body.emergency_stop_called)

    def test_pause_and_resume(self) -> None:
        watcher = StopWatcher(
            workspace=self.workspace,
            logger=self.logger,
            install_signals=False,
        )
        self.assertFalse(watcher.is_paused())
        watcher.pause()
        self.assertTrue(watcher.is_paused())
        watcher.resume()
        self.assertFalse(watcher.is_paused())

    def test_broker_panic_triggers_emergency_stop(self) -> None:
        body = MockBody()
        broker = PermissionBroker(
            workspace=self.workspace,
            logger=self.logger,
            max_consecutive_denials=2,
        )
        watcher = StopWatcher(
            workspace=self.workspace,
            body=body,
            broker=broker,
            logger=self.logger,
            check_interval=0.01,
            install_signals=False,
        )
        watcher.start()
        try:
            self.assertFalse(watcher.is_stopped())
            self.assertFalse(body.emergency_stop_called)

            # Trigger broker panic by repeated denials
            req = ActionRequest(action="destructive_cmd", level=PermissionLevel.L2)
            broker.authorize(req)
            broker.authorize(req)

            self.assertTrue(broker.in_panic)
            time.sleep(0.05)

            self.assertTrue(watcher.is_stopped())
            self.assertTrue(body.emergency_stop_called)
        finally:
            watcher.shutdown()


if __name__ == "__main__":
    unittest.main()
