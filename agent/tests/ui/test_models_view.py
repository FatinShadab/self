"""The /models text includes evidence, measurements, and decision origins."""
from __future__ import annotations

import unittest

from agent.ui.wake import format_models_snapshot


class ModelViewTests(unittest.TestCase):
    def test_models_view_has_registry_and_last_ten_origins(self):
        snapshot = {
            "registry": {"models":[{
                "name":"helper", "role":"helper", "status":"reachable",
                "agent_assessment":"Useful for code", "ratings":{"code":"high"},
                "measured_stats":{"calls":3,"failures":1},
            }]},
            "last_ten_decisions":[{"source":"checkpoint:create_tool_critic",
                                   "model":"helper", "origin":"model_choice",
                                   "task_type":"code"}],
        }
        output = format_models_snapshot(snapshot)
        self.assertIn("status=reachable", output)
        self.assertIn("assessment=Useful for code", output)
        self.assertIn('"code": "high"', output)
        self.assertIn("calls=3 failures=1", output)
        self.assertIn("origin=model_choice", output)
        self.assertIn("Last ten decisions", output)
