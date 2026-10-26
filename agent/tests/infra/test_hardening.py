"""SELF test hardening module."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from agent.infra.event_log import EventLogger
from agent.infra.hardening import (
    CapabilityRequests,
    DailyTokenLedger,
    RunCheckpoint,
    decline_pending_capability_request,
    get_harness_request_path,
)
from agent.reporting.report import create_report


class HardeningTests(unittest.TestCase):
    def test_capability_request_is_human_only_and_durable(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logger = EventLogger(root / "logs" / "actions.jsonl")
            cap = CapabilityRequests(root, logger)
            result = cap.request("credential", "Use a provider key", "Need supplementary inference", "example", ["EXAMPLE_API_KEY"], "https://example.test/key")
            text = (root / "state" / "capability_requests.md").read_text()
            self.assertFalse(result["ok"])
            self.assertIn("Human action required", text)
            self.assertIn("EXAMPLE_API_KEY", text)

            # Decline capability and verify locks cleared and repeat prevented
            record = decline_pending_capability_request(root, reason="Host key restricted", logger=logger)
            self.assertIsNotNone(record)
            self.assertFalse((root / "HUMAN_REQUEST.md").exists())
            self.assertFalse(get_harness_request_path(root).exists())

            # Verify declined capability deduplication does not re-halt
            repeat_res = cap.request("credential", "Use a provider key", "Need supplementary inference", "example", ["EXAMPLE_API_KEY"], "https://example.test/key")
            self.assertFalse(repeat_res["ok"])
            self.assertFalse(repeat_res["halted"])
            self.assertEqual(repeat_res["status"], "previously_declined")

            # Verify stalled task report generation and plan demotion
            from agent.runtime.task_reporter import write_human_report
            from agent.learning.plan import PlanStore
            report_file = write_human_report(
                workspace=root,
                goal="Build custom docker inspector",
                tool_name="create_tool",
                error_details="Permission denied on /var/run/docker.sock",
                why_explanation="Cannot reach docker daemon socket in container",
                next_goal="Explore filesystem",
                logger=logger,
            )
            self.assertTrue(report_file.exists())
            report_content = report_file.read_text(encoding="utf-8")
            self.assertIn("Stalled Task Report", report_content)
            self.assertIn("Build custom docker inspector", report_content)
            self.assertIn("Explore filesystem", report_content)

            # Verify plan demote_stalled_goal
            plan = PlanStore(root, logger)
            plan.update_plan(action="add", goal="Task A", priority=1, reason="First task")
            plan.update_plan(action="add", goal="Task B", priority=2, reason="Second task")
            self.assertEqual(plan.top_items()[0]["goal"], "Task A")

            plan.demote_stalled_goal("Task A", reason="Failed 3 times")
            top = plan.top_items()
            self.assertEqual(top[0]["goal"], "Task B")
            stalled_item = [it for it in plan.items if it["goal"] == "Task A"][0]
            self.assertEqual(stalled_item["status"], "blocked")
            self.assertEqual(stalled_item["priority"], 3)

    def test_daily_budget_reservation_and_settlement(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logger = EventLogger(root / "logs" / "actions.jsonl")
            ledger = DailyTokenLedger(root, logger, cap=10)
            self.assertTrue(ledger.reserve(7))
            self.assertFalse(ledger.reserve(4))
            ledger.settle(7, 5)
            self.assertTrue(ledger.reserve(5))
            state = json.loads((root / "state" / "daily_token_budget.json").read_text())
            self.assertEqual(state["used_tokens"], 5)

    def test_network_events_write_egress_and_report_daily_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logger = EventLogger(root / "logs" / "actions.jsonl")
            logger.log("network_request", method="GET", host="example.test", path="/a")
            logger.log("network_request", method="POST", host="example.test", path="/b")
            egress = (root / "state" / "egress.jsonl").read_text().splitlines()
            self.assertEqual(len(egress), 2)
            report = create_report(root, advance_cursor=False)
            self.assertIn("example.test: 2", report)
            self.assertIn("Today's egress", report)

    def test_checkpoint_uses_atomic_latest_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logger = EventLogger(root / "logs" / "actions.jsonl")
            checkpoint = RunCheckpoint(root, logger)
            checkpoint.save(status="running", task="resume me", cycle=4)
            self.assertEqual(checkpoint.load()["cycle"], 4)

    def test_daily_token_ledger_write_handles_permission_error_with_retry(self) -> None:
        """Verify _write retries os.replace upon transient PermissionError (e.g. Windows file lock)."""
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logger = EventLogger(root / "logs" / "actions.jsonl")
            ledger = DailyTokenLedger(root, logger, cap=100)

            # 1. Transient failure recovers on retry
            call_count = 0
            real_replace = os.replace

            def mock_replace(src, dst):
                nonlocal call_count
                call_count += 1
                if call_count < 3:
                    raise PermissionError("[WinError 5] Access is denied")
                return real_replace(src, dst)

            with patch("os.replace", side_effect=mock_replace):
                ledger._write({"date": "2026-10-25", "used_tokens": 10, "cap": 100})

            self.assertEqual(call_count, 3)
            written = json.loads((root / "state" / "daily_token_budget.json").read_text(encoding="utf-8"))
            self.assertEqual(written["used_tokens"], 10)

            # 2. Permanent failure raises after exhausting 5 retries
            call_count_fail = 0

            def mock_replace_always_fail(src, dst):
                nonlocal call_count_fail
                call_count_fail += 1
                raise PermissionError("[WinError 5] Access is denied")

            with patch("os.replace", side_effect=mock_replace_always_fail):
                with self.assertRaises(PermissionError):
                    ledger._write({"date": "2026-10-25", "used_tokens": 20, "cap": 100})
            self.assertEqual(call_count_fail, 5)


if __name__ == "__main__":
    unittest.main()
