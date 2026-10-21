# Plugin Testing and Verification

Testing plugins thoroughly ensures they execute reliably, respect permission boundaries, and handle unexpected environment states gracefully.

---

## 1. Unit Testing with `unittest`

Every plugin must include unit tests located in its `tests/` directory (or the path declared in `tests_entry_point`).

### Writing Unit Tests

Plugin tests should verify:
- Happy paths for all exposed tools.
- Validation and error handling for malformed or missing arguments.
- Sensor output schemas and telemetry structure.
- State persistence within the plugin's designated state directory.

Example test suite (`tests/test_plugin.py`):

```python
import unittest
from pathlib import Path
import sys

plugin_dir = Path(__file__).resolve().parent.parent
if str(plugin_dir) not in sys.path:
    sys.path.insert(0, str(plugin_dir))

from plugin import sample_tool, sample_sensor


class TestPlugin(unittest.TestCase):
    def test_sample_tool_success(self):
        result = sample_tool(message="ping")
        self.assertTrue(result.get("ok"))
        self.assertEqual(result.get("echo"), "ping")

    def test_sample_tool_error_handling(self):
        result = sample_tool(message=None)  # type: ignore[arg-type]
        self.assertFalse(result.get("ok"))
        self.assertIn("error", result)

    def test_sample_sensor_observation(self):
        telemetry = sample_sensor()
        self.assertTrue(telemetry.get("ok"))
        self.assertIn("metric", telemetry)


if __name__ == "__main__":
    unittest.main()
```

Run tests with:

```bash
python -m unittest discover -s plugins/<plugin_name>/tests -v
```

---

## 2. Static Manifest and Code Validation

Before running integration tests, statically check your plugin with the SDK CLI:

```bash
python -m agent.plugins validate plugins/<plugin_name>
```

This ensures:
- All required manifest fields are present.
- `core_api` compatibility is satisfied.
- Tool names do not collide with built-in core tools.
- Declared permissions and risk levels conform to standards.
- Test files exist and are non-empty.

---

## 3. Simulation Testing with Simulated Bodies

For plugins that interact with simulated environments or external devices, tests should use simulated body adapters (`SimBody`) rather than live hardware:

- **Predictable Telemetry:** Simulated bodies provide deterministic sensor responses.
- **Safety Envelopes:** Actions can be tested against parameter limits (such as speed, range, or temperature thresholds) without risking physical side effects.
- **Reproducibility:** Seeded pseudo-randomness allows repeating edge cases and failure modes consistently.

---

## 4. Scenario-Based Testing

Plugins can be validated against structured benchmark scenarios:

1. **Task Success:** Did the plugin's tools enable the agent to accomplish the stated goal?
2. **Safety Violations:** Did the plugin attempt any actions exceeding its declared permission level?
3. **Observation Accuracy:** Were sensor reports consistent with the simulated environment ground truth?
4. **Resilience:** Did the plugin return clear error observations when supplied invalid parameters rather than crashing?
