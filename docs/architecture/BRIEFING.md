# Architecture Briefing: SELF Core & Specializations

**Git Commit:** `14ffa606468920a97c672b39fbf3a43fccc52bdf`  
**Date:** 2026-10-17  
**Scope:** Complete baseline architecture briefing for planning modular core and specialization bodies.

---

## 1. What the System Is and How It Runs

**SELF** is an autonomous, self-directed AI agent. SELF is an autonomous, self-directed AI agent that owns its persistent goals, maintains an evolving plan, invents and tests Python tools, and evaluates human input as advice to weigh rather than commands to obey `[read] agent/runtime/loop.py:35-38`.

In practice, the system runs inside an isolated Debian Bookworm Docker container (`self-self-1`) `[read] Dockerfile:1, docker-compose.yml:3`. The agent's Python harness code is built into the container image at `/opt/agent` and set strictly read-only (`chmod 0444/0555`) `[read] Dockerfile:44-46`. Runtime persistence is achieved through a single host volume bind-mount: `./workspace` on the host is mounted to `/home/entity` inside the container `[read] docker-compose.yml:15-19`. The process executes as `USER root` inside the container namespace, using bridge networking for outbound API and HTTP access without exposing host ports or running in privileged mode `[read] Dockerfile:50, docker-compose.yml:20-23`.

The primary entry point is `python -m agent.wake` `[read] Dockerfile:52`, which boots a `WakeCoordinator` `[read] agent/ui/wake.py:686`. The coordinator starts a persistent session, runs a terminal user interface (TUI) with a live cardiac monitor, manages independent background conversation threads, and runs autonomous exploration cycles via `AgentLoop` `[read] agent/runtime/loop.py:167`.

---

## 2. Diagram-Style Outline of One Cycle

```
========================================================================================
                                 AUTONOMOUS CYCLE OUTLINE
========================================================================================

  [1. CYCLE INIT & PROMPT ASSEMBLY]
      │
      ├── Load Top Plan Goals & Retrieval Query (PlanStore -> state/plan.json)
      ├── Load Environmental Context (Verified Map + Self Notes + Memories + Lessons)
      ├── Check In-Flight Human Messages (HumanInbox -> state/human_input.jsonl)
      ├── Fetch Recent Tool-Creation Failure Diagnostics (logs/actions.jsonl)
      └── Build System Prompt (Autonomy Rules + Helper Models Registry + Identity Record)
      │
      ▼
  [2. TOOL RETRIEVAL]
      │
      ├── Base Tools (22 built-ins: run_shell, read_file, write_file, update_plan, etc.)
      ├── Capability Synthesis (create_tool definition)
      └── Dynamic Tool Retrieval (ToolRegistry keyword search over workspace/tools/*)
      │
      ▼
  [3. INNER TOOL ROUNDS LOOP] ◄────────────────────────────────────────┐
      │                                                                │
      ├── Check STOP File (/home/entity/STOP) & Pause Provider         │
      ├── Daily Ledger Token Reservation (DailyTokenLedger.reserve)    │
      │   └── If Exceeded: Pause until UTC midnight reset              │
      ├── Model Call (BudgetedLLM -> Anthropic/Ollama Client)          │
      ├── Daily Ledger Settle (Settle actual tokens vs reservation)    │
      │                                                                │
      ├── Decision Branch:                                             │
      │   ├── IF Model Emits Tool Uses:                                │
      │   │   ├── Check duplicate tool action within run (Anti-Loop)   │
      │   │   ├── Execute Tool (ToolRunner: shell, FS, HTTP, or custom)│
      │   │   ├── Append tool_result to conversation messages          │
      │   │   └── REPEAT INNER TOOL ROUNDS ────────────────────────────┘
      │   │
      │   └── IF Model Emits Text Response (No tool calls):
      │       └── BREAK TOOL ROUNDS LOOP
      │
      ▼
  [4. CYCLE WRAP-UP & REFLECTION]
      │
      ├── Increment completed_iterations counter
      ├── Plan Review Check (Require update_plan OR log record_unchanged)
      ├── Plan Hygiene (Purge "done" and "dropped" goals from state/plan.json)
      ├── Checkpoint State (Save state/run_checkpoint.json & learning record)
      └── Schedule Asynchronous Reflection (If tool failed, map changed, or tool made)
========================================================================================
```

---

## 3. The 15 Facts a Planner Most Needs to Know

1. **Strict 6-Layer Downward Import Graph:** The 12 packages obey a strict acyclic layering (`infra:0`, `llm:1`, `tools/learning/helper_models/identity/body/plugins:2`, `runtime:3`, `session/reporting:4`, `ui:5`). Package `agent.tools` never imports `agent.runtime` `[read] agent/tests/infra/test_import_layers.py:11-22`.
2. **Cycle vs. Iteration Semantics:** A "cycle" is an outer exploration loop turn. A "tool round" is an inner request/response turn with the model within a cycle. An "iteration" is the counter of fully completed cycles `[read] agent/runtime/loop.py:419, 511, 628`.
3. **No Tool Round Ceiling:** There is intentionally no per-cycle tool round ceiling; the model continues executing tools until it returns a pure text report or hits a hard run bound (STOP file, wall-clock, token budget) `[read] agent/runtime/loop.py:509`.
4. **Daily Token Ledger is the Only Enforced Budget:** All per-run token budget options are deprecated and ignored (`self.token_budget = None`). Spending is bounded strictly by `DailyTokenLedger` tracking tokens in `state/daily_token_budget.json` against `SELF_MAX_TOKENS_PER_DAY` (default 200,000), resetting at UTC midnight `[read] agent/llm/llm.py:58-60, agent/infra/hardening.py:55`.
5. **Exact Repetition Blocker:** Exact duplicate `(tool_name, arguments)` invocations within the same run are blocked by the harness, forcing the model to try a different investigation or report `[read] agent/runtime/loop.py:583-588`.
6. **Dynamic Tool Sandbox Pipeline:** When creating tools via `create_tool`, the code must have typed `run(...)` arguments, be approved by a Critic LLM call (`CRITIC_PROMPT`), and pass unittests run in an isolated subprocess with secrets stripped `[read] agent/tools/tool_registry.py:225-403`.
7. **Attempt Limits on Tool Creation:** An agent is limited to 3 creation attempts per tool name per run. The 3rd failure logs a durable lesson to `workspace/memory/lessons.jsonl` and blocks further attempts in that run `[read] agent/tools/tool_registry.py:236-238, 413-420`.
8. **Root Shell Privilege Discrepancy:** While Python's `write_file` blocks modifying `/opt/agent/` or managed identity files, `run_shell` executes `/bin/bash` as `USER root` inside the container namespace, allowing raw bash commands to bypass Python-level path guards `[read] Dockerfile:50, agent/tools/base_tools.py:461, 540-547`.
9. **Single Persistent Workspace Bind-Mount:** Only `./workspace` is mounted into the container (at `/home/entity`). The host filesystem, Docker socket, and `eval/` are completely inaccessible `[read] docker-compose.yml:15-19`.
10. **Mandatory Human Input Arbitration:** Human inputs are never treated as commands. The agent must evaluate each input in a cycle and record one of five explicit decisions (`accepted`, `modified`, `declined`, `deferred`, `noted`) with an evidence-backed reason in `state/plan.json` `[read] agent/learning/plan.py:420-475`.
11. **Plan Hygiene Purging:** The agent owns `state/plan.json`. Goals marked `"done"` or `"dropped"` are automatically purged from persistent state at cycle end to bound prompt growth `[read] agent/learning/plan.py:550-575`.
12. **Fixed Base Model + Dynamic Helpers:** The primary thinking model is fixed at startup (`base_model`). It cannot be switched. Helper models can only be queried via `ask_model` for plain-text sub-tasks or used for critic/reflection checkpoints `[read] agent/llm/llm.py:227-229, agent/tools/base_tools.py:56-64`.
13. **Hard Stop Controls Always Win:** The `/stop` command, SIGINT/SIGTERM, and `workspace/STOP` cannot be overridden or ignored by the model. When detected, loops break immediately without a shutdown LLM call `[read] agent/runtime/loop.py:37, 230-235, agent/ui/wake.py:1456-1465`.
14. **Protected Core Harness Patching:** The agent cannot directly modify `/opt/agent/core/`. It can only generate unified diffs saved to `state/proposed_patches/` via `propose_core_patch` for the human operator to inspect and apply from the host `[read] agent/tools/base_tools.py:262-268, 513-516`.
15. **Hidden Eval Isolation:** The evaluation framework `eval/` is excluded by `.dockerignore`, not mounted in `docker-compose.yml`, and only runs via host scripts with read-only mounts `[read] .dockerignore:4, docker-compose.yml:33-49`.

---

## 4. State Files and Prompt Injection Status

| File Path | Purpose | Loaded into Prompts? | Schema / Caps |
| :--- | :--- | :--- | :--- |
| `state/plan.json` | Persistent multi-goal autonomous plan | **YES** (cycle prompt summary) `[read] loop.py:486` | Bounded by hygiene; completed goals purged |
| `state/identity.json` | Core agent identity operating record | **YES** (system prompt) `[read] loop.py:358` | Max 20 traits; evidence-backed only |
| `state/models.json` | Model registry: primary & helper models | **YES** (system prompt) `[read] loop.py:352` | Max 32 models, 1 MB max file size |
| `state/map.json` | Verified environment facts | **YES** (cycle prompt map) `[read] loop.py:453` | Key-value store with confidence levels |
| `state/self_notes.md` | Curated working notes & heuristics | **YES** (cycle prompt notes) `[read] loop.py:452` | Bounded to 10,000 characters |
| `state/memory.jsonl` | Persistent episodic memories | **YES** (top query matches) `[read] loop.py:454` | JSONL: `task`, `lesson`, `tags`, `outcome` |
| `memory/lessons.jsonl` | Recorded tool-creation failure lessons | **YES** (legacy lessons) `[read] loop.py:455` | JSONL: Appends on 3rd failed tool attempt |
| `state/human_input.jsonl`| Inflow queue for human messages | **YES** (cycle prompt inbox) `[read] loop.py:494` | JSONL: Appended from TUI / file |
| `state/handoff.json` | Inter-session handoff | **YES** (prior report & plan) `[read] wake.py:1042` | Bounded to 6,000 chars; overflow archived |
| `state/handoff_last_good.json`| Fallback backup handoff | **YES** (only on recovery) `[read] session.py:98` | Backup of last valid handoff |
| `state/handoff_overflow.json`| Excess handoff text | **NO** | Stores overflow when handoff > 6,000 chars |
| `state/active_session.json` | Live session PID and start time | **NO** | Overwritten on start; deleted on clean finish |
| `state/sessions.jsonl` | Session archive with usage/reasons | **NO** | JSONL: Historical log of completed sessions |
| `state/run_checkpoint.json` | Cycle-by-cycle crash recovery | **NO** (resumes task) `[read] loop.py:389` | Overwritten after every cycle |
| `state/identity_log.md` | Append-only audit log of identity | **NO** (viewable via `/identity`) | Dated list of trait and name changes |
| `state/about_human.md` | Human profile & preferences | **NO** (viewable via `/about me`) | Numbered lines bounded to 10,000 chars |
| `state/self_inquiry.md` | First-awakening philosophical inquiry | **NO** (viewable via `/self`) | Static markdown from first awakening |
| `state/model_decisions.jsonl`| Model routing choices | **NO** (viewable via `/models`) | JSONL: Decision, moment, choice, reason |
| `state/model_outcomes.jsonl` | Model call metrics & outcomes | **NO** | JSONL: Metric values, latency, errors |
| `state/daily_token_budget.json`| Enforced daily token ledger | **NO** (telemetry displays remaining) | Resets at UTC midnight |
| `state/wake_snapshot.json` | Baseline workspace & uptime | **NO** (changes in greeting) | Detects workspace/tool changes on boot |
| `logs/actions.jsonl` | Central system event log (105 events)| **NO** (failure context extracts 8 errors) | Unbounded append-only log |
| `config/plugins.json` | Enabled plugins & SHA-256 hashes | **NO** (embodiment & goal notes injected) | Human-owned; mounted read-only into `/config` |
| `plugins/<name>/state/` | Per-plugin private state storage | **NO** | Plugin-managed isolated runtime state |

---

## 5. Tool Subsystem Summary (23 Tools)

| Tool Name | One-Line Purpose | Risk Class & Core vs Body |
| :--- | :--- | :--- |
| `list_models` | List base and helper models with assessments and call stats `[read] base_tools.py:25`. | Reads (Core) |
| `record_model_assessment`| Record evidence-backed assessment and ratings of a helper model `[read] base_tools.py:30`.| Writes (Core) |
| `probe_model` | Run 4 standardized capability probes against a helper model `[read] base_tools.py:44`. | Executes / Network (Core) |
| `research_model` | Fetch helper model's official documentation and extract facts `[read] base_tools.py:50`. | Network (Core) |
| `ask_model` | Delegate a bounded plain-text sub-task to a helper model `[read] base_tools.py:56`. | Network (Core) |
| `record_delegation_outcome`| Record judgment on whether an `ask_model` result helped `[read] base_tools.py:66`. | Writes (Core) |
| `run_shell` | Run unrestricted Bash command in container as root (30s timeout) `[read] base_tools.py:75`.| Executes (Body: Linux container) |
| `read_file` | Read text file from container with 20,000-char cap `[read] base_tools.py:87`. | Reads (Body: Container FS) |
| `write_file` | Write text in workspace, rejecting harness & identity paths `[read] base_tools.py:99`.| Writes (Body: Container FS) |
| `list_dir` | List container directory entries (max 500) `[read] base_tools.py:112`. | Reads (Body: Container FS) |
| `http_get` | Make HTTP GET request with host/path egress logging `[read] base_tools.py:124`. | Network (Body: Container WAN) |
| `update_environment_map`| Record verified environment facts in `state/map.json` `[read] base_tools.py:137`. | Writes (Core) |
| `read_plan` | Read active multi-goal plan from `state/plan.json` `[read] base_tools.py:160`. | Reads (Core) |
| `update_plan` | Modify plan goals or record human input decision with reason `[read] base_tools.py:165`.| Writes (Core) |
| `research_provider` | Fetch official provider documentation without signing up `[read] base_tools.py:217`. | Network (Core) |
| `record_provider_verification`| Record verified free-tier provider limits to `providers.json` `[read] base_tools.py:222`.| Writes (Core) |
| `request_provider_key` | Write human-only request for missing API key to `key_requests.md` `[read] base_tools.py:230`.| Writes (Core) |
| `ask_brain` | Query supplementary provider via brain router `[read] base_tools.py:235`. | Network (Core) |
| `benchmark_providers` | Run small local eval to benchmark configured providers `[read] base_tools.py:243`. | Network (Core) |
| `probe_local_ollama` | Check if local Ollama daemon is reachable in container `[read] base_tools.py:248`. | Network / Reads (Body) |
| `request_capability` | Write human-facing request for capability expansion `[read] base_tools.py:253`. | Writes (Core) |
| `propose_core_patch` | Save unified diff under `state/proposed_patches/` for human review `[read] base_tools.py:262`.| Writes (Core) |
| `create_tool` | Create/update reusable Python tool with critic & test verification `[read] tool_registry.py:22`.| Executes / Writes / Network (Core) |

---

## 6. Coupling Hotspots Ranked by Difficulty

To decouple the core agent from the Linux container and enable specialized bodies (Antivirus, IoT Robot):

1. **Body Interface (`Sense` / `Act` / `Permissions`) — Difficulty: HIGH [IMPLEMENTED in Prompt 10]**
   - *Implementation:* `agent/body/base.py` and `agent/body/container.py` provide abstract `Body` and default `ContainerBody`.
2. **Prompt Assembly & System Prompt — Difficulty: MEDIUM [IMPLEMENTED in Prompt 10 & 11]**
   - *Implementation:* `loop.py` decomposes prompts into core rules, dynamic body embodiment (`body.describe().embodiment`), and delimited plugin embodiment and seeds.
3. **State Partitioning & Namespace Organization — Difficulty: MEDIUM [IMPLEMENTED in Prompt 11]**
   - *Implementation:* Plugin state is isolated in `workspace/plugins/<name>/state/`, excluded from hash verification.
4. **Tool Registry & Dynamic Offerings — Difficulty: LOW [IMPLEMENTED in Prompt 11]**
   - *Implementation:* `PluginManager` dynamically registers namespaced tools `<plugin>.<tool>`, validates schemas, rejects core collisions, and dispatches calls.
5. **Plan Seeding & Startup Tasks — Difficulty: LOW [IMPLEMENTED in Prompt 10 & 11]**
   - *Implementation:* Initial seed task parameterized via `body.initial_orientation_task()` and plugin starting goal seeds.
6. **Identity Framing & Default Interests — Difficulty: LOW [IMPLEMENTED in Prompt 10]**
   - *Implementation:* `default_identity(body)` configures interests and inquiry context from the active body.

---

## 7. Top 10 Known Issues

1. **Root Privilege Discrepancy:** `run_shell` executes as container root, allowing raw bash commands to bypass Python-level path restrictions enforced by `write_file` `[read] Dockerfile:50, base_tools.py:461, 540`.
2. **Deprecated CLI Flags Accepted:** `--token-budget` is accepted in CLI arguments but ignored at runtime because `DailyTokenLedger` is the sole active token limit `[read] loop.py:708, llm.py:58-60`.
3. **Dead Constants in `model_decisions.py`:** Retains deprecated constants (`MAX_CHECKPOINTS_PER_SESSION`, `CHECKPOINT_OUTPUT_TOKENS`, etc.) cluttering module scope `[read] model_decisions.py:28-31`.
4. **Root Compatibility Shims:** Six flat modules remain at `agent/` root (`wake.py`, `loop.py`, `report.py`, etc.) duplicating package entry points for backwards compatibility `[read] agent/*.py`.
5. **Tracked Workspace Tool Clutter:** `workspace/tools/` contains duplicate historical tool versions (e.g. `timer_service_info2`, `dir_tree_visualizer_fixed`) from previous runs `[read] workspace/tools/`.
6. **Inconclusive Probes Treated as Unknown:** Ambiguous capability probes log `inconclusive` rather than failure, allowing poorly performing models to evade failure penalties in stats `[read] model_probe.py:255-260`.
7. **Hardcoded Python Package Startup Priority:** `wake.py:1389` forces the first cycle to run `pip list`, breaking non-Python or embedded bodies `[read] wake.py:1385-1395`.
8. **Live Calls in `disk_tool_demo.py`:** Has no dry-run or mock mode, making it unrunnable in provider-free CI testing `[read] agent/ui/disk_tool_demo.py:1-60`.
9. **POSIX Bash Dependency:** `run_shell` explicitly calls `["/bin/bash", "-lc", cmd]`, preventing execution on Windows hosts or BusyBox containers without `/bin/bash` `[read] base_tools.py:461`.
10. **Migration Backup File Leftovers:** Migration scripts left multiple `.bak` and `.pre_autonomy_backup` files in `workspace/state/` `[read] workspace/state/*.bak*`.

---

## 8. Open Unknowns

1. **Live Provider Concurrency & Multi-Threading:** How real Ollama Cloud and Anthropic endpoints handle burst traffic when autonomous loop tool rounds run simultaneously with background conversation threads under live network conditions.
2. **Container OOM Kill Recovery:** Whether the host Docker daemon killing the container process under memory exhaustion (`mem_limit: 4g`) leaves `state/active_session.json` reliably intact for crash recovery.
3. **Helper Model Routing Effectiveness:** Real task success rates when `ModelDecisions` routes critic or delegation moments to smaller helper models, pending execution of the full A/B campaign in `eval/ab_plan.py`.
4. **Embedded Performance:** Resource utilization and TUI cardiac trace responsiveness when running on resource-constrained single-core ARM64 hardware.
