"""Section C: Replay tests against historical bad run shapes and oversized handoffs."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from agent.infra.permission_broker import PermissionLevel
from agent.tests.soak.harness import Invariants, ReplayProvider, SoakRunner


class SoakReplayTests(unittest.TestCase):
    """C1-C3 Replay of historical failure shapes against current code."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="soak_replay_")
        self.workspace = Path(self.temp_dir)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_c1_c2_real_run_shape_replay_30_cycles(self) -> None:
        """C1 & C2: 30-cycle replay of real failure sequence, oversized handoff, and tool churn."""
        state = self.workspace / "state"
        state.mkdir(parents=True)

        # 1. Seed workspace with real oversized (7,326 bytes / 16 repeats) handoff
        backup_handoff = Path("workspace/state/handoff.json.pre_autonomy_backup")
        if not backup_handoff.exists():
            # Synthetic oversized fallback if run in clean container without workspace state
            legacy_summary = "\n".join([f"Session complete after {i} cycle(s).\nTrying to do: shutdown reflection\nAchieved: exploring container." for i in range(16)])
            seeded_data = {
                "summary": legacy_summary,
                "plan": [{"step": "Inspect current state", "why": "Initial", "priority": 1, "status": "todo"}],
                "long_term_summary": "Extensive uncompressed log notes across multiple sessions. " * 150,
            }
            seeded_bytes = json.dumps(seeded_data, indent=2).encode("utf-8")
        else:
            seeded_bytes = backup_handoff.read_bytes()

        (state / "handoff.json").write_bytes(seeded_bytes)
        before_wake_len = len((state / "handoff.json").read_bytes())
        self.assertGreater(before_wake_len, 6_000, "Seed handoff must exceed 6,000 threshold to test compaction")

        # 2. Build SoakRunner with ReplayProvider
        runner = SoakRunner(workspace=self.workspace, max_iterations=30, seed=42)
        provider = ReplayProvider(logger=runner.coordinator.logger, total_replay_cycles=30)
        runner.provider = provider
        runner.coordinator._llm = provider
        runner.coordinator.broker.policy.action_grants["create_tool"] = PermissionLevel.L2
        runner.coordinator.broker.policy.action_grants["read_file"] = PermissionLevel.L0
        runner.coordinator.broker.panic_threshold = 100

        try:
            # 3. Assert current code bounds the handoff on first wake
            runner.coordinator.boot()
            first_wake_len = len((state / "handoff.json").read_bytes())
            self.assertLessEqual(first_wake_len, 6_000, f"Handoff on first wake ({first_wake_len} bytes) must be <= 6,000")
            overflow_file = state / "handoff_overflow.json"
            self.assertTrue(overflow_file.exists(), "Overflow file must be created to preserve unabridged record")
            self.assertGreater(len(overflow_file.read_bytes()), 6_000, "Overflow file must retain full historical handoff")

            # 4. Run full 30-cycle execution against ReplayProvider
            res = runner.coordinator.run()

            # 5. Assert clean termination and cycle count
            self.assertEqual(res.iterations, 30, f"Expected 30 iterations, got {res.iterations}")
            self.assertEqual(res.reason, "max_iterations", f"Expected finish reason 'max_iterations', got {res.reason}")

            # 6. Assert handoff size and repeat bounds
            final_handoff_bytes = len((state / "handoff.json").read_bytes())
            self.assertLessEqual(final_handoff_bytes, 6_000, f"Final handoff ({final_handoff_bytes} bytes) exceeded cap")
            final_text = (state / "handoff.json").read_text(encoding="utf-8")
            repeats = final_text.count("Session complete after")
            self.assertLessEqual(repeats, 1, f"Expected at most 1 'Session complete after', found {repeats}")

            # 7. Assert all 374 historical failure events were replayed
            self.assertEqual(sum(provider.replayed_llm_failures.values()), 374)
            self.assertEqual(provider.replayed_llm_failures.get("APIConnectionError"), 199)
            self.assertEqual(provider.replayed_llm_failures.get("InternalServerError"), 133)
            self.assertEqual(provider.replayed_llm_failures.get("APITimeoutError"), 21)
            self.assertEqual(provider.replayed_llm_failures.get("RateLimitError"), 19)

            # 8. Assert create_tool failure churn stopped and lessons recorded in memory
            lessons_file = self.workspace / "memory" / "lessons.jsonl"
            self.assertTrue(lessons_file.exists(), "Lessons must be recorded in memory/lessons.jsonl")
            lessons_lines = [l for l in lessons_file.read_text(encoding="utf-8").splitlines() if l.strip()]
            self.assertGreater(len(lessons_lines), 0, "Lessons must be recorded on repeated tool creation failures")

            # 9. Verify audit trail sequential verification
            valid, rec_count, err = runner.coordinator.audit_trail.verify()
            self.assertTrue(valid, f"Audit trail verification failed at {rec_count}: {err}")
        finally:
            runner.close()

    def test_c3_old_log_predates_plan_system(self) -> None:
        """C3: Verify historical run log lacked plan events, confirming replay is a stress test."""
        # Inspect fixture events
        fixture_path = Path(__file__).parent / "fixtures" / "real_run_shape.jsonl"
        self.assertTrue(fixture_path.exists(), "Fixture real_run_shape.jsonl must exist")

        with open(fixture_path, "r", encoding="utf-8") as f:
            fixture_events = [json.loads(line) for line in f if line.strip()]

        # The historical run had zero plan_updated and zero plan_unchanged events
        plan_events = [e for e in fixture_events if e.get("event") in {"plan_updated", "plan_unchanged"}]
        self.assertEqual(len(plan_events), 0, "Historical run shape must contain zero plan events")


if __name__ == "__main__":
    unittest.main()
