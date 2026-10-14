from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from event_log import EventLogger
from hardening import CapabilityRequests, DailyTokenLedger, RunCheckpoint
from report import create_report


class HardeningTests(unittest.TestCase):
    def test_capability_request_is_human_only_and_durable(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logger = EventLogger(root / "logs" / "actions.jsonl")
            result = CapabilityRequests(root, logger).request("credential", "Use a provider key", "Need supplementary inference", "example", ["EXAMPLE_API_KEY"], "https://example.test/key")
            text = (root / "state" / "capability_requests.md").read_text()
            self.assertFalse(result["ok"])
            self.assertIn("Human action required", text)
            self.assertIn("EXAMPLE_API_KEY", text)

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


if __name__ == "__main__":
    unittest.main()
