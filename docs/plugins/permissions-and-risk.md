# Permissions and Risk Classification

Plugins declare their required permissions and risk categories. This allows human operators to govern external capabilities safely without placing blind trust in model outputs.

---

## 1. Permission Hierarchy (L0 to L3)

The core mediates operations through a 4-tier permission hierarchy:

| Level | Name | Scope & Operational Meaning | Default Policy |
| :---: | :--- | :--- | :---: |
| **L0** | **Observe** | Read-only observation, telemetry, and querying. Cannot alter any state or external system. | **ALLOW** |
| **L1** | **Reversible Change** | Changes that are bounded and programmatically reversible (e.g. temporary scratch files, quarantine actions with clean undo hooks). | **DENY** until granted |
| **L2** | **Irreversible Change**| Destructive or permanent state modifications (e.g. direct file deletion, arbitrary shell commands, non-rollback updates). | **DENY** until granted |
| **L3** | **Actuation** | Environmental boundary transitions and physical actuation. | **DENY** until granted |

---

## 2. Risk Classes

Every sensor and action must declare one of four standard risk classes:

1. **`reads`:**
   Passive observation of internal or external state. No mutation of data or environments occurs. Example: reading temperature telemetry or file metadata.

2. **`writes`:**
   Creation or alteration of state, files, or local configuration records.

3. **`executes`:**
   Process execution, subshell spawning, or dynamic evaluation.

4. **`network`:**
   Outbound network transmissions, API requests, or socket connections.

---

## 3. Reversibility

Every declared sensor and action specifies a boolean `reversible` flag in `plugin.json`:

- `reversible: true`: The operation maintains an explicit rollback path or undo hook. If an operation fails midway, changes can be cleanly restored to their prior state.
- `reversible: false`: The operation produces irreversible side effects.

Sensors must always declare `reversible: true`.

---

## 4. How the Human Operator Grants Permissions

All operations above `L0` are denied by default. The agent cannot grant itself permissions or bypass the permission layer.

Human operators configure permission grants in `/config/permissions.json` (mounted read-only into the agent container):

```json
{
  "default_level": "L0",
  "grants": {
    "plugin:my_specialization": "L1"
  },
  "action_grants": {
    "my_specialization.custom_action": "L1"
  }
}
```

- **Actor Grants (`grants`):**
  Sets the maximum permission level permitted for an actor (e.g., `"plugin:<name>"`).
- **Action Grants (`action_grants`):**
  Sets specific permission grants for individual namespaced actions.

---

## 5. Implementation Status and Enforcement Differences

What the code actually enforces:
1. **Default Deny:** The permission broker strictly denies any action with level > `L0` unless explicitly granted in `/config/permissions.json`.
2. **Panic on Denials:** Repeated ungranted permission attempts (default threshold: 3 denials in a 1-minute window) trip a panic circuit breaker that halts execution.
3. **Non-Interactive Tool Execution:** Autonomous cycles execute tools non-interactively. If an LLM attempts an ungranted `L1` or `L2` operation without prior operator configuration in `permissions.json`, the operation is denied and an error observation is returned to the model.

Planned but not yet implemented:
- **Interactive Mid-Turn Human Approval:** A dynamic human-in-the-loop prompt pausing the agent mid-cycle to request real-time human authorization for individual tool invocations is planned for future releases. Currently, all grants must be pre-configured in `/config/permissions.json`.

---

## 6. Limits of Validation

Static analysis and schema checks in `validate_plugin` are strictly advisory:
- **Bypassable static checks:** Static AST parsing and text regexes cannot detect obfuscated or dynamic behavior, including:
  - Dynamic imports (such as `__import__("socket")` or `importlib.import_module(...)`).
  - Dynamic attribute access on modules (such as `getattr(sys.modules["os"], "system")`).
  - Runtime string construction for secret filenames or sensitive endpoints (e.g. `"".join(["/", "etc", "/", "shadow"])` or base64 decoding).
- **The real security controls:** Because static checks are advisory, real enforcement relies on defense-in-depth:
  1. **Human Governance:** Human review of diffs and explicit promotion via `/plugins promote` and `/plugins enable`.
  2. **Cryptographic Hash Pinning:** Immutable SHA-256 content verification recorded in human-owned `/config/plugins.json`.
  3. **Runtime Permission Broker:** Mandatory broker checks and L0-L3 permission verification on every action invocation.
  4. **Container Isolation:** Unprivileged container runtime environment without host filesystem access or elevated capabilities.
