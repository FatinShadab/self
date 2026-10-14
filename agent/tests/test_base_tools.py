from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from base_tools import ToolRunner
from event_log import EventLogger


class ToolRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name)
        self.logger = EventLogger(self.workspace / "logs" / "actions.jsonl")
        self.runner = ToolRunner(self.logger, self.workspace, output_cap=1_000)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_file_tools_and_tool_creation_log(self) -> None:
        target = self.workspace / "tools" / "probe.py"
        written = self.runner.execute("write_file", {"path": str(target), "content": "print('ok')\n"})
        self.assertTrue(written["ok"])
        read = self.runner.execute("read_file", {"path": str(target)})
        self.assertIn("print('ok')", read["content"])
        listed = self.runner.execute("list_dir", {"path": str(target.parent)})
        self.assertEqual(listed["entries"][0]["name"], "probe.py")
        events = [json.loads(line)["event"] for line in self.logger.path.read_text().splitlines()]
        self.assertIn("tool_created", events)

    def test_shell_timeout_and_output_cap(self) -> None:
        capped = self.runner.execute("run_shell", {"cmd": "python -c \"print('x' * 5000)\""})
        self.assertTrue(capped["truncated"])
        self.assertLessEqual(len(capped["output"]), 1_000)
        timed = self.runner.execute("run_shell", {"cmd": "sleep 2", "timeout": 0.1})
        self.assertTrue(timed["timed_out"])

    def test_shell_background_child_cannot_hold_pipe_forever(self) -> None:
        timed = self.runner.execute("run_shell", {"cmd": "sleep 5 &", "timeout": 0.1})
        self.assertTrue(timed["timed_out"])

    def test_known_secret_is_redacted(self) -> None:
        old = os.environ.get("TEST_API_KEY")
        os.environ["TEST_API_KEY"] = "unit-test-secret-value"
        try:
            logger = EventLogger(self.workspace / "logs" / "redaction.jsonl")
            runner = ToolRunner(logger, self.workspace)
            result = runner.execute("run_shell", {"cmd": "printf unit-test-secret-value"})
            self.assertNotIn("unit-test-secret-value", result["output"])
            self.assertNotIn("unit-test-secret-value", logger.path.read_text())
        finally:
            if old is None:
                os.environ.pop("TEST_API_KEY", None)
            else:
                os.environ["TEST_API_KEY"] = old

    def test_http_get_logs_host_and_path_without_query(self) -> None:
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                body = b"local response"
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_: object) -> None:
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}/probe?private=value"
            result = self.runner.execute("http_get", {"url": url})
            self.assertEqual(result["status"], 200)
            self.assertEqual(result["body"], "local response")
            log_text = self.logger.path.read_text()
            self.assertIn('"path":"/probe"', log_text)
            self.assertNotIn("private=value", log_text)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
