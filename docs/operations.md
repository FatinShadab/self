# SELF Operator Runbook

This runbook provides host-side procedures for building, testing, verifying, and operating the SELF autonomous agent system.

> [!WARNING]
> **Live Multi-Cycle Runs Are Not Formally Validated:** While the automated test suites (337 harness tests and 20 eval tests) and the deterministic soak suite (scenarios B1–B10 across 60–200 cycles) pass completely with mocked and scripted providers, **no live multi-cycle run on the current release candidate (`core-v0.1.0-rc3`) has been validated against real LLM provider endpoints**. Proceed cautiously with small iteration counts and bounded token limits.

---

## 1. Environment & Prerequisites

Operations are performed from the repository root on the host machine (Windows PowerShell or Linux bash).

### Required Host Tools
- **Python:** Python 3.10+ (tested on Python 3.12 and 3.14)
- **Docker & Docker Compose:** Docker Engine with Compose support
- **PowerShell:** PowerShell 5.1+ or PowerShell Core 7+ (on Windows) or `bash` (on Linux)

### Environment Variables (.env)
The agent reads credentials and configuration from a gitignored `.env` file at the repository root. Create it from the template:
```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Key environment variables:
| Variable Name | Purpose | Required for Offline Tests? | Required for Live Runs? |
| :--- | :--- | :--- | :--- |
| `OLLAMA_API_KEY` | Primary API key for Ollama Cloud provider | **No** (Mocked) | Yes (if using Ollama) |
| `ANTHROPIC_API_KEY` | Primary API key for Anthropic provider | **No** (Mocked) | Yes (if using Anthropic) |
| `ANTHROPIC_MODEL` | Base model identifier (e.g. `claude-3-5-sonnet-latest`) | **No** | Yes (if using Anthropic) |
| `OLLAMA_MODEL` | Base model identifier (e.g. `llama3.3:70b`) | **No** | Yes (if using Ollama) |
| `LLM_AVAILABLE_MODELS` | Comma-separated or JSON list of eligible helper models | **No** | Optional |
| `SELF_MAX_TOKENS_PER_DAY` | Hard daily token ceiling enforced by `DailyTokenLedger` (default: 200,000) | **No** | Optional |
| `SELF_CONFIG_DIR` | Host directory mounted read-only to `/config` (default: `./config`) | **No** | Optional |
| `SELF_WORKSPACE_DIR` | Host directory mounted to `/home/entity` (default: `./workspace`) | **No** | Optional |

---

## 2. Image Building

Build the primary container image (`self-self:latest` or `self-ci`):

```powershell
# Using Docker Compose
docker compose build

# Or direct Docker build
docker build --tag self-ci .
```

*Verification status: Verified by Dockerfile static inspection and build syntax.*

---

## 3. Test Suites Execution

### Running All Automated Tests (CI Mode)
The standard verification script checks architecture documentation integrity, builds the container image, and runs both the harness and evaluation suites:

```powershell
.\scripts\run-tests.ps1
```

On Linux:
```bash
bash scripts/run-tests.sh
```

### Running Host-Only Offline Unit Tests (Without Docker)
When Docker is unavailable on the host, harness tests can be run directly using the host Python environment:

```powershell
$env:PYTHONPATH=".;agent"
python -m unittest discover -s agent/tests -v
```

> [!NOTE]
> - **Harness Collection:** Unittest discovery collects **337 harness test methods** across all 12 Python packages. In Linux container CI, all 337 pass.
> - **Windows Host Differences:** On a Windows host, 334 pass, 2 fail, and 1 encounters an error due to Windows platform behaviors: subprocess pipe buffering before the 0.2s timeout in `test_output_cap_and_timeout_remain_bounded`, Windows file locking on temp directory `rmdir` while a background process exits in `test_shell_background_child_cannot_hold_pipe_forever`, and host vs container environment detection in `test_container_never_reads_supplied_eval_files`.
> - **Evaluation Suite:** The 20 tests under `eval/tests/` depend on POSIX system interfaces (`fcntl`) and Linux container paths (`/etc/os-release`), and require execution inside the Linux Docker container. On Windows host, 14 are collected and 2 fail with environment errors. Container run: NOT RUN if Docker is unavailable.

---

## 4. Deterministic Soak Testing

The soak test suite executes long multi-cycle runs using a deterministic `ScriptedProvider` or historical replay fixture, validating per-cycle invariants without network calls or API costs:

```powershell
# Run 60-cycle deterministic soak suite (Scenarios B1-B10) with seed 42
.\scripts\soak.ps1 -Seed 42

# Run extended 200-cycle soak suite
.\scripts\soak.ps1 -Seed 42 -Long
```

What the soak suite checks on every cycle:
1. **Token Budget Invariant:** Active reservations never exceed available daily balance in `daily_token_budget.json` (or fallback `token_ledger.json`).
2. **Handoff Boundedness Invariant:** `state/handoff.json` length remains strictly ≤ 6,000 characters.
3. **No Header Duplication Invariant:** The string `"Session complete after"` appears at most once in handoff summaries.
4. **Plan Hygiene Invariant:** Goals with status `done` or `dropped` are purged from `state/plan.json` at cycle end.
5. **No Tight Spin Invariant:** Daily token pauses sleep until UTC midnight rather than burning CPU on dust token balances.

*Verification status: Verified by automated test module `agent/tests/soak/test_soak_scenarios.py` and `agent/tests/soak/test_soak_30_cycles_replay.py`.*

---

## 5. Pre-Live Run Diagnostic Gate

Before starting any live autonomous session with real credentials, execute the pre-run gates on the host:

### Step 1: Run Live Diagnostic Checks
```powershell
.\scripts\live-check.ps1 -Workspace workspace -DryRun
```
Inspect the output to confirm:
- Plugin enablement and SHA-256 hash status (`[PASS]`).
- Absence of unacknowledged stop-loss review triggers.
- Integrity of `config/plugins.json` and `config/permissions.json`.

### Step 2: Validate Invariant Gate
```powershell
python scripts/live_soak_gate.py --workspace workspace --fail-on-warn
```
Ensures that existing workspace state complies with all safety invariants.

### Step 3: Run Pre-Flight Checklist
- [ ] `./workspace` has been backed up if previous memories should be retained.
- [ ] `.env` specifies a dedicated API key with a strict spending cap configured on the provider console.
- [ ] `SELF_MAX_TOKENS_PER_DAY` is set to an acceptable daily limit in `.env` (e.g. `50000`).
- [ ] Host paths other than `./workspace` and `./config` are unmounted.
- [ ] No `workspace/STOP` file exists prior to boot.

---

## 6. Live Agent Sessions

### Starting an Interactive Terminal UI Session
```powershell
# Run interactive wake session in disposable container
docker compose run --rm self --max-iterations 5 --token-budget 20000
```
- First wake: SELF executes its A–E orientation sequence, explains its code, and asks for a name.
- Interactive controls:
  - `/goal <focus>`: Direct autonomous attention.
  - `/models`: View configured models and helper probes.
  - `/coverage`: Inspect explored directories and saved tools.
  - `/pause` / `/resume`: Pause and resume autonomous loop cycles.
  - `/stop`: Halt execution cleanly, checkpoint handoff, and write `workspace/STOP`.

### Starting a Headless Run (Plain Terminal Output)
```powershell
docker compose run --rm self --headless --max-iterations 2 --token-budget 20000
```

### Emergency Stopping an Unresponsive Container
If the interactive TUI is unresponsive:
```powershell
# Create emergency STOP file on host
New-Item -ItemType File -Path workspace/STOP -Force

# Or stop the container directly via Docker
docker compose down
```

---

## 7. Post-Run Log Analysis

Evaluate an extended autonomous run trace:

```powershell
.\scripts\analyze-run.ps1 -Workspace workspace -MaxCycles 30
```

Or invoke the Python analyzer directly:
```powershell
python scripts/analyze_run.py --workspace workspace --max-cycles 30 --json
```

The analyzer reports:
- Plan autonomy ratio: Percentage of plan reviews driven by the agent model vs. automatic harness fallback.
- Handoff file size and character growth trajectory against the 6,000-character ceiling.
- Human input arbitration breakdown (`accepted`, `modified`, `declined`, `deferred`, `noted`).
- Failure categorization (LLM errors, tool failures, permission denials, duplicate action blocks).
- Plugin lifecycle events and stop-loss reviews.
- Per-cycle token expenditure and cumulative trajectory.

---

## 8. Workspace Backup & Restore

### Automated Snapshot Backup
Before running state migrations or risky explorations:
```powershell
python scripts/migrate_p14_tagged_state.py --workspace workspace
```
Creates an uncompressed, SHA-256 hashed snapshot under `workspace/state/backups/<TIMESTAMP>/`.

### Byte-for-Byte Restore
To revert to a previously recorded snapshot:
```powershell
python scripts/migrate_p14_tagged_state.py --workspace workspace --restore workspace/state/backups/<TIMESTAMP>
```
The script restores all pre-migration files and validates that restored SHA-256 digests match `backup_manifest.json` byte-for-byte.

---

## 9. Release & Versioning Procedures

### Version Scheme Distinction
- **Plugin API Specification (`VERSION` and `CORE_API_VERSION`):** Currently `1.1.0`. Governs the public plugin interface, manifest schema, slash commands, and lifecycle hooks. SemVer git tags for this specification are `v1.0.0` and `v1.1.0`.
- **Core Engine Releases:** Currently `core-v0.1.0-rc3`. Governs the complete agent harness, runtime loop, safety boundaries, container packaging, and operator scripts. Git tags follow `core-v<major>.<minor>.<patch>[-rcN]`.

### Verification Steps Before Tagging a Release
1. Run `python scripts/check_architecture_docs.py` -> exit code 0.
2. Run `python scripts/check_docs_claims.py` -> exit code 0.
3. Run `python -m unittest agent.tests.infra.test_import_layers` -> exit code 0.
4. Run `python -m unittest agent.tests.plugins.test_docs_and_image` -> exit code 0.
5. Run full CI test suite: `.\scripts\run-tests.ps1` -> exit code 0.
6. Run soak test suite: `.\scripts\soak.ps1 -Seed 42` -> exit code 0.

---

## 10. Branch Merge Status & Operator Integration Order

### Current Branch Topology
- **Merged Historical Branches (`p11..p20`):** All local feature and hardening branches (`p11-plugins`, `p12-safety`, `p13-sim-and-scoring`, `p14-tagged-state`, `p14b-verify`, `p14c-summaries`, `p15-plugin-sdk`, `p16-pet-demo`, `p17-self-plugins`, `p18-release`, `p19-rc-hardening`, `p20-soak`) are ancestors of `main` and have already been merged into `main` (verified by `git branch --merged main`).
- **Unmerged Branches (`p21-docs`, `p22-doc-fixes`):** Only `p21-docs` and `p22-doc-fixes` are not yet merged to `main` (verified by `git branch --no-merged main`).
- **Supersession:** `p22-doc-fixes` was branched directly from the HEAD of `p21-docs` and contains the complete P21 documentation overhaul plus all P22 accuracy corrections.

### Operator Merge Sequence
The human operator can integrate documentation into `main` with the following clean fast-forward or merge:

```powershell
# 1. Switch to main
git checkout main

# 2. Merge p22-doc-fixes (incorporates all p21 and p22 work)
git merge p22-doc-fixes

# 3. Verify documentation and architecture integrity
python scripts/check_architecture_docs.py
python scripts/check_docs_claims.py
python -m unittest agent.tests.infra.test_import_layers
```

*Note: Do not re-merge p11 through p20, as their commits are already reachable from main.*
