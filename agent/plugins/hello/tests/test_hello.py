"""Unit tests for the hello plugin."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

try:
    from agent.plugins.hello.plugin import greet, on_disable, on_enable
except ImportError:
    plugin_dir = Path(__file__).resolve().parent.parent
    if str(plugin_dir) not in sys.path:
        sys.path.insert(0, str(plugin_dir))
    from plugin import greet, on_disable, on_enable


class HelloPluginTests(unittest.TestCase):
    def test_greet_default(self) -> None:
        result = greet()
        self.assertTrue(result["ok"])
        self.assertEqual(result["message"], "Hello, from hello plugin!")

    def test_greet_custom(self) -> None:
        result = greet("Hi")
        self.assertTrue(result["ok"])
        self.assertEqual(result["message"], "Hi, from hello plugin!")

    def test_lifecycle_hooks(self) -> None:
        on_enable({})
        on_disable({})


if __name__ == "__main__":
    unittest.main()
