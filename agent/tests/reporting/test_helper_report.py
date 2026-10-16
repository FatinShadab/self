"""Helper reporting stays descriptive and host-only for eval results."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.reporting.report import _host_results_allowed, create_report


class HelperReportTests(unittest.TestCase):
    def _workspace(self, root: Path) -> None:
        (root / "logs").mkdir()
        (root / "state").mkdir()
        events = [
            {"event":"llm_call_attempt","model":"base"},
            {"event":"llm_call_attempt","model":"helper"},
            {"event":"llm_call_completed","model":"base","total_tokens":12,"latency_ms":30},
            {"event":"llm_call_completed","model":"helper","total_tokens":8,"latency_ms":50},
            {"event":"llm_call_failed","model":"helper","error_type":"TimeoutError"},
        ]
        (root / "logs/actions.jsonl").write_text("\n".join(json.dumps(row) for row in events) + "\n")
        (root / "state/models.json").write_text('{"base_model":"base"}')
        decisions = [
            {"source":"agent_tool","model":"helper","task_type":"code"},
            {"source":"checkpoint:create_tool_critic","model":"base","origin":"model_choice"},
            {"source":"checkpoint:reflection","model":"base","origin":"default_after_parse_failure"},
        ]
        (root / "state/model_decisions.jsonl").write_text("\n".join(json.dumps(row) for row in decisions) + "\n")
        outcomes = [
            {"source":"agent_tool","provenance":"objective","signal":"cycle_completed","value":True},
            {"source":"task_baseline","provenance":"objective","signal":"cycle_completed","value":False},
            {"source":"agent_tool","provenance":"self_reported","signal":"usefulness","value":"used"},
        ]
        (root / "state/model_outcomes.jsonl").write_text("\n".join(json.dumps(row) for row in outcomes) + "\n")

    def test_helper_sections_and_host_provided_results(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._workspace(root)
            calibration = root / "calibration.txt"
            comparison = root / "ab.txt"
            calibration.write_text("overall_mean_spearman=0.500\n")
            comparison.write_text("Pooled on-minus-off success difference=+0.100\n")
            with patch("agent.reporting.report._host_results_allowed", return_value=True):
                report = create_report(root, advance_cursor=False,
                                       calibration_file=calibration, ab_comparison_file=comparison)
            self.assertIn("helper: calls=1, total tokens 8", report)
            self.assertIn("helper / code: 1", report)
            self.assertIn("Checkpoint chose base: 2/2; forced defaults: 1/2", report)
            self.assertIn("delegated objective cycle_completed: n=1 true=1/1", report)
            self.assertIn("non-delegated objective cycle_completed: n=1 true=0/1", report)
            self.assertIn("delegated self_reported usefulness: n=1", report)
            self.assertIn("overall_mean_spearman=0.500", report)
            self.assertIn("Pooled on-minus-off", report)

    def test_container_never_reads_supplied_eval_files(self):
        self.assertFalse(_host_results_allowed())
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._workspace(root)
            calibration = root / "eval-calibration.txt"
            comparison = root / "eval-ab.txt"
            calibration.write_text("private calibration")
            comparison.write_text("private comparison")
            original = Path.read_text

            def guarded(path, *args, **kwargs):
                if path in {calibration, comparison}:
                    raise AssertionError("agent container read a host result")
                return original(path, *args, **kwargs)

            with patch.object(Path, "read_text", guarded):
                report = create_report(root, advance_cursor=False,
                                       calibration_file=calibration, ab_comparison_file=comparison)
            self.assertIn("Latest calibration: no data yet (host-only).", report)
            self.assertNotIn("private calibration", report)

    def test_no_data_messages(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "logs").mkdir()
            with patch("agent.reporting.report._host_results_allowed", return_value=True):
                report = create_report(root, advance_cursor=False)
            self.assertIn("Calls, tokens, latency, failures by model: no data yet.", report)
            self.assertIn("Latest calibration: no data yet.", report)
            self.assertIn("Latest A/B comparison: no data yet.", report)
