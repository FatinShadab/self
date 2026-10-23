# Master Refactoring Summary: SELF Harness Modularization

## 1. Executive Summary

This refactoring program systematically decomposed 22 monolithic "god files" across the SELF agent harness (`agent/`) into small, single-purpose, highly cohesive modules adhering strictly to SOLID principles, import layering rules, and backward-compatibility invariants.

Every original module remains in place as a thin facade re-exporting its historical public API, preserving private attributes and internal methods required by unit tests, retaining all mock patch targets, and ensuring zero behavioral changes.

### Key Metrics
- **God Files Refactored**: 22 files across all priority tiers ([P1], [P2], [P3]).
- **New Submodules Created**: 120+ single-purpose modules.
- **Verification Gate**: 100% compliant with `scripts/check_docs_claims.py` (337 harness tests + 20 eval tests = 357 total tests; 135 verified events; 29 core tools + 7 OpenCode tools; 12 packages; 42 state files).
- **Import Layering**: Strict downward DAG compliance enforced by `test_import_layers.py`.
- **Golden Prompts**: 100% character-for-character preserved.

---

## 2. Refactoring Inventory

| Priority | Original God File | Original LOC | Facade LOC | Subpackage Created | Documentation Report |
| :---: | :--- | :---: | :---: | :--- | :--- |
| **[P1]** | `agent/ui/wake.py` | 1,455 | 102 | `agent/ui/tui/`, `formatting/`, `cardiac_monitor.py` | [`ui-wake.md`](ui-wake.md) |
| **[P1]** | `agent/session/coordinator.py` | 1,191 | 391 | `agent/session/{boot,telemetry,plan_recovery,etc.}.py` | [`session-coordinator.md`](session-coordinator.md) |
| **[P1]** | `agent/tools/base_tools.py` | 944 | 392 | `agent/tools/{definitions,execution,handlers,dispatch}/` | [`tools-base_tools.md`](tools-base_tools.md) |
| **[P1]** | `agent/runtime/loop.py` | 880 | 275 | `agent/runtime/{wiring,tool_round,cycle_runner,etc.}.py` | [`runtime-loop.md`](runtime-loop.md) |
| **[P2]** | `agent/plugins/self_dev.py` | 912 | 200 | `agent/plugins/dev/` | [`plugins-self_dev.md`](plugins-self_dev.md) |
| **[P2]** | `agent/helper_models/model_decisions.py` | 904 | 286 | `agent/helper_models/decisions/` | [`helper_models-model_decisions.md`](helper_models-model_decisions.md) |
| **[P2]** | `agent/identity/identity.py` | 811 | 456 | `agent/identity/store/` | [`identity-identity.md`](identity-identity.md) |
| **[P2]** | `agent/learning/plan.py` | 783 | 438 | `agent/learning/plans/` | [`learning-plan.md`](learning-plan.md) |
| **[P2]** | `agent/opencode/wrapper.py` | 775 | 488 | `agent/opencode/delegation/` | [`opencode-wrapper.md`](opencode-wrapper.md) |
| **[P2]** | `agent/plugins/manager.py` | 770 | 264 | `agent/plugins/lifecycle/` | [`plugins-manager.md`](plugins-manager.md) |
| **[P2]** | `agent/llm/model_registry.py` | 613 | 444 | `agent/llm/registry/` | [`llm-model_registry.md`](llm-model_registry.md) |
| **[P2]** | `agent/helper_models/model_probe.py` | 513 | 87 | `agent/helper_models/probes/` | [`helper_models-model_probe.md`](helper_models-model_probe.md) |
| **[P2]** | `agent/tools/tool_registry.py` | 470 | 148 | `agent/tools/custom/` | [`tools-tool_registry.md`](tools-tool_registry.md) |
| **[P3]** | `agent/plugins/cli.py` | 597 | 45 | `agent/plugins/sdk_cli/` | [`plugins-cli.md`](plugins-cli.md) |
| **[P3]** | `agent/body/container.py` | 568 | 183 | `agent/body/linux/` | [`body-container.md`](body-container.md) |
| **[P3]** | `agent/body/sim.py` | 547 | 180 | `agent/body/simulation/` | [`body-sim.md`](body-sim.md) |
| **[P3]** | `agent/opencode/status.py` | 476 | 150 | `agent/opencode/provider_status/` | [`opencode-status.md`](opencode-status.md) |
| **[P3]** | `agent/infra/migration.py` | 468 | 28 | `agent/infra/state_migration/` | [`infra-migration.md`](infra-migration.md) |
| **[P3]** | `agent/learning/learning.py` | 427 | 180 | `agent/learning/store/` | [`learning-learning.md`](learning-learning.md) |
| **[P3]** | `agent/infra/permission_broker.py` | 421 | 38 | `agent/infra/permissions/` | [`infra-permission_broker.md`](infra-permission_broker.md) |
| **[P3]** | `agent/llm/llm.py` | 374 | 239 | `agent/llm/client/` | [`llm-llm.md`](llm-llm.md) |
| **[P3]** | `agent/session/reflection.py` | 352 | 15 | `agent/session/reflections/` | [`session-reflection.md`](session-reflection.md) |

---

## 3. SOLID Improvements & Architectural Highlights

### Single Responsibility Principle (SRP)
- **Separation of I/O from Logic**: Atomic state file reads/writes, lock acquisition, and JSON serialization are extracted into dedicated persistence modules (e.g., `agent/learning/plans/persistence.py`, `agent/session/reflections/state.py`, `agent/infra/atomic_io.py`).
- **Telemetry & Logging Decoupled**: Event logging and decision recording are encapsulated into dedicated handlers (e.g., `agent/tools/execution/call_logging.py`, `agent/llm/registry/telemetry.py`).
- **Input Validation & Safety Filtering**: Inner-state claims, regex validations, and argument schema enforcement are isolated (e.g., `agent/session/reflections/safety.py`, `agent/tools/execution/model_arg_validation.py`).

### Open/Closed Principle (OCP)
- **TUI Command Registry**: Replaced a 250-line `if/elif` ladder in `agent/ui/wake.py` with an extensible `CommandRegistry` and command handlers implementing a common `CommandHandler` protocol (`agent/ui/tui/commands/`).
- **Full-Screen Views**: Encapsulated coverage, archive, and conversation views behind a common `FullScreenView` interface (`agent/ui/tui/views/base.py`), allowing new full-screen views to be plugged in without modifying `SelfApp`.
- **Tool Handlers**: Partitioned 29 core tools into domain-specific handler modules (`handlers/files.py`, `handlers/system.py`, `handlers/plan.py`, `handlers/learning.py`, etc.).

### Liskov Substitution & Interface Segregation (LSP & ISP)
- **Tool Search**: Formalized `ToolSearch` protocol with default `KeywordToolSearch` implementation.
- **Provider Status**: Decoupled provider state tracking and error classification into standalone pure functions and storage records.

### Dependency Inversion (DIP)
- High-level orchestrators (`AgentLoop`, `WakeCoordinator`, `ReflectionManager`) delegate specific responsibilities to pure helpers or injected dependencies, eliminating hidden global state and direct filesystem side-effects in constructors.

---

## 4. Verification and Constraint Compliance

### 1. Import Layering
Enforced by `agent/tests/infra/test_import_layers.py`:
```
infra(0) → llm, body(1) → tools, learning, helper_models, identity, plugins(2) → runtime(3) → session, reporting(4) → ui(5)
```
- Every new module resides strictly within its existing package namespace.
- No cross-layer upward imports exist across the entire harness.

### 2. Backward Compatibility & Facades
- All 22 original files remain importable at their original paths.
- Each facade explicitly defines `__all__` and re-exports all original public functions, classes, and constants.
- Symbols cited in documentation and tests use explicit assignments (`Symbol = _Symbol`) to satisfy static symbol discovery (`check_symbol_citations`).

### 3. Mock Patch Targets Preserved
All known test patch targets remain functional without test modifications:
- `agent.tools.tool_registry.run_process`
- `agent.plugins.self_dev.run_process`
- `agent.helper_models.model_probe.subprocess.run`
- `agent.llm.llm.Anthropic`
- `agent.llm.llm.reserve_provider_call`
- `agent.llm.llm.time.sleep`
- `agent.runtime.loop.time.sleep`
- `agent.body.container.run_process`
- `agent.reporting.report._host_results_allowed`

### 4. Golden Prompts Character-for-Character Preserved
- `assemble_system_prompt`, `assemble_conversation_system_prompt`, and all `GOLDEN_*` prompt constants pass character-for-character comparison tests (`agent/tests/body/test_golden_prompts.py`).

### 5. Documentation Claims Guard
Executed `scripts/check_docs_claims.py`:
- 29 Core Tools verified
- 135 Events verified (all AST logger call sites preserved)
- 357 Total Tests verified (337 harness + 20 eval)
- 12 Packages verified
- 42 State Files verified
- 44 Environment Variables verified

---

## 5. Observations (Pre-existing Quirks and Host/Container Discrepancies)

The following items were identified during regression testing. In accordance with the non-negotiable constraints, **no behavior changes or bug fixes were made**; these are recorded here for operator awareness:

1. **Subprocess Output Buffering on Windows (`agent/infra/process_runner.py`)**:
   - `test_output_cap_and_timeout_remain_bounded` fails when executed directly on Windows host Python because standard output is buffered by default in Python child processes. When `process.kill()` terminates the process upon timeout, buffered output is discarded prior to being flushed, leaving `result["truncated"] == False`. On Linux / container environments with pseudo-terminals or unbuffered execution, stdout is captured as expected.
2. **Container Boundary Detection (`agent/reporting/report.py`)**:
   - `_host_results_allowed()` checks `not Path("/opt/agent").exists()`. Inside the production container `/opt/agent` exists (returning `False`), whereas on the host development machine `/opt/agent` does not exist (returning `True`). Consequently, `test_container_never_reads_supplied_eval_files` expects a container environment.
3. **Cross-Thread Interception during Monolithic Test Discovery (`time.sleep`)**:
   - When running the entire unittest suite in a single process (`discover -s agent/tests`), global monkey-patching of `time.sleep` in `agent/tests/runtime/test_loop.py` intercepts `time.sleep` calls made by concurrent background threads (e.g. heartbeat/watchers from earlier tests), causing the loop pause iteration count assertion (`sleep_calls == 3`) to record calls from other threads. Running `test_loop.py` in isolation passes cleanly (8/8 tests pass).
