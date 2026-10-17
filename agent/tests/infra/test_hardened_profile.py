"""Tests for the hardened profile configuration and egress proxy allowlist."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from scripts.egress_proxy import Allowlist


class TestHardenedProfile(unittest.TestCase):
    def test_docker_compose_hardened_profile_specification(self) -> None:
        compose_path = Path("docker-compose.yml")
        self.assertTrue(compose_path.exists())

        data = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
        services = data.get("services", {})

        # 1. self-hardened service
        self.assertIn("self-hardened", services)
        sh = services["self-hardened"]
        self.assertIn("hardened", sh.get("profiles", []))
        self.assertEqual(sh.get("user"), "1000:1000")
        self.assertTrue(sh.get("read_only"))
        self.assertIn("no-new-privileges:true", sh.get("security_opt", []))
        self.assertIn("ALL", sh.get("cap_drop", []))

        # Check tmpfs mounts
        tmpfs = sh.get("tmpfs", [])
        self.assertTrue(any("/tmp" in str(m) for m in tmpfs))
        self.assertTrue(any("/run" in str(m) for m in tmpfs))

        # 2. egress-proxy sidecar service
        self.assertIn("egress-proxy", services)
        proxy = services["egress-proxy"]
        self.assertIn("hardened", proxy.get("profiles", []))
        self.assertIn("no-new-privileges:true", proxy.get("security_opt", []))
        self.assertIn("ALL", proxy.get("cap_drop", []))

        # Check networks
        networks = data.get("networks", {})
        self.assertIn("hardened-net", networks)
        self.assertTrue(networks["hardened-net"].get("internal"))

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
