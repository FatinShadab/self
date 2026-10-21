"""Tests for deterministic_summary(), retrieve_memories() report_path, and migration stats."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from agent.infra.migration import deterministic_summary, restore_migration_p14, run_migration_p14


# ---------------------------------------------------------------------------
# Test data: 13 cases covering a range of real-world lesson patterns
# (label, input, expected_max_chars, must_contain, must_not_contain)
# ---------------------------------------------------------------------------
TEST_CASES = [
    # Case 1: Already short – returned unchanged
    ("already_short", "Listing the root directory.", 280, ["Listing the root directory."], ["..."]),
    # Case 2: Empty → sentinel
    ("empty", "", 280, ["Cycle completed"], []),
    # Case 3: Cycle-1 Report header stripped, findings preferred
    (
        "cycle_report_header_stripped",
        "**Cycle 1 Report**\n\n**What I discovered**\n- The root filesystem contains the usual Linux directories.\n- My home directory `/home/entity` holds persistent sub-folders.\n- The container runs Debian 12 (bookworm).",
        280,
        ["root filesystem", "Debian 12"],  # content preserved
        ["Cycle 1 Report", "What I discovered"],  # headers removed
    ),
    # Case 4: Narration header stripped
    (
        "narration_header_stripped",
        "**Narration:** Ran `python -m pip list --format=json` to retrieve the inventory.\n\n**Discoveries this cycle**\n- The container has a comprehensive set of Python packages installed.",
        280,
        ["Python packages"],
        ["Narration"],
    ),
    # Case 5: Long text with Discoveries section – prefer that section
    (
        "discoveries_section_preferred",
        "Some preamble text that is boring.\n\n**Discoveries**\n- Key finding number one.\n- Key finding number two.\n- Key finding number three about systemd.",
        280,
        ["Key finding"],
        [],
    ),
    # Case 6: Very long text cut at sentence boundary
    (
        "cut_at_sentence_boundary",
        "Action taken: did something. " + "X" * 300 + ". Final sentence.",
        280,
        ["…"],
        [],
    ),
    # Case 7: Text that needs word-boundary cut (no sentence boundary in window)
    (
        "cut_at_word_boundary",
        "A" * 200 + " word " + "B" * 200,
        280,
        ["…"],
        [],
    ),
    # Case 8: Exploration Cycle header stripped
    (
        "exploration_cycle_header_stripped",
        "**Exploration Cycle 4 – Report**\n\n**What I did**\n1. Inspected system-d configuration directories.\n2. Read and parsed the unit files.",
        280,
        ["Inspected", "unit files"],
        ["Exploration Cycle 4"],
    ),
    # Case 9: Already-bounded lesson (<=280) kept as-is
    (
        "already_bounded_kept",
        "Short lesson that is already within limits and needs no truncation at all.",
        280,
        ["Short lesson"],
        ["…"],
    ),
    # Case 10: 4000-char lesson (already-truncated upstream) – still summarized correctly
    (
        "4000_char_lesson",
        "**Cycle 13 Report – Exploration Progress**\n\n**What I did (observable actions)**\n1. Listed the contents of the system-d wants directories.\n2. Read the full unit files for several core services.\n" + "X" * 3700,
        280,
        ["…"],
        ["Cycle 13 Report"],
    ),
    # Case 11: Worst example 1 (index 104 pattern) – timer list
    (
        "worst_timer_list",
        "**Cycle 13 Report – Exploration Progress**\n\n**What I did (observable actions)**\n1. Listed the contents of the system-d wants directories:\n   * `/etc/systemd/system/timers.target.wants` -> `apt-daily-upgrade.timer`, `apt-daily.timer`\n2. Read the full unit files for several core services and timers and stored their text:\n   * `dpkg-db-backup.service`\n3. Added documentation listings and environment map entries.",
        280,
        ["apt-daily"],
        ["Cycle 13 Report"],
    ),
    # Case 12: Worst example 2 (index 234 pattern) – Cycle 1 Report
    (
        "worst_cycle1_report",
        "**Cycle 1 Report**\n\n**What I observed**\n- Listed all systemd unit files in `/usr/lib/systemd/system` (14 files: services and timers).\n- Discovered which units are enabled via symlinks:\n  - Enabled timers: `apt-daily-upgrade.timer`, `apt-daily.timer`, `dpkg-db-backup.timer`.\n- Inspected the `/var/log` directory.",
        280,
        ["systemd unit files"],
        ["Cycle 1 Report", "What I observed"],
    ),
    # Case 13: Worst example 3 (index 423 pattern) – Cycle 2 Report Continued
    (
        "worst_cycle2_continued",
        "**Cycle 2 Report – Continued Exploration**\n\n**What I explored this step**\n- Timer-service details – used the `timer_service_info` tool to fetch the full schedule.\n- Installed packages – read the full list of Debian packages from `/home/entity/state/installed_packages_full.txt`.\n- Environment map updates – persisted the newly discovered data.",
        280,
        ["timer_service_info", "installed_packages_full"],
        ["Cycle 2 Report", "What I explored"],
    ),
]


class TestDeterministicSummary(unittest.TestCase):
    """Verify deterministic_summary() behaviour for all 13 test cases."""

    def _run_case(self, label, text, max_chars, must_contain, must_not_contain):
        result = deterministic_summary(text, max_chars=max_chars)
        self.assertLessEqual(
            len(result), max_chars,
            f"[{label}] Exceeded {max_chars} chars: {len(result)}"
        )
        for fragment in must_contain:
            self.assertIn(fragment, result, f"[{label}] Expected fragment not found: {repr(fragment)}")
        for fragment in must_not_contain:
            self.assertNotIn(fragment, result, f"[{label}] Unexpected fragment found: {repr(fragment)}")

    def test_case_01_already_short(self):
        self._run_case(*TEST_CASES[0])

    def test_case_02_empty(self):
        self._run_case(*TEST_CASES[1])

    def test_case_03_cycle_report_header_stripped(self):
        self._run_case(*TEST_CASES[2])

    def test_case_04_narration_header_stripped(self):
        self._run_case(*TEST_CASES[3])

    def test_case_05_discoveries_section_preferred(self):
        self._run_case(*TEST_CASES[4])

    def test_case_06_cut_at_sentence_boundary(self):
        self._run_case(*TEST_CASES[5])

    def test_case_07_cut_at_word_boundary(self):
        self._run_case(*TEST_CASES[6])

    def test_case_08_exploration_cycle_header_stripped(self):
        self._run_case(*TEST_CASES[7])

    def test_case_09_already_bounded_kept(self):
        self._run_case(*TEST_CASES[8])

    def test_case_10_4000_char_lesson(self):
        self._run_case(*TEST_CASES[9])

    def test_case_11_worst_timer_list(self):
        self._run_case(*TEST_CASES[10])

    def test_case_12_worst_cycle1_report(self):
        self._run_case(*TEST_CASES[11])

    def test_case_13_worst_cycle2_continued(self):
        self._run_case(*TEST_CASES[12])

    def test_fallback_first_and_last_sentence(self):
        """When no preferred section header exists, summary takes first sentence + last sentence."""
        text = (
            "The initial scan discovered a Linux environment. "
            "Middle sentence one that has details about various files. "
            "Middle sentence two that elaborates on configuration. "
            "Conclusion reveals five systemd units are active."
        )
        res = deterministic_summary(text, max_chars=180)
        self.assertLessEqual(len(res), 180)
        self.assertIn("The initial scan discovered a Linux environment.", res)
        self.assertIn("Conclusion reveals five systemd units are active.", res)
        self.assertNotIn("Middle sentence one", res)


class TestRetrievalReportPath(unittest.TestCase):
    """Verify retrieve_memories() includes/excludes Report: line correctly."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.workspace = Path(self.tmp)
        self.state_dir = self.workspace / "state"
        self.state_dir.mkdir()
        logs_dir = self.workspace / "logs"
        logs_dir.mkdir()
        from agent.infra.event_log import EventLogger
        self.logger = EventLogger(logs_dir / "events.jsonl")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_retrieval_includes_report_path_for_bounded_entries(self):
        """An entry WITH report_path must include 'Report: ...' in the retrieval output."""
        entry = {
            "timestamp": "2026-01-01T00:00:00Z",
            "what_was_tried": "Explored container filesystem",
            "outcome": "completed",
            "lesson": "Found Debian 12.",
            "report_path": "state/reports/report_migrated_00007.txt",
            "tags": ["filesystem"],
            "plugin": "core",
            "body": "container",
        }
        (self.state_dir / "memory.jsonl").write_text(
            json.dumps(entry) + "\n", encoding="utf-8", newline="\n"
        )

        from agent.learning.learning import LearningStore
        store = LearningStore(self.workspace, self.logger)
        result = store.retrieve_memories("container filesystem")
        self.assertIn("Report: state/reports/report_migrated_00007.txt", result)

    def test_retrieval_no_report_path_for_legacy_entries(self):
        """An entry WITHOUT report_path must NOT include 'Report:' in the retrieval output."""
        entry = {
            "timestamp": "2026-01-01T00:00:00Z",
            "what_was_tried": "Listed root directory",
            "outcome": "completed",
            "lesson": "Root has standard Linux dirs.",
            "tags": ["filesystem"],
            "plugin": "core",
            "body": "container",
        }
        (self.state_dir / "memory.jsonl").write_text(
            json.dumps(entry) + "\n", encoding="utf-8", newline="\n"
        )

        from agent.learning.learning import LearningStore
        store = LearningStore(self.workspace, self.logger)
        result = store.retrieve_memories("root directory")
        self.assertNotIn("Report:", result)


class TestMigrationStats(unittest.TestCase):
    """Verify that migration stats dict has the 3 new keys with correct values."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.workspace = Path(self.tmp)
        state_dir = self.workspace / "state"
        state_dir.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_memory(self, entries: list[dict]) -> None:
        mem_path = self.workspace / "state" / "memory.jsonl"
        lines = [json.dumps(e, ensure_ascii=False) for e in entries]
        mem_path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")

    def test_stats_keys_present(self):
        """Stats dict must have entries_with_report, entries_left_alone, entries_already_4000."""
        stats = run_migration_p14(self.workspace)
        self.assertIn("entries_with_report", stats)
        self.assertIn("entries_left_alone", stats)
        self.assertIn("entries_already_4000", stats)

    def test_long_lesson_counted_as_with_report(self):
        """A lesson > 280 chars should increment entries_with_report."""
        long_lesson = "X" * 400
        self._write_memory([
            {
                "timestamp": "2026-01-01T00:00:00Z",
                "what_was_tried": "something",
                "outcome": "completed",
                "lesson": long_lesson,
                "tags": [],
                "plugin": "core",
                "body": "container",
            }
        ])
        stats = run_migration_p14(self.workspace)
        self.assertEqual(stats["entries_with_report"], 1)
        self.assertEqual(stats["entries_left_alone"], 0)

    def test_short_lesson_counted_as_left_alone(self):
        """A lesson <= 280 chars should increment entries_left_alone."""
        self._write_memory([
            {
                "timestamp": "2026-01-01T00:00:00Z",
                "what_was_tried": "something",
                "outcome": "completed",
                "lesson": "Short lesson.",
                "tags": [],
                "plugin": "core",
                "body": "container",
            }
        ])
        stats = run_migration_p14(self.workspace)
        self.assertEqual(stats["entries_left_alone"], 1)
        self.assertEqual(stats["entries_with_report"], 0)

    def test_already_migrated_entry_is_idempotent(self):
        """An entry with report_path already set must not be re-processed."""
        self._write_memory([
            {
                "timestamp": "2026-01-01T00:00:00Z",
                "what_was_tried": "something",
                "outcome": "completed",
                "lesson": "Already bounded.",
                "report_path": "state/reports/report_migrated_00000.txt",
                "tags": [],
                "plugin": "core",
                "body": "container",
            }
        ])
        stats = run_migration_p14(self.workspace)
        self.assertEqual(stats["entries_with_report"], 0)
        self.assertEqual(stats["entries_left_alone"], 0)

    def test_4000_char_lesson_counted(self):
        """A lesson of exactly 4000 chars should increment entries_already_4000."""
        lesson_4000 = "Y" * 4000
        self._write_memory([
            {
                "timestamp": "2026-01-01T00:00:00Z",
                "what_was_tried": "something",
                "outcome": "completed",
                "lesson": lesson_4000,
                "tags": [],
                "plugin": "core",
                "body": "container",
            }
        ])
        stats = run_migration_p14(self.workspace)
        self.assertEqual(stats["entries_already_4000"], 1)
        self.assertEqual(stats["entries_with_report"], 1)


class TestRestoreLegacyManifest(unittest.TestCase):
    """Verify that restore_migration_p14() successfully falls back to manifest.json."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.workspace = Path(self.tmp)
        state_dir = self.workspace / "state"
        state_dir.mkdir(parents=True)
        (state_dir / "memory.jsonl").write_text("orig memory\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_restore_falls_back_to_legacy_manifest_name(self):
        stats = run_migration_p14(self.workspace)
        backup_path = Path(stats["backup_path"])

        # Rename backup_manifest.json -> manifest.json to simulate an older backup
        bm = backup_path / "backup_manifest.json"
        legacy_m = backup_path / "manifest.json"
        self.assertTrue(bm.exists())
        bm.rename(legacy_m)
        self.assertFalse(bm.exists())
        self.assertTrue(legacy_m.exists())

        # Overwrite file to simulate corrupted state
        (self.workspace / "state" / "memory.jsonl").write_text("corrupted\n", encoding="utf-8")

        # Restore must succeed using manifest.json
        res = restore_migration_p14(self.workspace, backup_path)
        self.assertTrue(res["verified"])
        self.assertEqual((self.workspace / "state" / "memory.jsonl").read_text(encoding="utf-8"), "orig memory\n")


if __name__ == "__main__":
    unittest.main()
