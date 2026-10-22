"""Integration and unit tests for opencode delegation wrapper using fake_opencode."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from agent.infra.file_lock import locked_file
from agent.opencode.sandbox import (
    DEFAULT_ALLOWED_ROOTS,
    SandboxManager,
    build_opencode_env,
)
from agent.opencode.status import OpencodeStatusTracker
from agent.opencode.wrapper import OpencodeDelegator

FAKE_OPENCODE_PATH = str(Path(__file__).resolve().parent / "fake_opencode.py")


class TestOpencodeWrapper(unittest.TestCase):
    """End-to-end tests for opencode delegation using the fake opencode executable."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.workspace = Path(self.tmpdir) / "workspace"
        self.workspace.mkdir()

        # Seed workspace layout
        (self.workspace / ".env").write_text("ANTHROPIC_API_KEY=secret_ant_key\n")
        (self.workspace / "state").mkdir()
        (self.workspace / "workspace" / "tools").mkdir(parents=True)
        (self.workspace / "workspace" / "scratch").mkdir(parents=True)
        (self.workspace / "README.md").write_text("# Project Root\n")

        # Fake scripts/opencode/config.json
        cfg_dir = self.workspace / "scripts" / "opencode"
        cfg_dir.mkdir(parents=True)
        self.config_file = cfg_dir / "config.json"
        self.config_file.write_text(
            '{\n  "models": ["groq/llama-3.3-70b-versatile", "google/gemini-2.0-flash"],\n'
            '  "providers": {"groq": {}, "google": {}, "huggingface": {}}\n}\n'
        )

        # Environment variables for testing
        self.orig_env = os.environ.copy()
        os.environ["OPENCODE_GROQ_API_KEY"] = "gsk_valid_key"
        os.environ["OPENCODE_GOOGLE_API_KEY"] = "AIza_valid_key"
        os.environ["OPENCODE_HF_TOKEN"] = "hf_valid_key"
        os.environ["FAKE_OPENCODE_MODE"] = "success"

        # Python executable + fake_opencode script as the binary runner
        self.python_bin = sys.executable
        self.delegator = OpencodeDelegator(
            workspace=self.workspace,
            config_path=self.config_file,
            binary_path=self.python_bin,
            allowed_roots=["workspace/tools", "workspace/scratch"],
        )
        # Point the delegator's binary runner to run fake_opencode with python
        self.delegator.binary_path = self.python_bin
        # Helper to invoke fake_opencode via python
        self.orig_run_in_sb = self.delegator.sandbox_manager.run_in_sandbox

        def mock_run_in_sb(cmd, sandbox_path, env, timeout_seconds=1800, shell=False):
            # Inject fake_opencode.py after python executable if executing binary and not already injected
            if isinstance(cmd, list) and cmd and cmd[0] == self.python_bin and FAKE_OPENCODE_PATH not in cmd:
                real_cmd = [self.python_bin, FAKE_OPENCODE_PATH] + cmd[1:]
                return self.orig_run_in_sb(real_cmd, sandbox_path, env, timeout_seconds, shell=False)
            return self.orig_run_in_sb(cmd, sandbox_path, env, timeout_seconds, shell=shell)

        self.delegator.sandbox_manager.run_in_sandbox = mock_run_in_sb

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.orig_env)
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_success_then_apply(self):
        """Test happy path: delegation succeeds, acceptance passes, apply copies files to real tree."""
        os.environ["FAKE_OPENCODE_MODE"] = "success"
        acceptance_cmd = f'"{self.python_bin}" -c "import workspace.tools.generated_code as m; assert m.run()[\'ok\'] is True"'

        res = self.delegator.delegate_coding(
            spec="Create a tool in workspace/tools",
            route_reasons="Self lacks specialized code synthesizer for this task",
            target_dirs=["workspace/tools"],
            acceptance_check=acceptance_cmd,
        )

        self.assertTrue(res["ok"])
        self.assertEqual(res["status"], "completed")
        self.assertIn("workspace/tools/generated_code.py", res["changed_files"]["added"])
        delegation_id = res["delegation_id"]

        # Before apply: file does not exist in real tree
        real_tool = self.workspace / "workspace" / "tools" / "generated_code.py"
        self.assertFalse(real_tool.exists())

        # Apply delegation
        apply_res = self.delegator.apply_delegation(delegation_id)
        self.assertTrue(apply_res["ok"])
        self.assertTrue(apply_res["applied"])

        # After apply: file exists and verified in real tree
        self.assertTrue(real_tool.exists())
        self.assertIn("Successful generated code", real_tool.read_text())

    def test_acceptance_fails(self):
        """Test acceptance check failure marks status as check_failed."""
        os.environ["FAKE_OPENCODE_MODE"] = "fail_acceptance"
        acceptance_cmd = f'"{self.python_bin}" -c "import workspace.tools.generated_code as m; assert m.run()[\'ok\'] is True"'

        res = self.delegator.delegate_coding(
            spec="Create a tool in workspace/tools",
            route_reasons="Delegating task",
            target_dirs=["workspace/tools"],
            acceptance_check=acceptance_cmd,
        )

        self.assertFalse(res["ok"])
        self.assertEqual(res["status"], "check_failed")

        # Cannot apply a check_failed delegation
        apply_res = self.delegator.apply_delegation(res["delegation_id"])
        self.assertFalse(apply_res["ok"])
        self.assertFalse(apply_res["applied"])

    def test_scope_violation_rejected(self):
        """Test modifications outside allowed roots triggers rejected_scope and nothing applied."""
        os.environ["FAKE_OPENCODE_MODE"] = "scope_violation"
        acceptance_cmd = f'"{self.python_bin}" -c "print(\'ok\')"'

        res = self.delegator.delegate_coding(
            spec="Create something",
            route_reasons="Delegating task",
            target_dirs=["workspace/tools"],
            acceptance_check=acceptance_cmd,
        )

        self.assertFalse(res["ok"])
        self.assertEqual(res["status"], "rejected_scope")

        # Attempting apply must fail
        apply_res = self.delegator.apply_delegation(res["delegation_id"])
        self.assertFalse(apply_res["ok"])
        self.assertFalse(apply_res["applied"])

    def test_throttled_with_retry_advances_to_next_provider(self):
        """Test 429 rate limit records throttled state with until and tries next provider."""
        # 1st provider groq will fail with rate_limit_retry, then we switch mode to success
        os.environ["FAKE_OPENCODE_MODE"] = "rate_limit_retry"
        acceptance_cmd = f'"{self.python_bin}" -c "print(\'ok\')"'

        # When groq fails, simulate google succeeding on the next attempt
        orig_run = self.orig_run_in_sb

        def multi_provider_run(cmd, sandbox_path, env, timeout_seconds=1800, shell=False):
            if env.get("GROQ_API_KEY"):
                # groq fails with 429
                env["FAKE_OPENCODE_MODE"] = "rate_limit_retry"
            else:
                # google succeeds
                env["FAKE_OPENCODE_MODE"] = "success"
            real_cmd = [self.python_bin, FAKE_OPENCODE_PATH] + (cmd[1:] if isinstance(cmd, list) else [])
            return orig_run(real_cmd, sandbox_path, env, timeout_seconds, shell=shell)

        self.delegator.sandbox_manager.run_in_sandbox = multi_provider_run

        res = self.delegator.delegate_coding(
            spec="Task",
            route_reasons="Need helper",
            target_dirs=["workspace/tools"],
            acceptance_check=acceptance_cmd,
        )

        self.assertTrue(res["ok"])
        # Both groq and google were tried
        self.assertIn("groq", res.get("providers_tried", []))
        self.assertEqual(res.get("provider"), "google")
        # groq status should now be recorded as throttled with an until timestamp
        groq_state = self.delegator.status_tracker.get_provider_state("groq")
        self.assertEqual(groq_state["state"], "throttled")
        self.assertIsNotNone(groq_state["until"])

    def test_all_providers_throttled_unavailable_without_subprocess(self):
        """When all providers are throttled, delegate_coding returns unavailable immediately."""
        self.delegator.status_tracker.record_failure("groq", "throttled", "Rate limit", reset_seconds=3600)
        self.delegator.status_tracker.record_failure("google", "throttled", "Rate limit", reset_seconds=3600)
        self.delegator.status_tracker.record_failure("huggingface", "throttled", "Rate limit", reset_seconds=3600)

        # spy on sandbox_manager.create_sandbox: it should NOT be called
        create_called = False
        orig_create = self.delegator.sandbox_manager.create_sandbox

        def mock_create(*args, **kwargs):
            nonlocal create_called
            create_called = True
            return orig_create(*args, **kwargs)

        self.delegator.sandbox_manager.create_sandbox = mock_create

        res = self.delegator.delegate_coding(
            spec="Task",
            route_reasons="Routing reason",
            target_dirs=["workspace/tools"],
            acceptance_check="exit 0",
        )

        self.assertFalse(res["ok"])
        self.assertEqual(res["status"], "unavailable")
        self.assertFalse(create_called)

    def test_throttled_provider_returns_after_probe_succeeds(self):
        """Throttled provider transitions to probe_due after expiry and becomes available via probe."""
        self.delegator.status_tracker.record_failure("groq", "throttled", "Rate limit", reset_seconds=0.01)
        time.sleep(0.05)

        # Now probe_due
        u = self.delegator.status_tracker.usability()
        self.assertEqual(u["providers"]["groq"]["state"], "probe_due")

        # Fake probe runner returning OK
        mock_runner = lambda cmd, **kw: subprocess.CompletedProcess(args=cmd, returncode=0, stdout="OK", stderr="")
        self.delegator.status_tracker.runner_fn = mock_runner

        # Running probe should restore available state
        self.assertTrue(self.delegator.status_tracker.probe("groq"))
        pstate = self.delegator.status_tracker.get_provider_state("groq")
        self.assertEqual(pstate["state"], "available")

    def test_invalid_key_persists_until_key_hash_changes(self):
        """Invalid key error keeps state invalid until key is updated in environment."""
        self.delegator.status_tracker.record_failure("groq", "invalid_key", "401 Unauthorized")
        self.assertEqual(self.delegator.status_tracker.get_provider_state("groq")["state"], "invalid")

        # Same key -> stays invalid
        self.delegator.status_tracker.sync_keys_with_environment()
        self.assertEqual(self.delegator.status_tracker.get_provider_state("groq")["state"], "invalid")

        # Change key
        os.environ["OPENCODE_GROQ_API_KEY"] = "gsk_brand_new_key"
        self.delegator.status_tracker.sync_keys_with_environment()
        self.assertEqual(self.delegator.status_tracker.get_provider_state("groq")["state"], "unknown")

    def test_timeout_kills_process(self):
        """Process hang hits timeout and results in status=timeout."""
        os.environ["FAKE_OPENCODE_MODE"] = "hang"

        res = self.delegator.delegate_coding(
            spec="Task",
            route_reasons="Reasons",
            target_dirs=["workspace/tools"],
            acceptance_check="exit 0",
            timeout_seconds=1,  # Short 1s timeout
        )

        self.assertFalse(res["ok"])
        self.assertEqual(res["status"], "timeout")

    def test_env_builder_never_leaks_other_variables(self):
        """Assert Self's own keys are never passed into opencode subprocess environment."""
        env = build_opencode_env(base_env=os.environ)
        self.assertNotIn("ANTHROPIC_API_KEY", env)
        self.assertNotIn("OLLAMA_API_KEY", env)
        self.assertIn("GROQ_API_KEY", env)

    def test_excluded_files_absent_from_sandbox(self):
        """Verify .env and state files are excluded when sandbox is created."""
        sb_path, manifest = self.delegator.sandbox_manager.create_sandbox("del-test-excl")
        self.assertFalse((sb_path / ".env").exists())
        self.assertFalse((sb_path / "state").exists())

    def test_apply_rollback_when_recheck_fails(self):
        """If real tree acceptance check fails during apply, changes are completely rolled back."""
        # 1. Successful delegation
        os.environ["FAKE_OPENCODE_MODE"] = "success"
        acceptance_cmd = f'"{self.python_bin}" -c "import workspace.tools.generated_code as m; assert m.run()[\'ok\'] is True"'

        res = self.delegator.delegate_coding(
            spec="Create tool",
            route_reasons="Delegating",
            target_dirs=["workspace/tools"],
            acceptance_check=acceptance_cmd,
        )
        self.assertEqual(res["status"], "completed")
        delegation_id = res["delegation_id"]

        # 2. Corrupt acceptance check in delegation record so re-run fails against real tree
        with locked_file(self.delegator.delegations_lock):
            records = self.delegator._read_delegations()
            records[delegation_id]["acceptance_check"] = f'"{self.python_bin}" -c "exit(1)"'
            self.delegator._write_delegations(records)

        # 3. Apply should fail and roll back
        apply_res = self.delegator.apply_delegation(delegation_id)
        self.assertFalse(apply_res["ok"])
        self.assertFalse(apply_res["applied"])

        # Target file must NOT remain in real tree
        real_tool = self.workspace / "workspace" / "tools" / "generated_code.py"
        self.assertFalse(real_tool.exists())

    def test_discard_delegation(self):
        """Test discard_delegation cleans up the sandbox directory."""
        os.environ["FAKE_OPENCODE_MODE"] = "success"
        res = self.delegator.delegate_coding(
            spec="Create tool",
            route_reasons="Delegating",
            target_dirs=["workspace/tools"],
            acceptance_check="exit 0",
        )
        delegation_id = res["delegation_id"]
        sb_path = Path(self.delegator.get_delegation(delegation_id)["sandbox_path"])
        self.assertTrue(sb_path.exists())

        discard_res = self.delegator.discard_delegation(delegation_id)
        self.assertTrue(discard_res["ok"])
        self.assertTrue(discard_res["discarded"])
        self.assertFalse(sb_path.exists())


if __name__ == "__main__":
    unittest.main()
