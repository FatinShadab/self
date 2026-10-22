"""Unit tests for opencode availability status, health tracking, and failure classification."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from agent.opencode.status import (
    BACKOFF_SCHEDULE,
    OpencodeStatusTracker,
    classify_failure,
    parse_reset_time,
)


class TestFailureClassification(unittest.TestCase):
    """Test classify_failure and reset time parsing."""

    def test_classify_ok(self):
        self.assertEqual(classify_failure(0, "All good"), "ok")

    def test_classify_invalid_key(self):
        self.assertEqual(classify_failure(1, "401 Unauthorized: Invalid API key"), "invalid_key")
        self.assertEqual(classify_failure(1, "Authentication failed. 403 Forbidden"), "invalid_key")
        self.assertEqual(classify_failure(1, "invalid_api_key provided"), "invalid_key")

    def test_classify_quota_daily(self):
        self.assertEqual(classify_failure(1, "Error: Daily quota exceeded for this account"), "quota_daily")
        self.assertEqual(classify_failure(1, "insufficient_quota: out of credits on billing"), "quota_daily")
        self.assertEqual(classify_failure(1, "You exceeded your current quota"), "quota_daily")

    def test_classify_throttled(self):
        self.assertEqual(classify_failure(1, "429 Too Many Requests"), "throttled")
        self.assertEqual(classify_failure(1, "Rate limit reached. Please wait."), "throttled")
        self.assertEqual(classify_failure(1, "Resource exhausted (ratelimit)"), "throttled")

    def test_classify_transient(self):
        self.assertEqual(classify_failure(1, "503 Service Unavailable"), "transient")
        self.assertEqual(classify_failure(1, "Connection reset by peer"), "transient")
        self.assertEqual(classify_failure(1, "Request timed out after 30s"), "transient")

    def test_parse_reset_time_seconds(self):
        self.assertEqual(parse_reset_time("Rate limit reached. Retry in 30s"), 30.0)
        self.assertEqual(parse_reset_time("Please try again in 45 seconds."), 45.0)
        self.assertEqual(parse_reset_time("Retry-After: 60"), 60.0)
        self.assertEqual(parse_reset_time("15s remaining until retry"), 15.0)

    def test_parse_reset_time_minutes(self):
        self.assertEqual(parse_reset_time("Quota exceeded. Retry in 2m"), 120.0)
        self.assertEqual(parse_reset_time("try again in 5 minutes"), 300.0)

    def test_parse_reset_time_hours(self):
        self.assertEqual(parse_reset_time("Retry after 1h"), 3600.0)

    def test_parse_reset_time_none(self):
        self.assertIsNone(parse_reset_time("Something went wrong"))
        self.assertIsNone(parse_reset_time(""))


class TestStatusTracker(unittest.TestCase):
    """Test OpencodeStatusTracker state management, usability, and probing."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.workspace = Path(self.tmpdir)
        # Clear provider env vars for a clean state
        self.orig_env = {
            "OPENCODE_GROQ_API_KEY": os.environ.get("OPENCODE_GROQ_API_KEY"),
            "OPENCODE_GOOGLE_API_KEY": os.environ.get("OPENCODE_GOOGLE_API_KEY"),
            "OPENCODE_HF_TOKEN": os.environ.get("OPENCODE_HF_TOKEN"),
        }
        for k in self.orig_env:
            os.environ.pop(k, None)

    def tearDown(self):
        for k, v in self.orig_env.items():
            if v is not None:
                os.environ[k] = v
            else:
                os.environ.pop(k, None)
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_initial_state_not_configured(self):
        tracker = OpencodeStatusTracker(workspace=self.workspace)
        u = tracker.usability()
        self.assertFalse(u["usable"])
        self.assertEqual(u["providers"]["groq"]["state"], "not_configured")
        self.assertEqual(u["providers"]["google"]["state"], "not_configured")
        self.assertEqual(u["providers"]["huggingface"]["state"], "not_configured")

    def test_key_configured_becomes_unknown(self):
        os.environ["OPENCODE_GROQ_API_KEY"] = "gsk_test123"
        tracker = OpencodeStatusTracker(workspace=self.workspace)
        u = tracker.usability()
        self.assertTrue(u["usable"])
        self.assertEqual(u["providers"]["groq"]["state"], "unknown")
        # key_hash should be populated, never the key itself
        self.assertIsNotNone(u["providers"]["groq"]["key_hash"])
        self.assertNotIn("gsk_test123", json.dumps(u))

    def test_record_success_makes_available(self):
        os.environ["OPENCODE_GROQ_API_KEY"] = "gsk_test123"
        tracker = OpencodeStatusTracker(workspace=self.workspace)
        tracker.record_success("groq")
        pstate = tracker.get_provider_state("groq")
        self.assertEqual(pstate["state"], "available")
        self.assertEqual(pstate["consecutive_failures"], 0)
        self.assertIsNone(pstate["until"])

    def test_throttled_with_explicit_reset_time(self):
        os.environ["OPENCODE_GROQ_API_KEY"] = "gsk_test123"
        tracker = OpencodeStatusTracker(workspace=self.workspace)
        tracker.record_failure("groq", "throttled", "Rate limit: retry in 30s", reset_seconds=30.0)
        pstate = tracker.get_provider_state("groq")
        self.assertEqual(pstate["state"], "throttled")
        self.assertEqual(pstate["consecutive_failures"], 1)
        self.assertIsNotNone(pstate["until"])

    def test_throttled_backoff_schedule(self):
        os.environ["OPENCODE_GROQ_API_KEY"] = "gsk_test123"
        tracker = OpencodeStatusTracker(workspace=self.workspace)
        # 1st failure -> 60s (1m)
        tracker.record_failure("groq", "throttled", "Rate limit")
        pstate = tracker.get_provider_state("groq")
        self.assertEqual(pstate["consecutive_failures"], 1)

        # 2nd failure -> 300s (5m)
        tracker.record_failure("groq", "throttled", "Rate limit")
        pstate = tracker.get_provider_state("groq")
        self.assertEqual(pstate["consecutive_failures"], 2)

    def test_daily_quota_fallback_one_hour(self):
        os.environ["OPENCODE_GOOGLE_API_KEY"] = "AIzaSyTest"
        tracker = OpencodeStatusTracker(workspace=self.workspace)
        before = time.time()
        tracker.record_failure("google", "quota_daily", "Exceeded daily quota")
        pstate = tracker.get_provider_state("google")
        self.assertEqual(pstate["state"], "throttled")
        until_dt = datetime.fromisoformat(pstate["until"])
        delta = until_dt.timestamp() - before
        # Should be approximately 3600 seconds (1 hour)
        self.assertTrue(3550 <= delta <= 3650)

    def test_invalid_key_persists_until_key_changes(self):
        os.environ["OPENCODE_HF_TOKEN"] = "hf_badkey"
        tracker = OpencodeStatusTracker(workspace=self.workspace)
        tracker.record_failure("huggingface", "invalid_key", "401 Unauthorized")
        pstate = tracker.get_provider_state("huggingface")
        self.assertEqual(pstate["state"], "invalid")
        self.assertIsNone(pstate["until"])

        # Usability should be false since only key is invalid
        u = tracker.usability()
        self.assertFalse(u["usable"])

        # Change key in environment -> resets to unknown!
        os.environ["OPENCODE_HF_TOKEN"] = "hf_newgoodkey"
        tracker.sync_keys_with_environment()
        pstate = tracker.get_provider_state("huggingface")
        self.assertEqual(pstate["state"], "unknown")
        u2 = tracker.usability()
        self.assertTrue(u2["usable"])

    def test_throttled_becomes_probe_due_after_until_passes(self):
        os.environ["OPENCODE_GROQ_API_KEY"] = "gsk_test123"
        tracker = OpencodeStatusTracker(workspace=self.workspace)
        # Set failure with 0.1s reset time
        tracker.record_failure("groq", "throttled", "Rate limit", reset_seconds=0.01)
        time.sleep(0.05)
        u = tracker.usability()
        self.assertTrue(u["usable"])
        self.assertEqual(u["providers"]["groq"]["state"], "probe_due")

    def test_probe_success_returns_to_available(self):
        os.environ["OPENCODE_GROQ_API_KEY"] = "gsk_test123"
        mock_runner = mock.Mock(
            return_value=subprocess.CompletedProcess(
                args=["opencode"], returncode=0, stdout="OK", stderr=""
            )
        )
        tracker = OpencodeStatusTracker(workspace=self.workspace, runner_fn=mock_runner)
        # First mark throttled
        tracker.record_failure("groq", "throttled", "Rate limit")
        self.assertEqual(tracker.get_provider_state("groq")["state"], "throttled")

        # Probe should succeed and make it available
        success = tracker.probe("groq")
        self.assertTrue(success)
        self.assertEqual(tracker.get_provider_state("groq")["state"], "available")
        self.assertEqual(tracker.get_provider_state("groq")["consecutive_failures"], 0)

    def test_probe_failure_reclassifies(self):
        os.environ["OPENCODE_GROQ_API_KEY"] = "gsk_test123"
        mock_runner = mock.Mock(
            return_value=subprocess.CompletedProcess(
                args=["opencode"], returncode=1, stdout="", stderr="429 Too Many Requests retry in 60s"
            )
        )
        tracker = OpencodeStatusTracker(workspace=self.workspace, runner_fn=mock_runner)
        success = tracker.probe("groq")
        self.assertFalse(success)
        pstate = tracker.get_provider_state("groq")
        self.assertEqual(pstate["state"], "throttled")
        self.assertIsNotNone(pstate["until"])


if __name__ == "__main__":
    unittest.main()
