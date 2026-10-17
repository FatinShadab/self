# Document 11: Known Issues, Tech Debt & Open Unknowns

**Git Commit:** `14ffa606468920a97c672b39fbf3a43fccc52bdf`  
**Date:** 2026-10-17  
**Status:** Read-only architecture documentation

---

## 1. Top 10 Known Issues & Bugs

### 1. Inconsistent Privilege Boundary Between `write_file` and `run_shell`
- **Issue:** `write_file` enforces Python-level path restrictions preventing writes to `/opt/agent/core/` and managed identity files `[read] agent/tools/base_tools.py:540-547`. However, `run_shell` executes `/bin/bash` commands as `USER root` `[read] Dockerfile:50`.
- **Impact:** An agent using `run_shell("chmod +w /opt/agent/core/loop.py && echo ... >> /opt/agent/core/loop.py")` can bypass the Python-level protection and mutate the harness within the container rootfs `[inferred]`.
- **Location:** `[read] agent/tools/base_tools.py:461, Dockerfile:50`.

### 2. Deprecated `--token-budget` Flags Still Accepted but Silently Ignored
- **Issue:** The `--token-budget` argument is accepted by `agent/runtime/loop.py` and `agent/ui/wake.py`, but `BudgetedLLM` explicitly sets `self.token_budget = None` and comments state: *"token_budget, adaptive_budget, max_token_budget are ignored; daily_ledger is the only active token limit"* `[read] agent/llm/llm.py:58-60`.
- **Impact:** Operators specifying `--token-budget 5000` in scripts will find the setting has zero effect, as only the daily ledger ceiling (`SELF_MAX_TOKENS_PER_DAY`) is enforced.
- **Location:** `[read] agent/llm/llm.py:58-60, agent/runtime/loop.py:705-724, agent/ui/wake.py:702`.

### 3. Deprecated Dead Constants in `model_decisions.py`
- **Issue:** Four module-level constants are retained with `# Deprecated:` comments:
  - `MAX_CHECKPOINTS_PER_SESSION = 0` (checkpoint cap removed)
  - `CHECKPOINT_OUTPUT_TOKENS = 32_768` (replaced by registry ceiling)
  - `RETRY_OUTPUT_TOKENS = 32_768` (replaced by registry ceiling)
  - `MAX_DELEGATION_OUTPUT_TOKENS = 32_768` (replaced by registry ceiling)
- **Impact:** Dead code cluttering module scope.
- **Location:** `[read] agent/helper_models/model_decisions.py:28-31`.

### 4. Compatibility Shims in `agent/` Root
- **Issue:** Six shim modules reside at the root of `agent/`:
  - `agent/wake.py` -> dispatches to `agent.ui.wake`
  - `agent/loop.py` -> dispatches to `agent.runtime.loop`
  - `agent/report.py` -> dispatches to `agent.reporting.report`
  - `agent/model_outcomes.py` -> dispatches to `agent.helper_models.model_outcomes`
  - `agent/disk_tool_demo.py` -> dispatches to `agent.ui.disk_tool_demo`
  - `agent/event_log.py` -> re-exports `EventLogger` from `agent.infra.event_log`
- **Impact:** Duplicate module paths create confusion between legacy flat paths and canonical package paths.
- **Location:** `[read] agent/*.py`.

### 5. Disk Clutter of Numbered Duplicate Tools in `workspace/tools/`
- **Issue:** The tracked `workspace/tools/` directory contains numerous historical tool iterations created during earlier testing (e.g. `proc_net_tcp_parser` vs `proc_net_tcp_parser2`; `timer_service_info` vs `timer_service_info2`; `dir_tree_visualizer` vs `dir_tree_visualizer_fixed`).
- **Impact:** Unnecessary disk usage and pollution of the keyword search retrieval index.
- **Location:** `[read] workspace/tools/`.

### 6. Inconclusive Model Probes Treated as Unknown Rather than Failure
- **Issue:** When a capability probe produces an ambiguous response, `ModelProber` logs `inconclusive` rather than `failed`.
- **Impact:** A poorly performing model may not be marked as failing in `measured_stats`, allowing it to be selected repeatedly by `ModelDecisions`.
- **Location:** `[read] agent/helper_models/model_probe.py:255-260`.

### 7. Hardcoded Startup Priority Expects Python Package Inventory
- **Issue:** `WakeCoordinator._run_session()` inspects `state/map.json` for a `packages` key; if absent, it hardcodes an imperative startup priority: *"Startup priority: I will immediately inventory installed Python packages before broader exploration"* `[read] agent/ui/wake.py:1389`.
- **Impact:** Breaks specialization bodies (e.g. an IoT robot or antivirus scanner) that have no concept of installed Python packages.
- **Location:** `[read] agent/ui/wake.py:1385-1395`.

### 8. `disk_tool_demo.py` Has No Dry-Run Mode and Calls Live Providers
- **Issue:** `agent/ui/disk_tool_demo.py` unconditionally calls `LLMClient(logger)` and dispatches live model queries on invocation without `--help` or dry-run guards.
- **Impact:** Cannot be executed during provider-free testing or CI verification.
- **Location:** `[read] agent/ui/disk_tool_demo.py:1-60`.

### 9. Hardcoded POSIX Shell Assumption in `run_shell`
- **Issue:** `run_shell` invokes `["/bin/bash", "-lc", cmd]`.
- **Impact:** Cannot run on a native Windows host without WSL/Git Bash, nor on minimal Alpine/BusyBox containers where `/bin/bash` does not exist (only `/bin/sh`).
- **Location:** `[read] agent/tools/base_tools.py:461`.

### 10. Memory and Identity Framing Migrations Left Multiple Backup Files
- **Issue:** Migration scripts left multiple timestamped backups in `workspace/state/`:
  - `memory.jsonl.20261017_102740.bak`, `memory.jsonl.20261017_103809.bak`
  - `identity.json.pre_autonomy_backup`
  - `handoff.json.pre_autonomy_backup`
- **Impact:** Bloats the repository and complicates clean state resets.
- **Location:** `[read] workspace/state/*.bak*`.

---

## 2. Documentation Contradictions

| Documentation Source | What the Doc Says | What the Code Actually Does | Evidence |
| :--- | :--- | :--- | :--- |
| `agent/tools/README.md` | Mentions that tools can be imported as flat modules | Tools must be imported canonically as `from tool import run`. Packaging aliases are only temporary during attempts. | `[read] agent/tools/tool_registry.py:44-47` |
| `agent/llm/README.md` | References per-run token budget options | `token_budget` is explicitly set to `None`; only `daily_ledger` is enforced. | `[read] agent/llm/llm.py:58-60` |
| Root `README.md` | References invoking `python agent/loop.py` | Canonical module path is `python -m agent.runtime.loop`. | `[read] agent/runtime/loop.py:753` |

---

## 3. Open Unknowns (Empirical Questions Requiring Live Runs)

Because live provider calls were prohibited during this investigation, the following questions cannot be determined from static analysis alone:

1. **Live Multi-Provider Quota Behavior:**
   - How do real Ollama Cloud and Anthropic endpoints respond to sustained concurrency when multiple conversation threads run in parallel?
   - *What is needed to verify:* An active test run with configured API keys observing `llm_key_rotated` and `DailyTokenLedger` settlement under load.
2. **Container OOM Kill Recovery:**
   - If the Linux kernel terminates the container process via OOM killer (`mem_limit: 4g`), does `state/active_session.json` reliably remain in `"running"` status allowing the subsequent wake to detect a crash, or can filesystem buffering lose the write?
   - *What is needed to verify:* A stress script allocating >4GB RAM inside the container while monitoring `session_crash_recovered` on reboot.
3. **Helper Model Routing Quality in Real Tasks:**
   - Does `ModelDecisions.decide_model()` consistently route tool critic moments to smaller helper models, and do those helper models achieve acceptable approval accuracy compared to the base model?
   - *What is needed to verify:* Executing the full 72-run A/B evaluation campaign defined in `eval/ab_plan.py`.
4. **Behavior on Low-Resource Embedded Devices:**
   - If the core is ported to an ARM64 IoT controller, how does the Textual TUI cardiac monitor perform over high-latency serial or SSH connections?
   - *What is needed to verify:* Profiling CPU usage of `cardiac_monitor_frame()` on a single-core Linux system.
