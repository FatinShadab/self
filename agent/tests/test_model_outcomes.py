from __future__ import annotations

import io
import json
import tempfile
import threading
import unittest
from pathlib import Path

from event_log import EventLogger
from model_outcomes import ModelOutcomes, print_outcome_summary


class ModelOutcomeTests(unittest.TestCase):
    def test_concurrent_appends_preserve_distinct_provenance_and_call_ids(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logger = EventLogger(root / "logs" / "actions.jsonl")
            first = ModelOutcomes(root, logger)
            second = ModelOutcomes(root, logger)
            def write(store, start):
                for number in range(start, start + 50):
                    store.append(f"call-{number}", "helper", "agent_tool",
                                 "tool_registration_success", number % 2 == 0,
                                 "objective", session_id="session")
            threads = [threading.Thread(target=write, args=(first, 0)),
                       threading.Thread(target=write, args=(second, 50))]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            rows = [json.loads(line) for line in first.path.read_text().splitlines()]
            self.assertEqual(len(rows), 100)
            self.assertEqual(len({row["call_id"] for row in rows}), 100)
            self.assertEqual({row["provenance"] for row in rows}, {"objective"})
            first.append("call-0", "helper", "agent_tool", "usefulness", "used",
                         "self_reported", session_id="session")
            rows = [json.loads(line) for line in first.path.read_text().splitlines()]
            self.assertEqual(rows[-1]["provenance"], "self_reported")
            stream = io.StringIO()
            print_outcome_summary(root, output=stream)
            self.assertIn("objective tool_registration_success: 50/100", stream.getvalue())
            self.assertIn('self_reported usefulness: n=1 {"used": 1}', stream.getvalue())

    def test_baseline_and_decision_linking(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logger = EventLogger(root / "logs" / "actions.jsonl")
            from model_registry import ModelRegistry
            from model_decisions import ModelDecisions
            registry = ModelRegistry(root, logger, "base", ["base", "helper"])
            decisions = ModelDecisions(root, logger, registry, None, "session")
            decisions.start_task("task-one")
            decisions.record_task_outcomes("task-one", completed=True, iterations=2,
                                           tool_errors=0, provider_errors=0)
            rows = [json.loads(line) for line in decisions.outcomes.path.read_text().splitlines()]
            self.assertEqual({row["source"] for row in rows}, {"task_baseline"})
            self.assertEqual({row["provenance"] for row in rows}, {"objective"})
            self.assertIn("cycle_completed", {row["signal"] for row in rows})
            decisions._track_call("decision-one", "helper", "checkpoint:create_tool_critic")
            decisions.record_tool_outcome(tool_name="tool", attempt=1,
                                          critic_call_id="decision-one", critic_model="helper",
                                          critic_approved=False, tests_passed=True,
                                          registered=False)
            rows = [json.loads(line) for line in decisions.outcomes.path.read_text().splitlines()]
            linked = [row for row in rows if row["call_id"] == "decision-one"]
            self.assertTrue(linked)
            self.assertTrue(all(row["provenance"] == "objective" for row in linked))
            self.assertTrue(any(row["signal"] == "critic_flagged_but_tests_passed"
                                and row["value"] for row in linked))


if __name__ == "__main__":
    unittest.main()
