"""Tests verifying docs/plugins content safety, authoring acceptance, and image layout."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agent.plugins.cli import cmd_new, cmd_validate


class DocsAndImageVerificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp())
        self.workspace = self.temp_dir / "workspace"
        self.workspace.mkdir(parents=True)
        docs_candidates = [
            Path(__file__).resolve().parents[3] / "docs" / "plugins",
            Path(__file__).resolve().parents[2] / "docs" / "plugins",
            Path("/opt/agent/docs/plugins"),
        ]
        self.docs_plugins = next((c for c in docs_candidates if c.exists() and (c / "overview.md").exists()), docs_candidates[0])
        template_candidates = [
            Path(__file__).resolve().parents[3] / "plugins" / "_template",
            Path(__file__).resolve().parents[2] / "plugins" / "_template",
            Path("/opt/agent/plugins/_template"),
        ]
        self.template_dir = next((c for c in template_candidates if c.exists() and (c / "plugin.json").exists()), template_candidates[0])

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_docs_plugins_exist_and_cover_required_topics(self) -> None:
        required_files = [
            "overview.md",
            "manifest-reference.md",
            "authoring-guide.md",
            "permissions-and-risk.md",
            "lifecycle.md",
            "testing.md",
        ]
        self.assertTrue(self.docs_plugins.exists(), "docs/plugins directory must exist")
        for filename in required_files:
            target = self.docs_plugins / filename
            self.assertTrue(target.exists(), f"docs/plugins/{filename} must exist")
            self.assertTrue(target.stat().st_size > 100, f"docs/plugins/{filename} must not be empty")

    def test_docs_plugins_contain_no_forbidden_terms_or_paths(self) -> None:
        """Scan docs/plugins/ for forbidden terms, internal paths, and non-neutral keywords."""
        # Forbidden terms list maintained strictly inside this test:
        forbidden_patterns = [
            r"\beval/\b",
            r"\beval\b",
            r"docs/architecture",
            r"docs/reports",
            r"antivirus",
            r"security-scanning",
            r"hardware-control",
            r"agent/infra/permission_broker",
            r"agent/infra/audit_trail",
            r"agent/infra/hardening",
            r"cap_drop",
            r"no-new-privileges",
        ]

        violations: list[str] = []
        for doc_file in self.docs_plugins.glob("*.md"):
            content = doc_file.read_text(encoding="utf-8")
            for pattern in forbidden_patterns:
                matches = re.findall(pattern, content, flags=re.IGNORECASE)
                if matches:
                    violations.append(f"{doc_file.name}: matched forbidden pattern '{pattern}' ({matches})")

        self.assertEqual(violations, [], f"Forbidden terms found in docs/plugins:\n" + "\n".join(violations))

    def test_acceptance_following_authoring_guide(self) -> None:
        """Acceptance test: follows authoring-guide.md to scaffold, validate, and test a plugin."""
        plugins_dir = self.workspace / "plugins"
        plugins_dir.mkdir(parents=True)

        # 1. Scaffold plugin with 'new'
        plugin_name = "guided_acceptance"
        code = cmd_new(
            name=plugin_name,
            dest_dir=plugins_dir,
            template_dir=self.template_dir,
        )
        self.assertEqual(code, 0)
        plugin_path = plugins_dir / plugin_name
        self.assertTrue(plugin_path.exists())

        # 2. Customize manifest and implementation exactly as described in authoring-guide.md
        manifest_file = plugin_path / "plugin.json"
        manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
        manifest_data["tools"] = [
            {
                "name": "multiply",
                "description": "Multiplies two numbers.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "a": {"type": "number"},
                        "b": {"type": "number"},
                    },
                    "required": ["a", "b"],
                },
            }
        ]
        manifest_data["sensors"] = [
            {
                "name": "pulse",
                "description": "Passive pulse sensor.",
                "risk_class": "reads",
                "reversible": True,
                "required_permission_level": "L0",
            }
        ]
        manifest_file.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")

        # Write tool and sensor implementation in plugin.py
        plugin_code = (
            "def multiply(a, b):\n"
            "    return {'ok': True, 'result': a * b}\n\n"
            "def pulse():\n"
            "    return {'ok': True, 'pulse': 1}\n\n"
            "def on_enable(context):\n"
            "    pass\n\n"
            "def on_disable(context):\n"
            "    pass\n"
        )
        (plugin_path / "plugin.py").write_text(plugin_code, encoding="utf-8")

        # Write unit tests in tests/test_plugin.py following authoring-guide pattern
        test_code = (
            "import sys\n"
            "import unittest\n"
            "from pathlib import Path\n\n"
            "plugin_dir = Path(__file__).resolve().parent.parent\n"
            "if str(plugin_dir) not in sys.path:\n"
            "    sys.path.insert(0, str(plugin_dir))\n\n"
            "from plugin import multiply, pulse\n\n"
            "class TestGuided(unittest.TestCase):\n"
            "    def test_multiply(self):\n"
            "        res = multiply(3, 4)\n"
            "        self.assertTrue(res['ok'])\n"
            "        self.assertEqual(res['result'], 12)\n"
            "    def test_pulse(self):\n"
            "        res = pulse()\n"
            "        self.assertTrue(res['ok'])\n"
        )
        (plugin_path / "tests" / "test_plugin.py").write_text(test_code, encoding="utf-8")

        # 3. Static validate
        val_code = cmd_validate(plugin_path)
        self.assertEqual(val_code, 0)

        # 4. Run unit tests
        res = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", str(plugin_path / "tests")],
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0, f"Guided plugin unit tests failed:\n{res.stdout}\n{res.stderr}")

    def test_container_image_layout_and_isolation(self) -> None:
        """Verify image layout: /opt/agent/docs/plugins exists, docs/architecture, docs/reports and eval/ do not."""
        # Check if running inside container
        opt_agent = Path("/opt/agent")
        if opt_agent.exists() and opt_agent.is_dir():
            # 1. docs/plugins exists in image
            image_docs_plugins = opt_agent / "docs" / "plugins"
            self.assertTrue(image_docs_plugins.exists(), "/opt/agent/docs/plugins must exist in image")
            self.assertTrue((image_docs_plugins / "overview.md").exists())
            self.assertTrue((image_docs_plugins / "manifest-reference.md").exists())

            # 2. Check read-only file permissions
            for p in image_docs_plugins.rglob("*"):
                if p.is_file():
                    mode = p.stat().st_mode
                    # Check write bits are not set (0o222)
                    self.assertEqual(mode & 0o222, 0, f"File {p} should be read-only")

            # 3. Forbidden paths MUST NOT exist in the image
            self.assertFalse((opt_agent / "docs" / "architecture").exists(), "docs/architecture must not be in image")
            self.assertFalse((opt_agent / "docs" / "reports").exists(), "docs/reports must not be in image")
            self.assertFalse(Path("/opt/eval").exists(), "eval/ must not be in image")
            self.assertFalse((opt_agent / "eval").exists(), "eval/ must not be in image")
        else:
            # On host: verify docker build context / Dockerfile preserves this isolation
            repo_root = Path(__file__).resolve().parents[3]
            dockerfile = (repo_root / "Dockerfile").read_text(encoding="utf-8")
            self.assertIn("COPY docs/plugins/ /opt/agent/docs/plugins/", dockerfile)
            self.assertNotIn("COPY docs/architecture", dockerfile)
            self.assertNotIn("COPY docs/reports", dockerfile)
            self.assertNotIn("COPY eval", dockerfile)


if __name__ == "__main__":
    unittest.main()
