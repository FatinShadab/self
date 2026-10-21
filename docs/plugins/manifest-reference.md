# Plugin Manifest Reference (`plugin.json`)

Every plugin must include a `plugin.json` manifest file at the root of its directory. The manifest defines the plugin's metadata, tools, sensors, actions, permissions, and compatibility requirements.

---

## 1. Complete Manifest Schema

Below is an example illustrating all supported manifest fields:

```json
{
  "name": "example_plugin",
  "version": "1.0.0",
  "core_api": ">=1.0.0,<2.0.0",
  "kind": "both",
  "description": "Demonstrates the complete manifest specification.",
  "tools": [
    {
      "name": "echo_tool",
      "description": "Echoes an input message.",
      "input_schema": {
        "type": "object",
        "properties": {
          "message": {
            "type": "string",
            "description": "Text to echo"
          }
        },
        "required": ["message"]
      }
    }
  ],
  "sensors": [
    {
      "name": "status_sensor",
      "description": "Observes operational metrics.",
      "risk_class": "reads",
      "reversible": true,
      "required_permission_level": "L0"
    }
  ],
  "actions": [
    {
      "name": "apply_patch",
      "description": "Applies a reversible configuration change.",
      "risk_class": "executes",
      "reversible": true,
      "required_permission_level": "L1"
    }
  ],
  "starting_goal_seeds": [
    "Verify plugin environment and record baseline metrics."
  ],
  "embodiment": "I have specialized example tools and sensors active.",
  "identity_notes": [
    "I focus on demonstrating full manifest field coverage."
  ],
  "state_dir": "state",
  "declared_needs": {
    "env_vars": [],
    "mounts": []
  },
  "tests_entry_point": "tests/test_plugin.py"
}
```

---

## 2. Field Specifications

### Top-Level Fields

| Field | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `name` | `string` | **Yes** | Unique alphanumeric identifier (`^[a-zA-Z0-9_-]+$`). Cannot start with `_` or `.`. |
| `version` | `string` | **Yes** | Semantic version string of the plugin (`X.Y.Z`). |
| `core_api` | `string` | **Yes** | Range expression defining compatible core API versions (e.g. `">=1.0,<2.0"`). A missing or empty `core_api` field is strictly rejected. |
| `kind` | `string` | **Yes** | Plugin classification: must be `"body"`, `"skill"`, or `"both"`. |
| `description` | `string` | **Yes** | Human-readable explanation of what the plugin provides. |
| `tools` | `list[object]` | **Yes** | List of tool definitions exposed to the agent loop. |
| `sensors` | `list[object]` | **Yes** | List of sensor definitions for passive environment telemetry. |
| `actions` | `list[object]` | **Yes** | List of action definitions for environmental operations. |
| `starting_goal_seeds` | `list[string]` | **Yes** | Initial goal seeds added to the plan when the plugin is enabled. |
| `embodiment` | `string` | **Yes** | System prompt description of the operational embodiment. |
| `identity_notes` | `list[string]` | No | Optional persona notes injected while the plugin is active. |
| `state_dir` | `string` | No | Relative path for private plugin state storage (default: `"state"`). Absolute paths or `..` traversals are rejected. |
| `declared_needs` | `object` | No | Optional declared prerequisites (`env_vars`: `list[string]`, `mounts`: `list[string]`). |
| `tests_entry_point` | `string` | No | Relative path to the test module (default: `"tests/test_plugin.py"`). |

---

### Tool Object Schema

Each entry in `tools` represents a callable function:

```json
{
  "name": "greet",
  "description": "Returns a greeting string.",
  "input_schema": {
    "type": "object",
    "properties": {
      "greeting": {"type": "string", "default": "Hello"}
    }
  }
}
```

- `name` (`string`, required): Tool identifier. Must not collide with core built-in tools. Tools are exposed to the model as `<plugin_name>.<tool_name>`.
- `description` (`string`, required): Tool description explaining its purpose to the model.
- `input_schema` (`object`, optional): JSON Schema object defining arguments accepted by the tool.

---

### Sensor Object Schema

Each entry in `sensors` represents a passive observation point:

```json
{
  "name": "battery_level",
  "description": "Reads current battery voltage and percentage.",
  "risk_class": "reads",
  "reversible": true,
  "required_permission_level": "L0"
}
```

- `name` (`string`, required): Unique sensor identifier.
- `description` (`string`, required): Sensor explanation.
- `risk_class` (`string`, required): Must be one of `"reads"`, `"writes"`, `"executes"`, `"network"`. For sensors, this is typically `"reads"`.
- `reversible` (`boolean`, required): Must be `true` for passive sensors.
- `required_permission_level` (`string`, required): Canonical permission level (e.g. `"L0"` or `"read_only"`).

---

### Action Object Schema

Each entry in `actions` represents an active environmental operation:

```json
{
  "name": "reset_connection",
  "description": "Re-establishes the network socket session.",
  "risk_class": "executes",
  "reversible": true,
  "required_permission_level": "L1"
}
```

- `name` (`string`, required): Action identifier.
- `description` (`string`, required): Description of the operation.
- `risk_class` (`string`, required): Must be one of `"reads"`, `"writes"`, `"executes"`, `"network"`.
- `reversible` (`boolean`, required): Whether the action's effects can be programmatically undone.
- `required_permission_level` (`string`, required): Required permission level (`"L0"`, `"L1"`, `"L2"`, `"L3"`).

---

## 3. Core API Range Syntax

The `core_api` field specifies compatible core versions using a dependency-free range syntax:

| Syntax Example | Meaning |
| :--- | :--- |
| `">=1.0,<2.0"` | Any core version 1.x (greater than or equal to 1.0.0, strictly less than 2.0.0) |
| `">=1.0.0"` | Core version 1.0.0 or higher |
| `"^1.0.0"` | Semver compatible with 1.0.0 (allows minor and patch updates: `>=1.0.0,<2.0.0`) |
| `"~1.1.0"` | Semver patch-level compatibility (allows patch updates: `>=1.1.0,<1.2.0`) |
| `"1.0.0"` or `"==1.0.0"` | Exact version match |
| `"*"` or `"any"` | Accepts any core API version |

Multiple clauses can be combined with commas. All clauses must evaluate to true.

---

## 4. Semantic Versioning for Core API

Changes to the core engine follow Semantic Versioning (SemVer 2.0.0):

- **Major Bump (X.0.0 - Breaking Changes):**
  - Renaming, removing, or changing signatures of plugin hooks (`on_enable`, `on_disable`).
  - Removing or altering required manifest schema fields.
  - Modifying the tool dispatch envelope or observation return formats.
  - Breaking changes to permission levels or broker interfaces.
  - Changing private plugin state layout conventions.

- **Minor Bump (1.X.0 - Additive Changes):**
  - Adding optional fields to the manifest schema.
  - Adding new optional plugin lifecycle hooks or helper utilities.
  - Adding new CLI subcommands or inspection flags.
  - Adding non-breaking permission levels or risk classes.

- **Patch Bump (1.0.X - Fixes and Optimizations):**
  - Backwards-compatible bug fixes in plugin discovery, manifest parsing, or error formatting.
  - Performance improvements in hash computation or cycle boundary synchronization.
  - Documentation clarifications.
