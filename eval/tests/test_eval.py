from __future__ import annotations

import io
import json
import tempfile
import unittest
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from llm import LLMResult
from file_lock import locked_file
from eval.calibrate import report, spearman
from eval.runner import (assert_isolated_compose, check_item, load_benchmark,
                         planned_call_count, run_item, score_records, check_code,
                         EvalQuotaStopped, _session_guard)


class FakeClient:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    def call(self, model, prompt, cap):
        self.calls.append((model, prompt, cap))
        item = self.outputs.pop(0)
        if isinstance(item, Exception):
            raise item
        return LLMResult([{"type": "text", "text": item.get("text", "")}],
                         4, item.get("output_tokens", 8),
                         item.get("stop_reason", "end_turn"), model, cap)


class HiddenEvalTests(unittest.TestCase):
    def test_hidden_set_has_eight_items_each_and_dry_run_count(self):
        data = load_benchmark()
        self.assertEqual(len(data["items"]), 40)
        self.assertEqual(planned_call_count(data, ["base", "helper"]), 240)
        self.assertEqual(data["repetitions"], 3)

    def test_compose_agent_service_has_no_eval_mount(self):
        compose = Path("/opt/eval-compose.yml").read_text(encoding="utf-8")
        assert_isolated_compose(compose)
        with self.assertRaises(RuntimeError):
            assert_isolated_compose(compose.replace("source: ./workspace\n        target: /home/entity",
                                                    "source: ./eval\n        target: /home/entity", 1))
        self.assertIn("source: ./eval", compose)
        self.assertIn("read_only: true", compose)

    def test_active_agent_shared_lock_blocks_eval_exclusive_lock(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / "state"
            state.mkdir()
            lock = state / "eval_session.lock"
            with locked_file(lock, shared=True):
                with self.assertRaisesRegex(RuntimeError, "agent session is active"):
                    _session_guard(Path(temp))
            handle = _session_guard(Path(temp))
            handle.close()

    def test_every_checker_has_pass_and_fail_paths(self):
        data = load_benchmark()
        by_kind = {}
        for item in data["items"]:
            by_kind.setdefault(item["kind"], item)
        self.assertTrue(check_item(by_kind["exact"], "59"))
        self.assertFalse(check_item(by_kind["exact"], "60"))
        self.assertTrue(check_item(by_kind["regex"], "HARBOR"))
        self.assertFalse(check_item(by_kind["regex"], "harbor"))
        self.assertTrue(check_item(by_kind["summary"], "Pine Street; the fare stays two dollars."))
        self.assertFalse(check_item(by_kind["summary"], "The fare stays two dollars."))
        self.assertTrue(check_item(by_kind["json_schema"], '{"city":"Oslo","temp_c":4}'))
        self.assertFalse(check_item(by_kind["json_schema"], '```json\n{"city":"Oslo","temp_c":4}\n```'))
        self.assertFalse(check_item(by_kind["json_schema"], '{"city":"Oslo","temp_c":4,"extra":1}'))
        self.assertTrue(check_item(by_kind["code"], "def triple(n: int) -> int:\n    return n * 3"))
        self.assertFalse(check_item(by_kind["code"], "import os\ndef triple(n): return 3*n"))

    def test_code_checker_uses_empty_directory_without_credentials_or_network(self):
        item = next(item for item in load_benchmark()["items"] if item["kind"] == "code")
        real_run = subprocess.run
        seen = []
        def inspect(*args, **kwargs):
            seen.append(kwargs)
            self.assertTrue(Path(kwargs["cwd"]).is_dir())
            self.assertEqual(kwargs["env"], {"PYTHONIOENCODING": "utf-8"})
            self.assertNotEqual(Path(kwargs["cwd"]), Path("/home/entity"))
            return real_run(*args, **kwargs)
        with patch("eval.runner.subprocess.run", side_effect=inspect):
            self.assertTrue(check_code(item, "def triple(n: int) -> int:\n    return n * 3"))
        self.assertEqual(len(seen), 1)
        with patch("eval.runner.subprocess.run", side_effect=subprocess.TimeoutExpired("python", 0.01)):
            self.assertFalse(check_code(item, "def triple(n: int) -> int:\n    return n * 3", timeout=0.01))

    def test_empty_retry_and_truncation_are_inconclusive_and_excluded(self):
        item = load_benchmark()["items"][0]
        client = FakeClient([{"text": ""}, {"text": "59"},
                             {"text": "59", "stop_reason": "max_tokens"}])
        first = run_item(item, "base", client, 1)
        second = run_item(item, "base", client, 2)
        self.assertEqual(first["outcome"], "passed")
        self.assertEqual(len(first["attempts"]), 2)
        self.assertEqual(second["outcome"], "inconclusive")
        scores = score_records([first, second])["base"]["reasoning"]
        self.assertEqual((scores["passed"], scores["conclusive"], scores["inconclusive"]), (1, 1, 1))
        self.assertEqual(scores["mean"], 1.0)
        with self.assertRaises(EvalQuotaStopped):
            run_item(item, "base", FakeClient([EvalQuotaStopped("quota")]), 1)

    def test_calibration_missing_and_tainted_ratings(self):
        start = datetime.now(timezone.utc)
        registry = {"base_model": "base", "models": [
            {"name": "base", "ratings": None, "ratings_at": None},
            {"name": "helper", "ratings": {key: "high" for key in
                ("reasoning", "code", "instruction_following", "summarization", "json_output")},
             "ratings_at": (start + timedelta(minutes=1)).isoformat()}]}
        scores = {model: {category: {"mean": score, "conclusive": 24, "inconclusive": 0}
                          for category in ("reasoning", "code", "instruction_following",
                                           "summarization", "json_output")}
                  for model, score in (("base", 0.6), ("helper", 0.8))}
        stream = io.StringIO()
        report(registry, {"started_at": start.isoformat(), "scores": scores},
               [{"origin": "model_choice", "model": "helper", "task_type": "summary"}],
               output=stream)
        text = stream.getvalue()
        self.assertIn("agent=missing", text)
        self.assertIn("TAINTED", text)
        self.assertIn("models_used=0", text)
        self.assertIn("summarization: at_or_above_base=1", text)
        self.assertAlmostEqual(spearman([(1, 0.2), (2, 0.5), (3, 0.9)]), 1.0)


if __name__ == "__main__":
    unittest.main()
