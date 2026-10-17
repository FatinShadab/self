# Document 09: Test Suites & Verification

**Git Commit:** `14ffa606468920a97c672b39fbf3a43fccc52bdf`  
**Date:** 2026-10-17  
**Status:** Read-only architecture documentation

---

## 1. Test Suites & Counts

The repository contains two distinct test suites:

| Test Suite | Location | Test Count | Execution Time | Description |
| :--- | :--- | :--- | :--- | :--- |
| **Agent Harness Suite** | `agent/tests/` | **157 tests** `[ran]` | ~12.2s `[ran]` | Comprehensive unit and integration tests covering all 10 harness packages. Uses mocked/faked models and disposable workspaces. |
| **Hidden Eval Suite** | `eval/tests/` | **11 tests** `[ran]` | ~0.6s `[ran]` | Verifies evaluation harness mechanisms, A/B randomization, scoring math, and strict container isolation. |
| **Total** | | **168 tests** `[ran]` | ~12.8s `[ran]` | 100% passing rate with zero failures or skips. |

---

## 2. Test Breakdown by Subsystem

### Harness Tests (`agent/tests/` — 157 tests)
`[ran] docker run --rm --entrypoint python self-self:latest -m unittest discover -s /opt/agent/tests -v`:
- **`tests/helper_models/` (3 test modules):**
  - `test_model_decisions.py`: Model picker moments, routing choices, history tracking, fallback on provider errors, and quota cooldowns.
  - `test_model_outcomes.py`: Logging and aggregation of model call metrics, truncation markers, and parse error outcomes.
  - `test_model_probe.py`: Capability probe test cases, objective rating evaluation, timeout handling, and format version transitions.
- **`tests/identity/` (2 test modules):**
  - `test_identity.py`: Identity initialization, traits additions, evidence verification, voice immutability, first awakening stage progression, and protected file permission checks.
  - `test_autonomy_relation.py`: First-person singular voice enforcement, autonomy arbitration over human input, and refusal to claim false sentience or biological states.
- **`tests/infra/` (3 test modules):**
  - `test_hardening.py`: DailyTokenLedger reservations, daily resets, CapabilityRequests format, RunCheckpoint persistence, and network egress logging.
  - `test_import_layers.py`: Static AST analysis proving the harness import graph across all 10 packages is strictly acyclic and downward-directed (Layers 0 to 5) `[read] agent/tests/infra/test_import_layers.py:11-22`.
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
- **`tests/ui/` (1 test module):**
  - `test_models_view.py`: Formatting of model registry data and recent routing decisions for TUI `/models` display.

### Eval Tests (`eval/tests/` — 11 tests)
`[ran] docker run --rm --entrypoint python -v ... self-self:latest -m unittest discover -s /opt/eval/tests -v`:
- `test_ab.py` (4 tests): Verifies randomized campaign planning, repetition counts, dry-run token upper bounds, seed workspace hygiene, and checker pass/fail paths.
- `test_eval.py` (7 tests): Verifies active agent shared lock blocks eval exclusive lock, code checker executes in an empty directory without credentials or network, and `docker-compose.yml` `self` service contains no eval mount.

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
`[read] scripts/run-tests.sh:1-19`:
Identical steps using POSIX shell syntax.

### 2. Direct Docker Commands
If invoking Docker directly without the scripts:
```bash
# Build image
docker build --tag self-ci .

# Run agent harness suite (157 tests)
docker run --rm --entrypoint python self-ci -m unittest discover -s /opt/agent/tests -v

# Run eval suite (11 tests) with read-only mounts
docker run --rm --entrypoint python \
  -v "$(pwd)/eval:/opt/eval:ro" \
  -v "$(pwd)/docker-compose.yml:/opt/eval-compose.yml:ro" \
  self-ci -m unittest discover -s /opt/eval/tests -v
```

---

## 4. Slow, Flaky Tests & Known Test Gaps

### Slow Tests
- `tools.test_tool_registry.RegistryTests`: Runs candidate Python tool unittests inside isolated sub-processes (`run_process([sys.executable, "-m", "unittest", ...])`). Executing multiple sub-processes in series takes ~8-10 seconds total `[ran]`.
- All tests are strictly deterministic with no network calls or sleep-waiting; none are currently flaky `[ran]`.

### Known Gaps in Test Coverage
1. **No Live Provider Integration:**
   - Under repository testing rules, all unit tests run provider-free. Tests mock API responses or use fake client adapters.
   - *Gap:* Real provider quirks (e.g. streaming chunks, non-standard HTTP 502/503 HTML error pages, rate-limit headers) are not exercised in automated tests `[inferred]`.
2. **Terminal UI (Textual) Interactive Behavior:**
   - Textual widgets and models view formatting are tested via static rendering and unit tests, but real interactive TUI event loops (mouse events, window resizing, live terminal scrolling) are not exercised in headless CI `[inferred]`.
3. **Container Reboot / Host Machine Reboots:**
   - Recovery from `active_session.json` crash state is tested with crafted disk files, but an actual operating system kill signal (`SIGKILL`) terminating the Docker daemon mid-write is only tested via mock simulation `[inferred]`.

---

## 5. Eval Framework Isolation

The hidden evaluation framework in `eval/` is strictly isolated from the agent harness:

1. **Build Exclusion:** `eval` is listed in `.dockerignore` `[read] .dockerignore:4`. It is never copied into the Docker image `self-self:latest`.
2. **Mount Isolation:** In `docker-compose.yml`, the agent service `self` mounts only `${SELF_WORKSPACE_DIR:-./workspace}` to `/home/entity`. The `eval/` folder is NOT mounted into the `self` service `[read] docker-compose.yml:15-19`.
3. **Compose Profile Protection:** The `eval` service in `docker-compose.yml` is protected by `profiles: ["eval"]` `[read] docker-compose.yml:26`. It does not start during normal `docker compose up self`.
4. **Secretless Evaluation:** Evaluation checkers run in temporary directories without provider API keys or internet access, ensuring benchmark integrity `[read] eval/tests/test_eval.py:80-95`.
