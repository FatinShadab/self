"""SELF test process runner module."""
import sys
import tempfile
import unittest
from pathlib import Path

from agent.infra.process_runner import run_process


class ProcessRunnerTests(unittest.TestCase):
    def test_streams_output_and_reports_completion(self):
        with tempfile.TemporaryDirectory() as temp:
            chunks = []
            completed = []
            result = run_process(
                [sys.executable, "-c", "print('first'); print('second')"],
                cwd=Path(temp), timeout=5, cap=2_000,
                on_output=chunks.append, on_complete=completed.append,
            )
        self.assertEqual(result["exit_code"], 0)
        self.assertIn("first", "".join(chunks))
        self.assertEqual(completed[0]["exit_code"], 0)

    def test_output_cap_and_timeout_remain_bounded(self):
        with tempfile.TemporaryDirectory() as temp:
            result = run_process(
                [sys.executable, "-c", "import time; print('x' * 5000); time.sleep(10)"],
                cwd=Path(temp), timeout=0.2, cap=100,
            )
        self.assertTrue(result["timed_out"])
        self.assertTrue(result["truncated"])
        self.assertLessEqual(len(result["output"]), 100)


if __name__ == "__main__":
    unittest.main()
