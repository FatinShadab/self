# Plugin Authoring Guide

This guide walks through creating, developing, testing, and validating a new SELF specialization plugin from scratch.

---

## Step 1: Scaffold a New Plugin

Use the Plugin SDK CLI to generate a working plugin skeleton from the built-in template:

```bash
python -m agent.plugins new my_specialization
```

By default, this creates a new directory at `plugins/my_specialization` containing:

```
plugins/my_specialization/
├── plugin.json         # Manifest declaring tools, sensors, actions, and metadata
├── plugin.py           # Python handlers for tools, sensors, actions, and hooks
├── tests/              # Plugin unit tests
│   └── test_plugin.py  # Unit test suite
└── README.md           # Starter documentation
```

You can optionally specify a destination folder using `--dest`:

```bash
python -m agent.plugins new my_specialization --dest workspace/plugins
```

The `new` command validates the plugin identifier (letters, numbers, hyphens, and underscores) and refuses to overwrite any existing directory.

---

## Step 2: Configure the Manifest (`plugin.json`)

Open `plugin.json` and declare your plugin's metadata, tools, and sensors:

```json
{
  "name": "my_specialization",
  "version": "1.0.0",
  "core_api": ">=1.0.0,<2.0.0",
  "kind": "skill",
  "description": "Performs specialized data calculations and observations.",
  "tools": [
    {
      "name": "calculate_hash",
      "description": "Computes SHA-256 digest of input text.",
      "input_schema": {
        "type": "object",
        "properties": {
          "text": {"type": "string", "description": "Text to hash"}
        },
        "required": ["text"]
      }
    }
  ],
  "sensors": [
    {
      "name": "system_clock_sensor",
      "description": "Reads high-resolution UTC timestamp.",
      "risk_class": "reads",
      "reversible": true,
      "required_permission_level": "L0"
    }
  ],
  "actions": [],
  "starting_goal_seeds": [
    "Verify my_specialization tool availability."
  ],
  "embodiment": "I have specialized data computation tools available.",
  "identity_notes": [
    "I compute cryptographic digests using the calculate_hash tool."
  ],
  "state_dir": "state",
  "declared_needs": {
    "env_vars": [],
    "mounts": []
  },
  "tests_entry_point": "tests/test_plugin.py"
}
```

Key rules:
- **`core_api`:** Always declare your compatible core version range (e.g. `">=1.0.0,<2.0.0"`).
- **Tool Names:** Names must be lowercase alphanumeric identifiers. Do not prefix with the plugin name in the manifest; the core harness will automatically namespace them as `<plugin_name>.<tool_name>`.
- **Sensors:** Senses must be read-only (`risk_class: "reads"`, `required_permission_level: "L0"`).

---

## Step 3: Implement Tool and Sensor Logic (`plugin.py`)

Implement the callable functions declared in your manifest:

```python
"""Implementation of my_specialization plugin tools and sensors."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any


def calculate_hash(text: str = "") -> dict[str, Any]:
    """Compute SHA-256 hash of input text."""
    if not isinstance(text, str):
        return {"ok": False, "error": "text parameter must be a string"}
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return {"ok": True, "digest": digest, "length": len(text)}


def system_clock_sensor() -> dict[str, Any]:
    """Read the current UTC timestamp."""
    return {
        "ok": True,
        "utc_iso": datetime.now(timezone.utc).isoformat(),
    }


def on_enable(context: dict[str, Any]) -> None:
    """Invoked when the plugin is activated at a cycle boundary."""
    state_dir = context.get("state_dir")
    if state_dir:
        state_dir.mkdir(parents=True, exist_ok=True)


def on_disable(context: dict[str, Any]) -> None:
    """Invoked when the plugin is deactivated."""
    pass
```

---

## Step 4: Write Unit Tests (`tests/test_plugin.py`)

Create unit tests verifying your tools and edge cases:

```python
"""Unit tests for my_specialization."""
import unittest
from pathlib import Path
import sys

# Ensure plugin module can be imported
plugin_dir = Path(__file__).resolve().parent.parent
if str(plugin_dir) not in sys.path:
    sys.path.insert(0, str(plugin_dir))

from plugin import calculate_hash, system_clock_sensor


class TestMySpecialization(unittest.TestCase):
    def test_calculate_hash_valid(self):
        res = calculate_hash(text="hello")
        self.assertTrue(res["ok"])
        self.assertEqual(len(res["digest"]), 64)

    def test_calculate_hash_invalid(self):
        res = calculate_hash(text=123)  # type: ignore[arg-type]
        self.assertFalse(res["ok"])

    def test_sensor(self):
        res = system_clock_sensor()
        self.assertTrue(res["ok"])
        self.assertIn("utc_iso", res)


if __name__ == "__main__":
    unittest.main()
```

---

## Step 5: Statically Validate the Plugin

Run the SDK static validator:

```bash
python -m agent.plugins validate plugins/my_specialization
```

To output machine-readable JSON for automated scripts:

```bash
python -m agent.plugins validate plugins/my_specialization --json
```

The validator checks:
- Manifest JSON validity and complete required fields.
- `core_api` version compatibility.
- Namespacing and collision avoidance with core tools.
- Risk classes and permission levels.
- Non-empty unit test files under `tests/`.

---

## Step 6: Run Your Test Suite

Run unit tests directly:

```bash
python -m unittest discover -s plugins/my_specialization/tests -v
```

Once tests pass and validation succeeds, your plugin is ready for deployment.
