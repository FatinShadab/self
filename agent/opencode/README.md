# Opencode Delegation Subpackage

Delegation wrapper, availability status tracker, sandboxing, and safety safeguards for the optional [opencode](https://github.com/anomalyco/opencode) coding-agent CLI.

> [!IMPORTANT]
> Opencode is an optional capability. Self does not depend on it for its core reasoning loop, tools, or survival. If opencode is uninstalled, broken, or rate-limited, Self continues operating normally without interruption.

---

## Subpackage Layout

| File | Purpose | Key Exports |
|---|---|---|
| `status.py` | Provider availability tracking, classification, backoff, and health probing. | `OpencodeStatusTracker`, `classify_failure`, `parse_reset_time` |
| `sandbox.py` | Isolated repository sandboxes, minimal env construction, scope checks, and file protection. | `SandboxManager`, `build_opencode_env`, `is_protected_path` |
| `wrapper.py` | High-level orchestrator for delegation lifecycle: dispatch, verification, atomic apply, and rollback. | `OpencodeDelegator` |
| `tools.py` | Schema definitions and permission levels for registered agent tools. | `OPENCODE_TOOL_DEFINITIONS`, `OPENCODE_TOOL_PERMISSIONS` |
| `tests/fake_opencode.py` | Fake executable simulator for offline testing of all success and failure modes. | Mock CLI |
| `tests/` | Unit and integration tests for status, sandbox, and delegation tools. | Test suites |

---

## 1. Availability Status Tracking

Status tracking is handled by `OpencodeStatusTracker` in `status.py`. State is persisted in `state/opencode_status.json` and protected against concurrent modifications using the repository's cross-process file lock (`locked_file`).

### Provider States
Each provider (`groq`, `google`, `huggingface`) is tracked in one of five states:
- `not_configured`: No API key found in the environment (`OPENCODE_GROQ_API_KEY`, `OPENCODE_GOOGLE_API_KEY`, `OPENCODE_HF_TOKEN`). The provider is never queried.
- `unknown`: Key is present, but no calls or probes have run yet. Treated as candidate for delegation.
- `available`: Last call or probe succeeded.
- `throttled`: 429 rate limit or quota exceeded with a known or backoff-calculated `until` timestamp. Once `until` has elapsed, the state becomes `probe_due`.
- `invalid`: 401/403 unauthorized or invalid API key. Stays invalid until the key hash in the environment changes.

### Failure Classification & Backoff
`classify_failure(exit_code, output_text)` inspects exit code and output for known error patterns:
- **Throttled (429 / Rate limit)**: Backoff schedule: `1m -> 5m -> 15m -> 1h -> 6h` (capped at 6h), indexed by consecutive failures. If the response contains a reset hint (e.g. `retry in 30s` or `try again in 2m`), the parsed reset time takes precedence.
- **Daily Quota**: Exceeded daily billing or request limit. Does not attempt to guess provider midnight resets; defaults to `now + 1h` with probe recovery.
- **Invalid Key**: Stores SHA-256 hash of the key. Retains `invalid` state across calls until the environment variable value changes.
- **Transient**: Network or subprocess timeout errors.

### Probing
`probe(provider)` executes a trivial headless query (`opencode run --auto --standalone "reply with the single word OK"`) with a 45-second timeout. Probes are cheap and represent the **only** mechanism that restores a throttled or probe-due provider to `available`.

---

## 2. Sandbox Isolation & Safeguards

Delegations never execute against the live repository tree.

### Minimal Environment
`build_opencode_env(provider=...)` constructs a strictly sanitized subprocess environment:
- Includes **only**: `PATH`, `LANG`, `HOME`, `OPENCODE_CONFIG_DIR`, and the mapped provider API key (`GROQ_API_KEY`, `GEMINI_API_KEY`, or `HF_TOKEN`).
- **Never passes** Self's own keys (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OLLAMA_API_KEY`, etc.) or other parent process environment variables.

### Sandbox Directory Isolation
For every delegation:
1. A fresh sandbox copy is created in `workspace/sandboxes/sandbox_<id>`.
2. Sensitive and heavy paths are **excluded** during copy:
   - `.env` and `.env.*`
   - `state/` and `workspace/state/`
   - `workspace/memory/`, `workspace/logs/`, `workspace/self/`
   - `scripts/opencode/` and `agent/opencode/`
   - `.git/`, `vendor/`, `sandboxes/`, `__pycache__/`
3. A SHA-256 file manifest of the sandbox is recorded immediately after creation.

### Allowed Write Roots & Scope Check
Opencode is restricted to writing only within pre-approved directory roots:
- `workspace/tools`
- `workspace/plugin_dev`
- `workspace/plugins`
- `workspace/scratch`

After opencode finishes, `SandboxManager.check_scope()` compares the sandbox against the initial manifest. If any file outside the allowed roots was created, modified, or deleted, the delegation status is set to `rejected_scope` and all changes are discarded.

### Process Privilege Drop
When Self runs as `root` in a POSIX container (e.g. Docker), the subprocess execution drops privileges to the unprivileged `opencode` user (`user="opencode"`).
> [!NOTE]
> When running as non-root (e.g. during local tests) or on Windows, privilege drop is not supported and isolation is recorded as `"none"`. This isolation is designed to prevent accidental damage and secret leakage, not serve as a hypervisor-grade hostile boundary.

### Self Self-Protection
Self's own file-writing tools (`ContainerBody.write_file` and `ToolRunner.write_file`) enforce `is_protected_path()`. Self will refuse to write or overwrite:
- `.env*`
- `scripts/opencode*`
- `agent/opencode*`
- `config*`
- `*.lock` and `*.lock.json`
- `opencode_status.json` and `opencode_delegations.json`

---

## 3. Delegation Tools

Four tools are registered for the agent:

### `opencode_status` (Permission L0)
Returns usability status, reasons, and per-provider availability without invoking any network operations or probes.

```json
{
  "ok": true,
  "usable": true,
  "reason": "One or more providers are available or ready for probe.",
  "earliest_retry": null,
  "providers": {
    "groq": {"state": "available", "until": null, "consecutive_failures": 0},
    "google": {"state": "unknown", "until": null, "consecutive_failures": 0},
    "huggingface": {"state": "not_configured", "until": null, "consecutive_failures": 0}
  }
}
```

### `delegate_coding` (Permission L2)
Delegates a scoped task to opencode in a sandbox.
- **Parameters**:
  - `spec` *(string, required)*: Detailed specification of the task.
  - `route_reasons` *(string, required)*: Free text explaining why Self chose to delegate instead of writing the code directly.
  - `target_dirs` *(list of strings, required)*: Subdirectories opencode is permitted to modify (must fall under allowed roots).
  - `acceptance_check` *(string, required)*: Shell command string that must exit 0 in the sandbox for the delegation to be accepted.
  - `model` *(string, optional)*: Explicit `provider/model` override.
  - `timeout_seconds` *(integer, optional)*: Subprocess wall-clock timeout (default: 1800s / 30 min).
- **Execution Workflow**:
  1. Checks `usability()`. If unavailable, returns immediately with `earliest_retry`.
  2. Creates sandbox and records manifest.
  3. Executes headless opencode: `opencode run --auto --standalone [--model <model>] "<prompt>"`.
  4. Multi-provider fallback: On 429/quota failure, marks provider throttled and tries next candidate.
  5. On process exit 0, runs scope check. If out-of-scope files were modified -> `rejected_scope`.
  6. Runs `acceptance_check` inside the sandbox. If fails -> `check_failed`.
  7. If check passes -> marks status `completed`, leaves sandbox intact, and returns `delegation_id`. Files are **not** yet copied to the real repo.

### `apply_delegation` (Permission L2)
Merges a completed delegation into the real repository tree:
1. Re-checks scope and detects collisions.
2. Copies added and modified files atomically to the real tree.
3. Re-runs `acceptance_check` against the **real tree** to verify context integrity.
4. If the real-tree check fails, performs an immediate rollback and returns `apply_failed`.
5. On success, marks delegation applied and cleans up the sandbox.

### `discard_delegation` (Permission L1)
Abandons a delegation and cleans up its sandbox directory.

---

## 4. Testing

All tests use `agent/opencode/tests/fake_opencode.py` to simulate all behavior modes (success, acceptance failure, scope violation, 429 rate limit with/without retry hint, daily quota, invalid key, and hanging process). Real network access and real provider keys are never required.

To run all opencode test suites:

```bash
python -m pytest agent/opencode/tests/ -v
```
