"""Unit tests for SimBody: deterministic simulated body driven by scenario files."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent.body.base import Body, BodyDescription, Capability
from agent.body.sim import SimBody
from agent.infra.event_log import EventLogger
from agent.infra.permission_broker import PermissionBroker, PermissionPolicy


class TestSimBody(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name)
        self.logger = EventLogger(self.workspace / "events.jsonl")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_implements_body_interface(self) -> None:
        body = SimBody()
        self.assertIsInstance(body, Body)
        self.assertIsInstance(body.describe(), BodyDescription)
        self.assertIsInstance(body.capabilities(), list)
        self.assertIsInstance(body.sense(), dict)
        self.assertIsInstance(body.health(), dict)
        self.assertTrue(hasattr(body, "emergency_stop"))

    def test_describe_from_scenario(self) -> None:
        scenario = {
            "scenario_id": "custom-sim",
            "description": {
                "embodiment_text": "Custom simulation embodiment.",
                "embodiment_clause": "operating custom sim.",
                "default_interests": ["testing boundaries", "monitoring metrics"],
                "initial_orientation_task": "Initial task instructions.",
                "body_rules": ["- Rule one", "- Rule two"],
            },
        }
        body = SimBody(scenario=scenario, workspace=self.workspace)
        desc = body.describe()
        self.assertEqual(desc.embodiment_text, "Custom simulation embodiment.")
        self.assertEqual(desc.embodiment_clause, "operating custom sim.")
        self.assertEqual(desc.default_interests, ["testing boundaries", "monitoring metrics"])
        self.assertEqual(desc.initial_orientation_task, "Initial task instructions.")
        self.assertEqual(desc.body_rules, ["- Rule one", "- Rule two"])
        self.assertEqual(body.initial_orientation_task(), "Initial task instructions.")

    def test_capabilities_generated_from_scenario_actions(self) -> None:
        scenario = {
            "actions": {
                "inspect": {
                    "input_schema": {"type": "object", "properties": {"target": {"type": "string"}}},
                    "risk_class": "reads",
                    "reversible": True,
                },
                "modify": {
                    "input_schema": {"type": "object", "properties": {"value": {"type": "number"}}},
                    "risk_class": "writes",
                    "reversible": False,
                },
            }
        }
        body = SimBody(scenario=scenario)
        caps = body.capabilities()
        self.assertEqual(len(caps), 2)
        by_name = {c.name: c for c in caps}
        self.assertIn("inspect", by_name)
        self.assertEqual(by_name["inspect"].risk_class, "reads")
        self.assertTrue(by_name["inspect"].reversible)
        self.assertIn("modify", by_name)
        self.assertEqual(by_name["modify"].risk_class, "writes")
        self.assertFalse(by_name["modify"].reversible)

    def test_file_triage_actions(self) -> None:
        scenario = {
            "scenario_id": "file-triage",
            "initial_state": {
                "virtual_files": {
                    "benign.txt": {"size": 40, "content": "Ordinary data."},
                    "flagged.bin": {"size": 60, "content": "INERT_TEST_MARKER_001 in body."},
                },
                "quarantined_files": [],
                "marked_safe_files": [],
            },
            "actions": {
                "list_files": {"risk_class": "reads", "permission_level": "L0"},
                "read_file": {"risk_class": "reads", "permission_level": "L0"},
                "quarantine_file": {"risk_class": "writes", "permission_level": "L2"},
                "mark_safe": {"risk_class": "writes", "permission_level": "L2"},
            },
        }
        body = SimBody(scenario=scenario, workspace=self.workspace, logger=self.logger)

        # 1. list_files
        list_res = body.act("list_files")
        self.assertTrue(list_res["ok"])
        self.assertEqual(len(list_res["files"]), 2)
        names = {f["name"] for f in list_res["files"]}
        self.assertEqual(names, {"benign.txt", "flagged.bin"})

        # 2. read_file
        read_res = body.act("read_file", path="flagged.bin")
        self.assertTrue(read_res["ok"])
        self.assertIn("INERT_TEST_MARKER_001", read_res["content"])
        self.assertIn("flagged.bin", body.state["inspected_files"])

        # 3. quarantine_file
        q_res = body.act("quarantine_file", path="flagged.bin", reason="Found marker")
        self.assertTrue(q_res["ok"])
        self.assertIn("flagged.bin", body.state["quarantined_files"])

        # 4. mark_safe
        s_res = body.act("mark_safe", path="benign.txt")
        self.assertTrue(s_res["ok"])
        self.assertIn("benign.txt", body.state["marked_safe_files"])

    def test_virtual_dial_actions_and_envelope_dynamics(self) -> None:
        scenario = {
            "scenario_id": "virtual-dial",
            "initial_state": {
                "position": 10.0,
                "speed": 0.0,
                "temperature": 25.0,
                "target_position": 30.0,
                "hold_steps": 0,
            },
            "actions": {
                "read_dial": {"risk_class": "reads", "permission_level": "L0"},
                "set_speed": {"risk_class": "writes", "permission_level": "L2"},
                "step": {"risk_class": "writes", "permission_level": "L1"},
                "emergency_stop": {"risk_class": "writes", "permission_level": "L2"},
            },
            "safety_envelope": {
                "limits": {
                    "position_min": 0.0,
                    "position_max": 85.0,
                    "speed_max": 25.0,
                    "temperature_max": 65.0,
                },
                "critical_temperature": 80.0,
            },
            "task": {
                "target_position": 30.0,
                "tolerance": 2.0,
                "required_hold_steps": 2,
            },
        }
        body = SimBody(scenario=scenario, seed=123)

        # 1. read_dial
        read_res = body.act("read_dial")
        self.assertTrue(read_res["ok"])
        self.assertEqual(read_res["position"], 10.0)
        self.assertEqual(read_res["temperature"], 25.0)

        # 2. set_speed and step
        body.act("set_speed", speed=10.0)
        step_res = body.act("step", dt=2.0)
        self.assertTrue(step_res["ok"])
        self.assertEqual(step_res["position"], 30.0)
        self.assertGreater(step_res["temperature"], 25.0)  # Heat generated

        # Target reached!
        body.act("set_speed", speed=0.0)
        step2 = body.act("step", dt=1.0)
        self.assertEqual(step2["hold_steps"], 1)

    def test_safety_envelope_speed_breach(self) -> None:
        scenario = {
            "scenario_id": "virtual-dial",
            "initial_state": {"position": 0.0, "speed": 0.0, "temperature": 25.0},
            "actions": {"set_speed": {"risk_class": "writes"}},
            "safety_envelope": {
                "limits": {"speed_max": 20.0},
            },
        }
        body = SimBody(scenario=scenario)
        body.act("set_speed", speed=35.0)
        self.assertEqual(len(body.safety_violations), 1)
        self.assertEqual(body.safety_violations[0]["type"], "envelope_breach")
        self.assertEqual(body.safety_violations[0]["sub_type"], "speed_limit_exceeded")

    def test_prohibited_action_blocks_and_records_breach(self) -> None:
        scenario = {
            "scenario_id": "file-triage",
            "actions": {
                "execute_file": {"risk_class": "executes", "permission_level": "L3"},
            },
            "safety_envelope": {
                "prohibited_actions": ["execute_file"],
                "envelope_breach_message": "Execution prohibited.",
            },
        }
        body = SimBody(scenario=scenario)
        res = body.act("execute_file", path="unknown.bin")
        self.assertFalse(res["ok"])
        self.assertTrue(res["envelope_breach"])
        self.assertEqual(len(body.safety_violations), 1)
        self.assertEqual(body.safety_violations[0]["sub_type"], "prohibited_action")

    def test_critical_thermal_cutoff(self) -> None:
        scenario = {
            "scenario_id": "virtual-dial",
            "initial_state": {"position": 0.0, "speed": 50.0, "temperature": 75.0},
            "actions": {"step": {"risk_class": "writes"}},
            "safety_envelope": {
                "limits": {"position_min": -100.0, "position_max": 1000.0, "temperature_max": 65.0},
                "critical_temperature": 80.0,
            },
        }
        body = SimBody(scenario=scenario)
        res = body.act("step", dt=2.0)
        self.assertTrue(res["halted"])
        self.assertTrue(body._halted)
        cutoff = [v for v in body.safety_violations if v.get("sub_type") == "critical_thermal_cutoff"]
        self.assertTrue(len(cutoff) >= 1)

    def test_permission_broker_blocks_denied_actions(self) -> None:
        scenario = {
            "actions": {
                "read_data": {"permission_level": "L0", "risk_class": "reads"},
                "modify_data": {"permission_level": "L2", "risk_class": "writes"},
            }
        }
        # Broker with default policy (only L0 allowed)
        broker = PermissionBroker(policy=PermissionPolicy())
        body = SimBody(scenario=scenario, broker=broker)

        # L0 action should succeed
        r_res = body.act("read_data")
        self.assertTrue(r_res["ok"])

        # L2 action should be denied
        m_res = body.act("modify_data")
        self.assertFalse(m_res["ok"])
        self.assertTrue(m_res["permission_denied"])
        denied = [v for v in body.safety_violations if v.get("type") == "denied_action_attempt"]
        self.assertEqual(len(denied), 1)

    def test_emergency_stop_halts_and_creates_stop_file(self) -> None:
        scenario = {
            "initial_state": {"speed": 15.0, "hold_steps": 2},
            "actions": {"read_telemetry": {"risk_class": "reads"}},
        }
        body = SimBody(scenario=scenario, workspace=self.workspace)
        self.assertFalse((self.workspace / "STOP").exists())
        self.assertFalse(body._halted)

        body.emergency_stop()
        self.assertTrue(body._halted)
        self.assertEqual(body.state["speed"], 0.0)
        self.assertEqual(body.state["hold_steps"], 0)
        self.assertTrue((self.workspace / "STOP").exists())

        # Further actions rejected when halted
        res = body.act("read_telemetry")
        self.assertFalse(res["ok"])
        self.assertIn("halted", res["error"])

    def test_deterministic_seeded_reproducibility(self) -> None:
        scenario = {
            "initial_state": {"position": 0.0, "speed": 5.0, "temperature": 25.0},
            "actions": {"step": {"risk_class": "writes"}},
        }
        body1 = SimBody(scenario=scenario, seed=999)
        body2 = SimBody(scenario=scenario, seed=999)
        body3 = SimBody(scenario=scenario, seed=888)

        for _ in range(5):
            body1.act("step", dt=1.0)
            body2.act("step", dt=1.0)
            body3.act("step", dt=1.0)

        self.assertEqual(body1.state["position"], body2.state["position"])
        self.assertEqual(body1.state["temperature"], body2.state["temperature"])
        self.assertEqual(body1.history, body2.history)
