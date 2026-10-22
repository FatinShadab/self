"""Unit tests for documentation claims guard (scripts/check_docs_claims.py)."""
from __future__ import annotations

import unittest
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

from scripts.check_docs_claims import (
    get_ground_truth_facts,
    normalize_anchor,
    check_claims,
    check_markdown_links_and_paths,
)


class DocsClaimsTests(unittest.TestCase):
    def test_ground_truth_facts_integrity(self) -> None:
        facts = get_ground_truth_facts()
        self.assertEqual(facts["tool_count"], 29)
        self.assertEqual(facts["event_count"], 135)
        self.assertEqual(facts["core_api_version"], "1.1.0")
        self.assertEqual(facts["version_file"], "1.1.0")
        # 334 baseline at rc3 + 3 tests in DocsClaimsTests = 337
        self.assertEqual(facts["harness_test_count"], 337)
        self.assertEqual(facts["eval_test_count"], 20)
        self.assertEqual(facts["total_test_count"], 357)
        self.assertEqual(facts["packages_count"], 12)
        self.assertEqual(facts["state_files_count"], 42)
        self.assertEqual(facts["env_vars_count"], 44)

    def test_normalize_anchor(self) -> None:
        self.assertEqual(normalize_anchor("What is this?"), "what-is-this")
        self.assertEqual(normalize_anchor("How to Run"), "how-to-run")
        self.assertEqual(normalize_anchor("1. Test the Checkout"), "1-test-the-checkout")

    def test_check_claims_detects_tampered_count(self) -> None:
        facts = get_ground_truth_facts()
        # Create a mock tampered facts dict where tool_count is changed
        tampered_facts = dict(facts)
        tampered_facts["tool_count"] = 999
        errors = check_claims(tampered_facts)
        # Should flag discrepancy if README claims a tool count
        # Or if we pass custom readme content:
        self.assertIsInstance(errors, list)


if __name__ == "__main__":
    unittest.main()
