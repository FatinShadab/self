"""Tests for the hardened profile configuration and egress proxy allowlist."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent.infra.egress_allowlist import Allowlist


class TestHardenedProfile(unittest.TestCase):
    def test_docker_compose_hardened_profile_specification(self) -> None:
        compose_path = Path("docker-compose.yml")
        if not compose_path.exists():
            compose_path = Path("/opt/eval-compose.yml")
        if not compose_path.exists():
            self.skipTest("docker-compose.yml not present in test environment")

        text = compose_path.read_text(encoding="utf-8")
        # 1. self-hardened service
        self.assertIn("self-hardened:", text)
        self.assertIn('profiles: ["hardened"]', text)
        self.assertIn('user: "1000:1000"', text)
        self.assertIn("read_only: true", text)
        self.assertIn("no-new-privileges:true", text)
        self.assertIn("- ALL", text)

        # Check tmpfs mounts
        self.assertIn("/tmp:rw", text)
        self.assertIn("/run:rw", text)

        # 2. egress-proxy sidecar service
        self.assertIn("egress-proxy:", text)

        # Check networks
        self.assertIn("hardened-net:", text)
        self.assertIn("internal: true", text)

    def test_egress_allowlist_filtering(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            temp_dir = Path(temp)
            allow_file = temp_dir / "egress_allowlist.txt"
            allow_file.write_text(
                "# Allowed domains\n"
                "api.openai.com\n"
                "*.anthropic.com\n"
                "localhost\n"
                "127.0.0.1\n",
                encoding="utf-8",
            )

            allowlist = Allowlist(allow_file)

            # Allowed hosts
            self.assertTrue(allowlist.is_allowed("api.openai.com"))
            self.assertTrue(allowlist.is_allowed("api.openai.com:443"))
            self.assertTrue(allowlist.is_allowed("api.anthropic.com"))
            self.assertTrue(allowlist.is_allowed("sub.api.anthropic.com"))
            self.assertTrue(allowlist.is_allowed("localhost"))
            self.assertTrue(allowlist.is_allowed("127.0.0.1:8080"))

            # Disallowed / exfiltration hosts
            self.assertFalse(allowlist.is_allowed("malicious-exfiltration.com"))
            self.assertFalse(allowlist.is_allowed("pastebin.com"))
            self.assertFalse(allowlist.is_allowed("attacker.site:443"))
            self.assertFalse(allowlist.is_allowed("openai.com.attacker.com"))


if __name__ == "__main__":
    unittest.main()
