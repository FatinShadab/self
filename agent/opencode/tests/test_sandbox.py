"""Unit tests for opencode sandbox, environment builder, scope checks, and safeguards."""
from __future__ import annotations

import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from agent.opencode.sandbox import (
    DEFAULT_ALLOWED_ROOTS,
    SandboxManager,
    build_opencode_env,
    compute_manifest,
    is_protected_path,
)


class TestEnvironmentBuilder(unittest.TestCase):
    """Test build_opencode_env safeguards and variable filtering."""

    def test_minimal_env_no_leakage(self):
        dirty_env = {
            "PATH": "/bin:/usr/bin",
            "LANG": "en_US.UTF-8",
            "ANTHROPIC_API_KEY": "sk-ant-secret123",
            "OLLAMA_API_KEY": "ollama-secret456",
            "SELF_MAX_TOKENS_PER_DAY": "500000",
            "OPENCODE_GROQ_API_KEY": "gsk_groq123",
            "OPENCODE_GOOGLE_API_KEY": "AIza_google456",
            "OPENCODE_HF_TOKEN": "hf_token789",
        }
        clean_env = build_opencode_env(base_env=dirty_env)

        # Must contain standard mapped keys
        self.assertEqual(clean_env["GROQ_API_KEY"], "gsk_groq123")
        self.assertEqual(clean_env["GEMINI_API_KEY"], "AIza_google456")
        self.assertEqual(clean_env["HF_TOKEN"], "hf_token789")

        # Must NOT leak Self's own credentials or configs
        self.assertNotIn("ANTHROPIC_API_KEY", clean_env)
        self.assertNotIn("OLLAMA_API_KEY", clean_env)
        self.assertNotIn("SELF_MAX_TOKENS_PER_DAY", clean_env)
        self.assertNotIn("OPENCODE_GROQ_API_KEY", clean_env)

        # Basic env vars
        self.assertIn("PATH", clean_env)
        self.assertIn("LANG", clean_env)
        self.assertIn("HOME", clean_env)
        self.assertIn("OPENCODE_CONFIG_DIR", clean_env)


class TestSandboxExclusionsAndManifest(unittest.TestCase):
    """Test sandbox copying exclusions and manifest creation."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.repo = Path(self.tmpdir) / "repo"
        self.repo.mkdir()

        # Create mock repo layout
        (self.repo / ".env").write_text("SECRET=123")
        (self.repo / ".env.local").write_text("SECRET=local")
        (self.repo / "state").mkdir()
        (self.repo / "state" / "run.json").write_text("{}")
        (self.repo / "workspace" / "state").mkdir(parents=True)
        (self.repo / "workspace" / "state" / "map.json").write_text("{}")
        (self.repo / "workspace" / "memory").mkdir(parents=True)
        (self.repo / "workspace" / "memory" / "notes.md").write_text("notes")
        (self.repo / "workspace" / "logs").mkdir(parents=True)
        (self.repo / "workspace" / "logs" / "run.log").write_text("log")
        (self.repo / ".git").mkdir()
        (self.repo / ".git" / "config").write_text("git")
        (self.repo / "vendor").mkdir()
        (self.repo / "vendor" / "lib.py").write_text("code")
        (self.repo / "scripts" / "opencode").mkdir(parents=True)
        (self.repo / "scripts" / "opencode" / "install.py").write_text("code")
        (self.repo / "agent" / "opencode").mkdir(parents=True)
        (self.repo / "agent" / "opencode" / "wrapper.py").write_text("code")

        # Allowed files
        (self.repo / "workspace" / "tools").mkdir(parents=True)
        (self.repo / "workspace" / "tools" / "my_tool.py").write_text("def run(): pass")
        (self.repo / "README.md").write_text("# Test Repo")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_sandbox_excludes_sensitive_paths(self):
        mgr = SandboxManager(repo_root=self.repo, sandboxes_dir=self.repo / "sandboxes")
        sandbox_path, manifest = mgr.create_sandbox("del-100")

        # Excluded files must NOT exist in sandbox
        self.assertFalse((sandbox_path / ".env").exists())
        self.assertFalse((sandbox_path / ".env.local").exists())
        self.assertFalse((sandbox_path / "state" / "run.json").exists())
        self.assertFalse((sandbox_path / "workspace" / "state" / "map.json").exists())
        self.assertFalse((sandbox_path / "workspace" / "memory" / "notes.md").exists())
        self.assertFalse((sandbox_path / "workspace" / "logs" / "run.log").exists())
        self.assertFalse((sandbox_path / ".git").exists())
        self.assertFalse((sandbox_path / "vendor").exists())
        self.assertFalse((sandbox_path / "scripts" / "opencode").exists())
        self.assertFalse((sandbox_path / "agent" / "opencode").exists())

        # Allowed files MUST exist
        self.assertTrue((sandbox_path / "workspace" / "tools" / "my_tool.py").exists())
        self.assertTrue((sandbox_path / "README.md").exists())

        # Manifest must reflect allowed files
        self.assertIn("workspace/tools/my_tool.py", manifest)
        self.assertIn("README.md", manifest)


class TestScopeCheck(unittest.TestCase):
    """Test scope checking against allowed write roots."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.sandbox = Path(self.tmpdir) / "sandbox"
        self.sandbox.mkdir()

        (self.sandbox / "workspace" / "tools").mkdir(parents=True)
        (self.sandbox / "workspace" / "tools" / "tool_a.py").write_text("v1")
        (self.sandbox / "README.md").write_text("readme")

        self.initial_manifest = compute_manifest(self.sandbox)
        self.mgr = SandboxManager(allowed_roots=["workspace/tools", "workspace/scratch"])

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_clean_modifications_inside_allowed_roots(self):
        # Modify a file inside workspace/tools
        (self.sandbox / "workspace" / "tools" / "tool_a.py").write_text("v2 modified")
        # Add a new file inside workspace/tools
        (self.sandbox / "workspace" / "tools" / "tool_b.py").write_text("new tool")

        is_clean, changes = self.mgr.check_scope(self.sandbox, self.initial_manifest)
        self.assertTrue(is_clean)
        self.assertEqual(changes["modified"], ["workspace/tools/tool_a.py"])
        self.assertEqual(changes["added"], ["workspace/tools/tool_b.py"])
        self.assertEqual(changes["deleted"], [])

    def test_scope_violation_outside_allowed_roots(self):
        # Modify file outside allowed roots
        (self.sandbox / "README.md").write_text("tampered readme")

        is_clean, changes = self.mgr.check_scope(self.sandbox, self.initial_manifest)
        self.assertFalse(is_clean)
        self.assertIn("README.md", changes["modified"])

    def test_scope_violation_added_outside(self):
        # Add new file outside allowed roots
        (self.sandbox / "hacked.sh").write_text("echo evil")

        is_clean, changes = self.mgr.check_scope(self.sandbox, self.initial_manifest)
        self.assertFalse(is_clean)
        self.assertIn("hacked.sh", changes["added"])


class TestProtectedPaths(unittest.TestCase):
    """Test is_protected_path safeguard for Self's own file-writing tools."""

    def test_is_protected_path_rules(self):
        self.assertTrue(is_protected_path(".env"))
        self.assertTrue(is_protected_path(".env.production"))
        self.assertTrue(is_protected_path("path/to/.env"))
        self.assertTrue(is_protected_path("scripts/opencode/install_opencode.py"))
        self.assertTrue(is_protected_path("agent/opencode/wrapper.py"))
        self.assertTrue(is_protected_path("config/permissions.json"))
        self.assertTrue(is_protected_path("state/opencode_status.json"))
        self.assertTrue(is_protected_path("workspace/state/opencode_status.lock"))

        # Non-protected files
        self.assertFalse(is_protected_path("workspace/tools/new_tool.py"))
        self.assertFalse(is_protected_path("workspace/scratch/notes.txt"))

    def test_container_body_refuses_protected_path(self):
        from agent.body.container import ContainerBody
        from agent.infra.event_log import EventLogger
        with tempfile.TemporaryDirectory() as td:
            body = ContainerBody(workspace=Path(td), logger=EventLogger(Path(td)))
            with self.assertRaises(PermissionError):
                body.write_file(".env", "FOO=BAR")
            with self.assertRaises(PermissionError):
                body.write_file("scripts/opencode/config.json", "{}")
            with self.assertRaises(PermissionError):
                body.write_file("agent/opencode/sandbox.py", "# code")


class TestSandboxCleanup(unittest.TestCase):
    """Test deletion of old sandboxes."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.sandboxes_dir = Path(self.tmpdir) / "sandboxes"
        self.sandboxes_dir.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_cleanup_removes_old_keeps_new(self):
        old_sb = self.sandboxes_dir / "sandbox_old123"
        old_sb.mkdir()
        (old_sb / "file.txt").write_text("data")

        new_sb = self.sandboxes_dir / "sandbox_new456"
        new_sb.mkdir()
        (new_sb / "file.txt").write_text("data")

        # Set mtime of old_sb to 10 days ago
        ten_days_ago = time.time() - (10 * 86400)
        os.utime(old_sb, (ten_days_ago, ten_days_ago))

        mgr = SandboxManager(sandboxes_dir=self.sandboxes_dir)
        removed = mgr.cleanup_old_sandboxes(max_age_days=7)

        self.assertEqual(removed, 1)
        self.assertFalse(old_sb.exists())
        self.assertTrue(new_sb.exists())


if __name__ == "__main__":
    unittest.main()
