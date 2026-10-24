# Permissions and Risk Classification

Plugins declare their required permissions and risk categories. This allows human operators to govern external capabilities safely without placing blind trust in model outputs.

---

## 1. Permission Hierarchy (L0 to L3)

The core mediates operations through a 4-tier permission hierarchy:

| Level | Name | Scope & Operational Meaning | Plugin default |
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

The shipped policy gives SELF's built-in core actions an L3 ceiling and scoped L2 grants for body `run_shell` and `write_file`. Plugins default to L0 and cannot grant themselves permissions or bypass the broker.

SELF's built-in grants are configured in `/config/permissions.json` (mounted read-only into the agent container). The relevant shipped entries are:

```json
{
  "default_level": "L0",
  "grants": {
    "core": "L3",
    "body": "L0",
    "tools": "L0"
  },
  "action_grants": {
    "core:update_plan": "L3",
    "core:update_environment_map": "L3",
    "body:run_shell": "L2",
    "body:write_file": "L2"
  }
}
```

- **Actor Grants (`grants`):**
  Sets the maximum permission level permitted for an actor (e.g., `"plugins.my_specialization"`).
- **Action Grants (`action_grants`):**
  Sets specific permission grants for an actor and action (e.g., `"body:run_shell"`). These take precedence over actor grants.

For plugins, set a ceiling in the host-owned `config/plugins.json` entry after enabling and hash-pinning the plugin:

```json
{
  "plugins": {
    "my_specialization": {
      "enabled": true,
      "hash": "<64-character SHA-256 hash of approved plugin contents>",
      "permission_level": "L2"
    }
  }
}
```

Replace the hash placeholder with the actual 64-character SHA-256 pin. `permission_level` accepts L0, L1, L2, or L3. It is the maximum level for that plugin's declared tools; it does not change SELF's core or body grants. A missing, disabled, or unpinned entry cannot gain an elevated level. Plugin ceilings are refreshed at cycle boundaries. `config/permissions.json` still supports `plugins.<name>` grants when no per-plugin level is set. If both files set a plugin level, the `plugins.json` ceiling takes precedence.

---

## 5. Implementation Status and Enforcement Differences

What the code actually enforces:
1. **Policy Gates:** Core actions are granted through L3, and body shell/file-write actions have scoped L2 grants. Plugin actions above L0 require an explicit host-configured grant.
2. **Panic on Denials:** Five consecutive denied or failed actions trip a panic circuit breaker that halts execution. A denied action is counted once, not again as an execution failure.
3. **Non-Interactive Tool Execution:** Autonomous cycles offer only tools allowed by the current policy. If an ungranted `L1` or `L2` action is attempted through another path, the broker denies it and returns an error.

Planned but not yet implemented:
- **Interactive Mid-Turn Human Approval:** A dynamic human-in-the-loop prompt pausing the agent mid-cycle to request real-time human authorization for individual tool invocations is planned for future releases. Currently, grants must be pre-configured in host-owned `config/plugins.json` or `config/permissions.json`.

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
  4. **Container Isolation:** The default profile runs commands as root inside the container. Host exposure is limited to the writable workspace mount and read-only config mount; the optional hardened profile drops privileges and capabilities.

### 6.1 Audit Hooks vs. Container Security Boundary
The in-process PEP 578 audit hook inside `test_plugin` intercepts standard Python socket creation and `.env` file open calls. However, in-process hooks are an advisory speed bump: subprocess execution (`subprocess.run(["curl", ...])`), `ctypes` foreign-function calls, symlinks, or low-level file descriptors can bypass in-process hooks. The Docker container boundary controls host exposure; in the default profile, `workspace` is writable, `config` is read-only, and shell commands run as container root.
