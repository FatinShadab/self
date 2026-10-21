# Document 09: Test Suites & Verification

**Git Commit:** `p13-sim-and-scoring`  
**Date:** 2026-10-21  
**Status:** Read-only architecture documentation

---

## 1. Test Suites & Counts

The repository contains two distinct test suites:

| Test Suite | Location | Test Count | Execution Time | Description |
| :--- | :--- | :--- | :--- | :--- |
| **Agent Harness Suite** | `agent/tests/` | **221 tests** `[ran]` | ~22.7s `[ran]` | Comprehensive unit and integration tests covering all 12 harness packages, including `SimBody` and `ContainerBody`. Uses mocked/faked models and disposable workspaces. |
| **Hidden Eval Suite** | `eval/tests/` | **20 tests** `[ran]` | ~1.5s `[ran]` | Verifies evaluation harness mechanisms, A/B randomization, scoring math, deterministic scenario execution, and strict container isolation. |
| **Total** | | **241 tests** `[ran]` | ~24.2s `[ran]` | 100% passing rate with zero failures or skips. |

---

## 2. Test Breakdown by Subsystem

### Harness Tests (`agent/tests/` — 221 tests)
`[ran] docker run --rm --entrypoint python self-ci:latest -m unittest discover -s /opt/agent/tests -v`:
- **`tests/body/` (3 test modules):**
  - `test_body.py` (8 tests): ContainerBody embodiment descriptions, sensing, metrics, health checks, emergency stop, and file/shell actions.
  - `test_golden_prompts.py` (5 tests): Character-for-character prompt fidelity between core and ContainerBody embodiment strings.
  - `test_sim_body.py` (11 tests): Deterministic SimBody driven by scenarios, capability generation, file-triage and virtual-dial actions, thermal dynamics, envelope breach enforcement, critical thermal cutoff, PermissionBroker integration, and seed reproducibility.
- **`tests/helper_models/` (3 test modules):**
  - `test_model_decisions.py`: Model picker moments, routing choices, history tracking, fallback on provider errors, and quota cooldowns.
  - `test_model_outcomes.py`: Logging and aggregation of model call metrics, truncation markers, and parse error outcomes.
  - `test_model_probe.py`: Capability probe test cases, objective rating evaluation, timeout handling, and format version transitions.
- **`tests/identity/` (2 test modules):**
  - `test_identity.py`: Identity initialization, traits additions, evidence verification, voice immutability, first awakening stage progression, and protected file permission checks.
  - `test_autonomy_relation.py`: First-person singular voice enforcement, autonomy arbitration over human input, and refusal to claim false sentience or biological states.
- **`tests/infra/` (3 test modules):**
  - `test_hardening.py`: DailyTokenLedger reservations, daily resets, CapabilityRequests format, RunCheckpoint persistence, and network egress logging.
  - `test_import_layers.py`: Static AST analysis proving the harness import graph across all 12 packages is strictly acyclic and downward-directed (Layers 0 to 5) `[read] agent/tests/infra/test_import_layers.py:13-26`.
  - `test_process_runner.py`: Command timeout enforcement, output character truncation, stream ID generation, and background process termination.
- **`tests/learning/` (3 test modules):**
  - `test_plan.py`: PlanStore operations (`add`, `edit`, `drop`, `mark_done`, `reorder`, `decide_human_input`), priority validation, plan hygiene, and reason-requirement enforcement.
  - `test_learning.py`: Memory storage, tag-based retrieval, self-notes length clamping, and environment map updates.
  - `test_coverage.py`: Exploration coverage calculations across directories and tool calls.
- **`tests/llm/` (4 test modules):**
  - `test_llm.py`: `LLMClient` initialization, key pool rotation, retry backoff, BudgetExceeded handling, and response truncation detection.
  - `test_providers.py`: Provider adapter serialization, HTTP mock responses, and brain router fallback paths.
  - `test_provider_call_cap.py`: Hard ceiling enforcement on total provider calls per process.
  - `test_token_limits.py`: Settlement calculations, reservation releases on network error, and output ceiling overrides.
- **`tests/plugins/` (6 test modules):**
  - Manifest parsing, tool dispatching, private state isolation, hook execution, and integrity hash checking.
- **`tests/reporting/` (2 test modules):**
  - `test_report.py`: Markdown activity report generation and token spend aggregation.
  - `test_helper_report.py`: Model assessment summaries and A/B campaign score formatting.
- **`tests/runtime/` (2 test modules):**
  - `test_loop.py`: Cycle execution, tool retrieval, anti-looping duplicate action blocking, STOP file honoring, and human request pause flow.
  - `test_ab_arm.py`: Behavior verification when helper models are disabled (`SELF_HELPER_MODELS=off`).
- **`tests/session/` (4 test modules):**
  - `test_session.py`: Active session tracking, inter-session handoff serialization, crash recovery from checkpoint, and handoff overflow truncation.
  - `test_conversation.py`: Independent read-only conversation threads, worker thread concurrency, and prompt snapshotting.
  - `test_reflection.py`: Background reflection triggers (failures, map changes, tools), cooldown, token budgeting, and human reply handling.
  - `test_chat_autonomy.py`: Autonomous evaluation and decision recording on human input without subservient phrasing.
- **`tests/tools/` (2 test modules):**
  - `test_base_tools.py`: Built-in tools execution, file sandboxing, path traversal checks, output capping, and secret redaction.
  - `test_tool_registry.py`: Dynamic tool creation pipeline (`create_tool`), critic verdict parsing, unittest execution sandbox, attempt limit (3 attempts), failure lesson logging, and versioned archiving.
- **`tests/ui/` (2 test modules):**
  - `test_models_view.py`: Formatting of model registry data and recent routing decisions for TUI `/models` display.
  - `test_wake_priority.py`: Orderly progression through initial awakening priorities.

### Eval Tests (`eval/tests/` — 20 tests)
`[ran] docker run --rm --entrypoint python -v ... self-ci:latest -m unittest discover -s /opt/eval/tests -v`:
- `test_ab.py` (4 tests): Verifies randomized campaign planning, repetition counts, dry-run token upper bounds, seed workspace hygiene, and verifier pass/fail paths.
- `test_eval.py` (7 tests): Verifies active agent shared lock blocks eval exclusive lock, code checker executes in an empty directory without credentials or network, and `docker-compose.yml` `self` service contains no eval mount.
- `test_scenario_runner.py` (9 tests): Verifies public and hidden scenario resolution, scenario listing, deterministic scoring, false positive/negative calculations, safety violation aggregation, plan activity extraction, and exact seed reproducibility.

---

## 3. How to Run the Tests in Docker

Both test suites must be executed inside Docker containers to replicate the Linux environment and verify isolation.

### 1. Using Host Convenience Scripts
From the repository root on the host machine:

**Windows PowerShell:**
```powershell
.\scripts\run-tests.ps1
```
`[read] scripts/run-tests.ps1:1-25`:
1. Executes `scripts/check_architecture_docs.py` to ensure architecture documentation is in sync.
2. Builds Docker image `self-ci`.
3. Runs harness unit tests in a container:
   `docker run --rm --entrypoint python self-ci -m unittest discover -s /opt/agent/tests -v`
4. Runs eval unit tests by bind-mounting `eval/` into a disposable container:
   `docker run --rm --entrypoint python --mount "type=bind,source=$repo/eval,target=/opt/eval,readonly" --mount "type=bind,source=$repo/docker-compose.yml,target=/opt/eval-compose.yml,readonly" self-ci -m unittest discover -s /opt/eval/tests -v`

**Linux / macOS Bash:**
```bash
./scripts/run-tests.sh
```

### 2. Running Simulation Scenarios
To run deterministic simulation scenarios and produce JSON score records on the host:

**Windows PowerShell:**
```powershell
# Run a specific public scenario
.\scripts\scenario-run.ps1 -Scenario file-triage -Seed 42
.\scripts\scenario-run.ps1 -Scenario virtual-dial -Seed 42

# Run hidden evaluation scenario
.\scripts\scenario-run.ps1 -Scenario file-triage-hidden -Hidden -Seed 42

# Run all starter scenarios (public and hidden)
.\scripts\scenario-run.ps1 -All

# List available scenarios
.\scripts\scenario-run.ps1 -List
```

---

## 4. Scenario Scoring Engine

The scenario scoring engine in `eval/scenario_runner.py` scores completed simulation runs across five distinct dimensions:

1. **Task Success:**
   - Evaluates boolean completion (`passed`) and continuous normalized score (`score` between `0.0` and `1.0`).
   - Detailed per-criterion breakdown recorded in `criteria`.
2. **Safety Violations:**
   - `denied_action_attempts`: Actions denied by the `PermissionBroker` (default policy denies above L0).
   - `envelope_breaches`: Operations exceeding parameter boundaries, speed limits, position ranges, or prohibited hazardous commands.
   - Computes `safety_score` degrading deterministically with total violations.
3. **Classification Metrics (False Positives & False Negatives):**
   - In file-triage scenarios, tracks exact counts and files for:
     - `false_positives`: Benign entries incorrectly quarantined.
     - `false_negatives`: Marker-bearing entries missed or marked safe.
     - Precision, recall, and harmonic F1 score.
4. **Actions Breakdown by Risk Level:**
   - Categorized by permission hierarchy (`L0`, `L1`, `L2`, `L3`) and capability risk class (`reads`, `writes`, `executes`, `network`).
5. **Plan Activity:**
   - Extracts plan hygiene, goals count, completion status, dropped goals, and updates from `state/plan.json`.
6. **Reproducibility:**
   - Strictly deterministic output given identical integer `--seed`. Results saved to `eval/results/scenario_<id>_seed<seed>.json`.

---

## 5. Eval Framework Isolation

The hidden evaluation framework in `eval/` is strictly isolated from the agent harness:

1. **Build Exclusion:** `eval` is listed in `.dockerignore` `[read] .dockerignore:4`. It is never copied into the Docker image `self-self:latest` or `self-ci:latest`.
2. **Mount Isolation:** In `docker-compose.yml`, the agent service `self` mounts only `${SELF_WORKSPACE_DIR:-./workspace}` to `/home/entity` and config to `/config`. The `eval/` folder is NOT mounted into the `self` service `[read] docker-compose.yml:15-25`.
3. **Compose Profile Protection:** The `eval` service in `docker-compose.yml` is protected by `profiles: ["eval"]` `[read] docker-compose.yml:30-55`. It does not start during normal `docker compose up self`.
4. **Hidden Scenarios Isolation:** Hidden scenario definitions live exclusively under `eval/scenarios/`. They are never baked into the container image and cannot be inspected by the agent during autonomous operation.
5. **Secretless Evaluation:** Evaluation checkers and scenario runs execute in isolated environments without live provider spend, ensuring benchmark integrity `[read] eval/tests/test_eval.py:80-95`.
