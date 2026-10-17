"""Tests for the append-only SHA-256 hash-chained AuditTrail."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent.infra.audit_trail import AuditTrail, GENESIS_HASH


class TestAuditTrail(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name)
        self.log_path = self.workspace / "state" / "audit_trail.jsonl"

    def tearDown(self) -> None:
        try:
            self.temp_dir.cleanup()
        except OSError:
            pass

    def test_append_creates_hash_chain(self) -> None:
        audit = AuditTrail(self.log_path)

        hash1 = audit.append("action_requested", action="read_file", source="body", level="L0")
        self.assertEqual(len(hash1), 64)

        hash2 = audit.append("action_allowed", action="read_file", source="body")
        self.assertEqual(len(hash2), 64)

        hash3 = audit.append("action_executed", action="read_file", success=True)
        self.assertEqual(len(hash3), 64)

        # Inspect disk records
        lines = [json.loads(line) for line in self.log_path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(lines), 3)

        self.assertEqual(lines[0]["seq"], 1)
        self.assertEqual(lines[0]["prev_hash"], GENESIS_HASH)
        self.assertEqual(lines[0]["entry_hash"], hash1)

        self.assertEqual(lines[1]["seq"], 2)
        self.assertEqual(lines[1]["prev_hash"], hash1)
        self.assertEqual(lines[1]["entry_hash"], hash2)

        self.assertEqual(lines[2]["seq"], 3)
        self.assertEqual(lines[2]["prev_hash"], hash2)
        self.assertEqual(lines[2]["entry_hash"], hash3)

        # Verification passes
        is_valid, count, msg = audit.verify()
        self.assertTrue(is_valid)
        self.assertEqual(count, 3)

    def test_resume_preserves_continuity(self) -> None:
        audit1 = AuditTrail(self.log_path)
        hash1 = audit1.append("event_1", key="val1")
        hash2 = audit1.append("event_2", key="val2")

        # Open second instance on same file
        audit2 = AuditTrail(self.log_path)
        hash3 = audit2.append("event_3", key="val3")

        lines = [json.loads(line) for line in self.log_path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[2]["seq"], 3)
        self.assertEqual(lines[2]["prev_hash"], hash2)
        self.assertEqual(lines[2]["entry_hash"], hash3)

        is_valid, count, msg = audit2.verify()
        self.assertTrue(is_valid)
        self.assertEqual(count, 3)

    def test_tampering_detected_on_modified_entry(self) -> None:
        audit = AuditTrail(self.log_path)
        audit.append("event_1", amount=100)
        audit.append("event_2", amount=200)
        audit.append("event_3", amount=300)

        is_valid, count, msg = audit.verify()
        self.assertTrue(is_valid)

        # Malicious root tamper: alter amount in record 2 without re-hashing
        lines = self.log_path.read_text(encoding="utf-8").splitlines()
        rec2 = json.loads(lines[1])
        rec2["details"]["amount"] = 999999  # Tamper
        lines[1] = json.dumps(rec2, ensure_ascii=False)
        self.log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        # Verify must fail
        is_valid, count, msg = audit.verify()
        self.assertFalse(is_valid)
        self.assertIn("tampering detected", msg)

    def test_tampering_detected_on_deleted_entry(self) -> None:
        audit = AuditTrail(self.log_path)
        audit.append("event_1", step=1)
        audit.append("event_2", step=2)
        audit.append("event_3", step=3)

        is_valid, count, msg = audit.verify()
        self.assertTrue(is_valid)

        # Malicious root tamper: delete middle record
        lines = self.log_path.read_text(encoding="utf-8").splitlines()
        del lines[1]
        self.log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        # Verify must fail due to broken sequence or prev_hash mismatch
        is_valid, count, msg = audit.verify()
        self.assertFalse(is_valid)


if __name__ == "__main__":
    unittest.main()
