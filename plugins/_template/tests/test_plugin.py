"""Unit tests for the template plugin."""
from __future__ import annotations

import unittest
from pathlib import Path

# When testing in isolation or under a real plugin name, import from the local plugin module
try:
    from .plugin import on_disable, on_enable, sample_action, sample_sensor, sample_tool
except ImportError:
    import sys
    plugin_dir = Path(__file__).resolve().parent.parent
    if str(plugin_dir) not in sys.path:
        sys.path.insert(0, str(plugin_dir))
    from plugin import on_disable, on_enable, sample_action, sample_sensor, sample_tool


class TestTemplatePlugin(unittest.TestCase):
    """Test suite verifying template plugin tools, sensors, and actions."""

    def test_sample_tool_echoes_message(self) -> None:
        result = sample_tool(message="hello world")
        self.assertTrue(result.get("ok"))
        self.assertEqual(result.get("echo"), "hello world")
        self.assertEqual(result.get("status"), "received")

    def test_sample_tool_handles_invalid_input(self) -> None:
        result = sample_tool(message=12345)  # type: ignore[arg-type]
        self.assertFalse(result.get("ok"))
        self.assertIn("error", result)

    def test_sample_sensor_reports_telemetry(self) -> None:
        result = sample_sensor()
        self.assertTrue(result.get("ok"))
        self.assertTrue(result.get("operational"))
        self.assertEqual(result.get("mode"), "simulated")
        self.assertEqual(result.get("metric"), 42.0)

    def test_sample_action_executes(self) -> None:
        result = sample_action(parameter="custom_value")
        self.assertTrue(result.get("ok"))
        self.assertEqual(result.get("parameter"), "custom_value")
        self.assertTrue(result.get("applied"))

    def test_lifecycle_hooks(self) -> None:
        ctx = {"name": "_template", "version": "1.0.0"}
        # Verify on_enable and on_disable execute without unhandled exceptions
        on_enable(ctx)
        on_disable(ctx)


if __name__ == "__main__":
    unittest.main()
