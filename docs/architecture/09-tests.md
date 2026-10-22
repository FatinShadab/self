# Document 09: Test Suites & Verification

**Git Commit:** `core-v0.1.0-rc3`  
**Date:** 2026-10-22  
**Status:** Read-only architecture documentation

---

## 1. Test Suites & Counts

The repository contains two distinct test suites:

| Test Suite | Location | Test Count | Execution Time | Description |
| :--- | :--- | :--- | :--- | :--- |
| **Agent Harness Suite** | `agent/tests/` | **337 tests** `[ran]` | ~30s `[ran]` | Comprehensive unit and integration tests covering all 12 harness packages, including `SimBody`, `ContainerBody`, soak scenarios, and documentation guards. Uses mocked/faked models and disposable workspaces. |
| **Hidden Eval Suite** | `eval/tests/` | **20 tests** `[ran]` | ~1.5s `[ran]` | Verifies evaluation harness mechanisms, A/B randomization, scoring math, deterministic scenario execution, and strict container isolation. |
| **Total** | | **357 tests** `[ran]` | ~32s `[ran]` | Complete passing rate under Linux container test harness. |

---

## 2. Test Breakdown by Subsystem

### Harness Tests (`agent/tests/` — 337 tests)
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
- **`tests/infra/` (4 test modules):**
  - `test_hardening.py`: DailyTokenLedger reservations, daily resets, CapabilityRequests format, RunCheckpoint persistence, and network egress logging.
  - `test_import_layers.py`: Static AST analysis proving the harness import graph across all 12 packages is strictly acyclic and downward-directed (Layers 0 to 5) `[read] agent/tests/infra/test_import_layers.py:13-26`.
  - `test_process_runner.py`: Command timeout enforcement, output character truncation, stream ID generation, and background process termination.
  - `test_docs_claims.py`: Static verification that documentation claims, test numbers, and relative links match ground truth facts.
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
- **`tests/soak/` (2 test modules, 12 tests):**
  - `test_soak_scenarios.py` (11 tests): Deterministic soak scenarios B1 through B10 exercising multi-cycle continuous execution, tool creation, stop files, and recovery.
  - `test_soak_30_cycles_replay.py` (1 test): 30-cycle reproducible historical execution replay against scrubbed golden fixtures.
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

---

## 6. Deterministic Soak Test Suite (`agent/tests/soak/`)

The soak suite (`agent/tests/soak/`) verifies loop and state machine invariants across extended multi-cycle autonomous runs (30 to 200+ cycles) without live provider spend or external network access.

### A. Soak Harness Architecture
- **`ScriptedProvider` (`agent/tests/soak/harness.py:165`):** Deterministic mock LLM provider simulating structured responses, tool calls, plan updates, self-development workflows, and synthetic errors based on cycle indices.
- **`ReplayProvider` (`agent/tests/soak/harness.py:270`):** Replays historical tool calls, plan events, and provider exceptions from scrubbed fixture `agent/tests/soak/fixtures/real_run_shape.jsonl` (1,686 events, 374 errors, zero secrets).
- **`FaultSchedule` (`agent/tests/soak/harness.py:80`):** Programmatic fault injection engine delivering burst and isolated errors: `APIConnectionError`, `InternalServerError`, `APITimeoutError`, `RateLimitError` (HTTP 429), and `BadRequestError` (HTTP 400).
- **`FakeClock` (`agent/tests/soak/harness.py:120`):** Freezes and steps synthetic time to verify token ledger rollovers and reset intervals without wall-clock sleeps.
- **`Invariants` (`agent/tests/soak/harness.py:380`):** Verifies workspace state assertions at every cycle boundary:
  - Handoff bounded to `<= 6,000` chars (`HANDOFF_CAP`) with overflow archived to `state/handoff_overflow.json`.
  - Handoff recursion prevention: `"Session complete after"` appears `<= 1` time.
  - Plan store persistence: `state/plan.json` maintains valid items.
  - Action loop protection: Identical tool actions blocked after 3 calls (`repeated_tool_action_blocked`).
  - Tool creation cap: Consecutive failures bounded to 3 attempts with lessons written to `memory/lessons.jsonl`.
  - Token ledger integrity: Active reservations must be released (`reserved_tokens == 0`) at cycle boundary.
- **`SoakRunner` (`agent/tests/soak/harness.py:530`):** Orchestrates the loop inside a disposable temporary workspace, recording cycle metrics and asserting invariants per cycle.

### B. Soak Scenarios (B1 - B10)
1. **B1: Plain 30-Cycle Mix (`test_soak_scenarios.py:44`):** Nominal 30 cycles with tool calls, plan updates, memory storage, and cycle 12 human input.
2. **B2: Fault Injection Schedule (`test_soak_scenarios.py:90`):** Network disconnects, 500 errors, timeouts, and 429 rate limits with backoff.
3. **B3: Flapping Network Outage (`test_soak_scenarios.py:145`):** Extended 5-cycle network outage triggering circuit breakers, followed by clean recovery.
4. **B4: Tool Creation Limit (`test_soak_scenarios.py:180`):** Enforces 3-attempt ceiling on failing tool creations and lesson logging.
5. **B5: Repeated Action Blocker (`test_soak_scenarios.py:215`):** Enforces blocking of identical tool calls after 3 repeats.
6. **B6: 60-Cycle Growth Bounds (`test_soak_scenarios.py:246`):** Verifies regression slopes across 60 cycles (`SOAK_LONG=1` runs 200 cycles).
7. **B7: STOP File Honoring (`test_soak_scenarios.py:290`):** Immediate exit on `STOP` sentinel file presence.
8. **B8: Hot-Unplug During Run (`test_soak_scenarios.py:330`):** Hot-unplug of active plugin, tool removal, and state archiving.
9. **B9: Token Ledger Exhaustion (`test_soak_scenarios.py:375`):** Reservation ceiling enforcement and rejection of unbacked calls.
10. **B10: Daily Allowance Reset (`test_soak_scenarios.py:420`):** Clean pause on daily budget exhaustion and resumption on synthetic UTC rollover.

### C. Replay Tests (C1 - C3)
- **C1/C2: Real Run Shape Replay (`test_soak_replay.py:35`):** 30 cycles against 1,686 scrubbed historical actions with 374 errors, oversized 7,326-byte handoff bounding, and 292 tool failure blocks.
- **C3: Historical Plan Absence (`test_soak_replay.py:120`):** Confirms historical log predates autonomous plan store, verifying replay tests unassisted recovery.

### D. Verification Tools
- **`scripts/soak.ps1`:** Runs the 12-scenario soak suite directly, reporting seed, scenario outcomes, and B6 growth trajectory table.
- **`scripts/live-soak-gate.ps1`:** Post-run read-only invariant validator for live workspaces. Evaluates handoff size, recursive framing, plan activity, failure classes, growth bounds, and token ledger state.

### E. What This Does and Does Not Prove
- **What It Proves (Mechanical Robustness):** Proves that the loop, plan store, memory, session coordinator, tool registry, and token ledger run for 30+ cycles without memory leaks, unbound handoff growth, runaway error loops, or leaked token reservations.
- **What It Does NOT Prove:** Does not prove LLM decision quality, semantic relevance of generated code, live provider API deviations, non-deterministic latency anomalies, or slow semantic topic drift.

