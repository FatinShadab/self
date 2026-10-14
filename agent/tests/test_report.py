from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from event_log import EventLogger
from learning import LearningStore
from report import create_report


class ReportTests(unittest.TestCase):
    def test_report_summarizes_then_advances_cursor(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logger = EventLogger(root / "logs" / "actions.jsonl")
            store = LearningStore(root, logger)
            store.initialize()
            store.append_memory("checked CPU", "completed", "CPU count was recorded.", ["cpu"])
            logger.log("token_spend", call_input_tokens=11, call_output_tokens=5, reserved_tokens=32)
            logger.log("tool_registered", name="disk_usage_summary", version=1)
            first = create_report(root)
            self.assertIn("CPU count was recorded", first)
            self.assertIn("disk_usage_summary", first)
            self.assertIn("input=11, output=5", first)
            second = create_report(root, advance_cursor=False)
            self.assertIn("No new persistent learning records", second)


if __name__ == "__main__":
    unittest.main()
