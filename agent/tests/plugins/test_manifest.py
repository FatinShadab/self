"""Unit tests for plugin manifest schema and compatibility validation."""
from __future__ import annotations

import unittest
from pathlib import Path

from agent.plugins.manifest import (
    CORE_API_VERSION,
    PluginManifestValidationError,
    is_core_api_compatible,
    parse_manifest,
)


class PluginManifestTests(unittest.TestCase):
    def test_sample_hello_manifest_parses_successfully(self) -> None:
        manifest_path = Path(__file__).resolve().parents[2] / "plugins" / "hello" / "plugin.json"
        self.assertTrue(manifest_path.exists())
        manifest = parse_manifest(manifest_path)
        self.assertEqual(manifest.name, "hello")
        self.assertEqual(manifest.version, "0.1.0")
        self.assertEqual(manifest.kind, "skill")
        self.assertEqual(len(manifest.tools), 1)
        self.assertEqual(manifest.tools[0]["name"], "greet")
        self.assertEqual(len(manifest.sensors), 1)
        self.assertEqual(manifest.sensors[0].risk_class, "reads")
        self.assertTrue(manifest.sensors[0].reversible)
        self.assertEqual(len(manifest.actions), 1)
        self.assertEqual(manifest.actions[0].risk_class, "executes")
        self.assertTrue(len(manifest.starting_goal_seeds) >= 1)
        self.assertIn("hello capability", manifest.embodiment)

    def test_core_api_version_compatibility(self) -> None:
        self.assertTrue(is_core_api_compatible("0.1.0", "0.1.0"))
        self.assertTrue(is_core_api_compatible("*", "0.1.0"))
        self.assertTrue(is_core_api_compatible(">=0.1.0,<1.0.0", "0.1.0"))
        self.assertTrue(is_core_api_compatible("^0.1.0", "0.1.0"))
        self.assertFalse(is_core_api_compatible(">=1.0.0", "0.1.0"))
        self.assertFalse(is_core_api_compatible("<0.1.0", "0.1.0"))
        self.assertFalse(is_core_api_compatible("0.2.0", "0.1.0"))

    def test_missing_required_fields_raise_validation_error(self) -> None:
        base = {
            "name": "valid_name",
            "version": "1.0.0",
            "core_api": CORE_API_VERSION,
            "kind": "skill",
            "description": "desc",
            "tools": [{"name": "t1"}],
            "sensors": [{"name": "s1", "description": "", "risk_class": "reads", "reversible": True, "required_permission_level": "read_only"}],
            "actions": [{"name": "a1", "description": "", "risk_class": "executes", "reversible": False, "required_permission_level": "workspace"}],
            "starting_goal_seeds": ["seed 1"],
            "embodiment": "I have skills.",
        }

        # Missing name
        bad = dict(base)
        bad.pop("name")
        with self.assertRaises(PluginManifestValidationError):
            parse_manifest(bad)

        # Invalid name characters
        bad = dict(base, name="bad name with spaces!")
        with self.assertRaises(PluginManifestValidationError):
            parse_manifest(bad)

        # Invalid kind
        bad = dict(base, kind="magic")
        with self.assertRaises(PluginManifestValidationError):
            parse_manifest(bad)

        # Incompatible core_api
        bad = dict(base, core_api=">=99.0.0")
        with self.assertRaises(PluginManifestValidationError):
            parse_manifest(bad)

        # Sensor invalid risk_class
        bad = dict(base, sensors=[{"name": "s1", "risk_class": "explosive", "reversible": True, "required_permission_level": "root"}])
        with self.assertRaises(PluginManifestValidationError):
            parse_manifest(bad)

        # Action missing reversible flag
        bad = dict(base, actions=[{"name": "a1", "risk_class": "executes", "required_permission_level": "workspace"}])
        with self.assertRaises(PluginManifestValidationError):
            parse_manifest(bad)

        # Missing embodiment
        bad = dict(base, embodiment="")
        with self.assertRaises(PluginManifestValidationError):
            parse_manifest(bad)
