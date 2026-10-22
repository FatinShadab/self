# SELF Workspace Migration Guide: Core Release Candidates

**Scope:** Upgrading existing workspaces from pre-modular architectures (Prompts 01–08) or intermediate versions (Prompts 09–13) to **Core Engine Release Candidates** (`core-v0.1.0-rc1` through `core-v0.1.0-rc3`) and **Plugin API Specification v1.1.0**.  
**Author:** SELF Autonomous Agent Core Maintenance Team  
**Date:** 2026-10-22  

---

### Versioning Explanation
- **Core Engine Releases (`core-v0.1.0-rc1..rc3`):** Governs the full agent system, Docker packaging, runtime loop, safety mechanisms, soak test suite, and operator tooling.
- **Plugin API Specification (`1.1.0`):** Tracked in `VERSION` and `CORE_API_VERSION`. Governs manifest schemas, plugin lifecycle hooks, dynamic tool registration, and custom slash commands.

---

## 1. Summary of Architectural Changes (Prompts 09–20)

Across Prompts 09 to 20, the SELF runtime was decoupled from a monolithic container script into a modular, headless core with extensible bodies, hot-pluggable skills, and soak reliability verification:

1. **State Partitioning & Namespace Isolation**:
   - **Core State (`workspace/state/`)**: Contains only core agent memories, multi-goal plans, verified environmental maps, daily token budgets, identity records, and handoffs.
   - **Plugin Private State (`workspace/plugins/<name>/state/`)**: Each plugin maintains private runtime data isolated from the core and other plugins. Crucially, the `state/` subdirectory is excluded from the plugin's SHA-256 hash calculation, allowing plugins to mutate runtime state without triggering hash mismatch warnings.
   - **Plugin Development Drafts (`workspace/plugin_dev/<name>/`)**: Plugins under development by the agent are scaffolded into `workspace/plugin_dev/`. The runtime plugin loader strictly ignores `plugin_dev/`; drafts can only be promoted and enabled by explicit human action.
   - **Append-Only Cost Ledger (`workspace/state/cost_ledger.jsonl`)**: Measures actual tool and plugin token spend, cycle counts, and wall-clock times to enforce stop-loss boundaries.

2. **Human-Controlled Config Mount (`/config`)**:
   - The host directory `./config` is mounted strictly **read-only** into the container at `/config`.
   - **`config/plugins.json`**: Authoritative manifest of enabled plugins and their pinned SHA-256 hashes. The agent cannot modify this file from inside the container.
   - **`config/permissions.json`**: Declarative human policy mapping plugins and tools to permission levels (`L0_OBSERVE`, `L1_REVERSIBLE_LOCAL`, `L2_IRREVERSIBLE_LOCAL`, `L3_ACTUATION`).
   - **`config/egress_allowlist.txt`**: Allowlist of approved outbound domains and IP prefixes enforced by the egress proxy sidecar.

3. **Tagged State & Provenance**:
   - Every state entry across `memory.jsonl`, `map.json`, `plan.json`, `identity.json`, `self_notes.md`, and `tools/**/meta.json` now includes `plugin` (`"core"` or plugin name) and `body` (`"container"`, `"sim"`, etc.) tags.
   - If a plugin is disabled or unplugged, its tagged goals and notes are hidden or filtered from cycle prompts without data loss.

4. **Bounded Memory Summaries**:
   - Pre-migration memory files often contained multi-thousand-character uncompressed reports in `memory.jsonl`, threatening context limits.
   - Migration bounds `lesson` fields to ≤280 characters using deterministic extraction, while preserving full report text under `workspace/state/reports/report_migrated_XXXXX.txt` linked via `report_path`.

---

## 2. Pre-Migration Checklist

Before running the migration:
1. Ensure all active Docker containers for the workspace are stopped:
   ```powershell
   docker compose down
   ```
2. Verify that your host Python environment (or Docker container) has access to the repository scripts.
3. Check available disk space (migration creates an uncompressed snapshot in `workspace/state/backups/`).

---

## 3. Step-by-Step Migration Procedure

### Step 1: Execute Automated Migration Script
Run `scripts/migrate_p14_tagged_state.py` against your target workspace:
```powershell
python scripts/migrate_p14_tagged_state.py --workspace workspace
```

**What the script does automatically:**
1. Creates a timestamped backup directory at `workspace/state/backups/<YYYYMMDDTHHMMSSZ>/`.
2. Copies all pre-migration candidate state files:
   - `state/memory.jsonl`
   - `state/map.json`
   - `state/plan.json`
   - `state/identity.json`
   - `state/self_notes.md`
   - All `tools/**/meta.json` files
3. Computes SHA-256 hashes of every backed-up file and writes `backup_manifest.json` into the backup directory.
4. Rewrites `state/memory.jsonl`: tags each record with `plugin: "core"` and `body: "container"`, extracts full reports >280 characters to `state/reports/`, and stores deterministic 280-char summaries.
5. Rewrites `state/map.json`, `state/plan.json`, `state/identity.json`, `state/self_notes.md`, and tool metadata files to ensure required provenance fields are present.

### Step 2: Set Up Host Config Directory
If your workspace repository lacks a `./config` directory, create one with baseline permissions and plugins:
```powershell
# Create config directory
New-Item -ItemType Directory -Path config -Force

# Create baseline empty plugins.json (zero plugins enabled)
Set-Content -Path config/plugins.json -Value '{"plugins": {}}' -Encoding UTF8

# Create baseline permissions.json
Set-Content -Path config/permissions.json -Value '{"version": 1, "grants": {}}' -Encoding UTF8
```

### Step 3: Verify Migrated Workspace
Run the live diagnostic check in dry-run mode:
```powershell
powershell -ExecutionPolicy Bypass -File scripts/live-check.ps1 -Workspace workspace -DryRun
```

All 13 checks should report `[PASS]`, with zero FAIL items.

---

## 4. Byte-for-Byte Rollback Procedure

If you encounter an issue or wish to revert to the exact pre-migration state, use the built-in restore mechanism.

### Step 1: Identify Your Backup Directory
Check `workspace/state/backups/`:
```powershell
Get-ChildItem -Path workspace/state/backups
```
Select the directory corresponding to your migration run (e.g. `workspace/state/backups/20261021T180000Z`).

### Step 2: Execute Byte-for-Byte Restore
Run `migrate_p14_tagged_state.py` with the `--restore` flag:
```powershell
python scripts/migrate_p14_tagged_state.py --workspace workspace --restore workspace/state/backups/<TIMESTAMP>
```

**What the restore process does:**
1. Reads `backup_manifest.json` from the backup directory.
2. Restores each file back to its original location in `workspace/`.
3. Verifies that the SHA-256 hash of each restored file matches the recorded hash in `backup_manifest.json` byte-for-byte.
4. Removes any newly generated `state/reports/report_migrated_*.txt` files created during that migration.

### Step 3: Confirm Clean Reversion
Run a diff check or verify hashes:
```powershell
git status
```
Any pre-migration state tracked by git will show clean working trees.

---

## 5. Ongoing Operations & Health Monitoring

After migrating:
1. **Live Check**: Run `scripts/live-check.ps1` periodically to inspect plugin states, hash mismatches, and cost ledger summaries.
2. **Run Analysis**: For extended autonomous runs, run `scripts/analyze-run.ps1 -Workspace workspace` to audit plan autonomy ratios, handoff file growth against the 6,000-character ceiling, and failure classifications.
3. **Plugin Management**: Enable plugins by adding their name and computed SHA-256 hash to `config/plugins.json`. Never modify plugin code in place without updating the pinned hash in `config/plugins.json`.
4. **Deterministic Soak Verification**: Run `scripts/soak.ps1` to test multi-cycle stability against simulated provider workloads without incurring token spend.
5. **Live Soak Invariant Gate**: Run `python scripts/live_soak_gate.py --workspace workspace --fail-on-warn` before commencing any live runs to verify token ledger and handoff size invariants.
