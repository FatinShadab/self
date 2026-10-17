# Document 01: Repository Map & Execution Topology

**Git Commit:** `14ffa606468920a97c672b39fbf3a43fccc52bdf`  
**Date:** 2026-10-17  
**Status:** Read-only architecture documentation

---

## 1. Directory Tree & Package Responsibilities

```
self/
├── .dockerignore                     # Excludes .env, .git, workspace, eval from image build [read] .dockerignore:1-7
├── .env.example                      # Template for host environment variables and model keys [read] .env.example:1-26
├── config/                           # Human-owned plugin configuration mounted read-only to /config [read] config/plugins.json:1-5
│   └── plugins.json                  # Recorded plugin enablement status and SHA-256 hash pins [read] config/plugins.json:1-5
├── docker-compose.yml                # Compose configuration defining 'self' and 'eval' services [read] docker-compose.yml:1-56
├── Dockerfile                        # Multi-stage image build for the agent runtime [read] Dockerfile:1-53
├── kill.sh                           # Host script to safely stop running containers [read] kill.sh:1-17
├── README.md                         # Project documentation and phase milestone overview [read] README.md:1-400
│
├── agent/                            # Image-owned Python agent harness [read] Dockerfile:32
│   ├── __init__.py                   # Package root init
│   ├── disk_tool_demo.py             # Root compatibility shim for disk tool demo CLI [read] agent/disk_tool_demo.py:1-12
│   ├── event_log.py                  # Root compatibility shim exporting EventLogger [read] agent/event_log.py:1-6
│   ├── loop.py                       # Root compatibility shim for agent.runtime.loop CLI [read] agent/loop.py:1-16
│   ├── model_outcomes.py             # Root compatibility shim for model outcome reporting [read] agent/model_outcomes.py:1-12
│   ├── report.py                     # Root compatibility shim for reporting CLI [read] agent/report.py:1-12
│   ├── requirements.txt              # Production Python package dependencies [read] agent/requirements.txt:1-15
│   ├── run.py                        # Headless entry point running WakeCoordinator without Textual [read] agent/run.py:1-42
│   ├── wake.py                       # Root compatibility shim for agent.ui.wake CLI [read] agent/wake.py:1-12
│   │
│   ├── body/                         # Body interface, capability declarations, sensing, ContainerBody (Layer 1)
│   │   ├── __init__.py               # Exports Body, BodyDescription, Capability, ContainerBody, ContainerMetrics [read] agent/body/__init__.py:1-12
│   │   ├── base.py                   # Abstract Body base class, BodyDescription, Capability dataclasses [read] agent/body/base.py:1-69
│   │   └── container.py              # ContainerBody wrapping shell, files, network, /proc and /sys metrics [read] agent/body/container.py:1-582
│   │
│   ├── helper_models/                # Multi-model management, probing, routing, and outcomes (Layer 2)

│   │   ├── __init__.py               # Exports ModelProber, ModelDecisions, ModelOutcomes [read] agent/helper_models/__init__.py:1-11
│   │   ├── model_decisions.py        # Model selector/picker, delegation routing, decision logging [read] agent/helper_models/model_decisions.py:1-720
│   │   ├── model_outcomes.py         # Appends and analyzes structured outcome observations [read] agent/helper_models/model_outcomes.py:1-115
│   │   └── model_probe.py            # Runs 4 standardized capability probes against helper models [read] agent/helper_models/model_probe.py:1-315
│   │
│   ├── identity/                     # Agent identity, voice, traits, and first awakening (Layer 2)
│   │   ├── __init__.py               # Exports IdentityStore, resolve_name_context [read] agent/identity/__init__.py:1-8
│   │   ├── identity.py               # Stores identity.json, voice, trait reflections, core patches [read] agent/identity/identity.py:1-730
│   │   ├── migration.py              # Framing migrations for identity records [read] agent/identity/migration.py:1-120
│   │   └── name_context.py           # Classifies names into mythological, fictional, or style cues [read] agent/identity/name_context.py:1-154
│   │
│   ├── infra/                        # Low-level primitives: logging, locks, process runner (Layer 0)
│   │   ├── __init__.py               # Exports EventLogger, run_process, DailyTokenLedger [read] agent/infra/__init__.py:1-15
│   │   ├── event_log.py              # Structured JSONL event logging with secret redaction [read] agent/infra/event_log.py:1-120
│   │   ├── file_lock.py              # Cross-platform file locking (fcntl / msvcrt) [read] agent/infra/file_lock.py:1-40
│   │   ├── hardening.py              # DailyTokenLedger, RunCheckpoint, CapabilityRequests [read] agent/infra/hardening.py:1-140
│   │   ├── process_runner.py         # Subprocess execution with timeout, output cap, and streaming [read] agent/infra/process_runner.py:1-85
│   │   └── provider_calls.py         # Hard ceiling on total provider calls per process [read] agent/infra/provider_calls.py:1-30
│   │
│   ├── learning/                     # Long-term knowledge, memory, map, and plan (Layer 2)
│   │   ├── __init__.py               # Exports PlanStore, LearningStore, CoverageSummary [read] agent/learning/__init__.py:1-10
│   │   ├── exploration_coverage.py   # Computes exploration coverage over filesystem and tools [read] agent/learning/exploration_coverage.py:1-93
│   │   ├── learning.py               # Memory storage (memory.jsonl), self notes, environment map [read] agent/learning/learning.py:1-320
│   │   ├── memory_migration.py       # Migrates legacy memory items to modern schema [read] agent/learning/memory_migration.py:1-90
│   │   └── plan.py                   # Persistent plan store (plan.json), priority, review hygiene [read] agent/learning/plan.py:1-580
│   │
│   ├── llm/                          # LLM clients, budget wrappers, model registry, routing (Layer 1)
│   │   ├── __init__.py               # Exports LLMClient, BudgetedLLM, ModelRegistry [read] agent/llm/__init__.py:1-10
│   │   ├── brain_router.py           # Fallback routing and benchmark execution for brain providers [read] agent/llm/brain_router.py:1-198
│   │   ├── llm.py                    # LLMClient, BudgetedLLM, daily token reservation, key rotation [read] agent/llm/llm.py:1-367
│   │   ├── model_registry.py         # State machine for model capability, output caps, stats [read] agent/llm/model_registry.py:1-614
│   │   └── providers/                # Provider protocol and adapters
│   │       ├── __init__.py           # Package init [read] agent/llm/providers/__init__.py:1-6
│   │       ├── adapters.py           # Provider HTTP request adapters (Ollama, Anthropic, Cerebras) [read] agent/llm/providers/adapters.py:1-190
│   │       ├── base.py               # ProviderRequest, ProviderResponse dataclasses [read] agent/llm/providers/base.py:1-34
│   │       └── registry.py           # Registry of free-tier provider limits and docs [read] agent/llm/providers/registry.py:1-210
│   │
│   ├── plugins/                      # Plugin lifecycle, dynamic tool registration, hash pinning (Layer 2)
│   │   ├── __init__.py               # Exports PluginManager, PluginManifest, compute_plugin_hash [read] agent/plugins/__init__.py:1-25
│   │   ├── hello/                    # Shipped sample hello plugin fixture [read] agent/plugins/hello/plugin.json:1-35
│   │   ├── manager.py                # PluginManager: discovery, lifecycle, sync, hash checks [read] agent/plugins/manager.py:1-400
│   │   └── manifest.py               # PluginManifest schema validation and version checks [read] agent/plugins/manifest.py:1-200
│   │
│   ├── reporting/                    # Activity reporting and statistics aggregation (Layer 4)
│   │   ├── __init__.py               # Exports generate_report [read] agent/reporting/__init__.py:1-5
│   │   └── report.py                 # Generates markdown summary of sessions, spend, and tools [read] agent/reporting/report.py:1-230
│   │
│   ├── runtime/                      # Core autonomous cycle orchestration (Layer 3)
│   │   ├── __init__.py               # Exports AgentLoop, AgentConfig, RunSummary [read] agent/runtime/__init__.py:1-8
│   │   └── loop.py                   # Main autonomous cycle: prompt assembly, tool execution, report [read] agent/runtime/loop.py:1-754
│   │
│   ├── session/                      # Session management, headless WakeCoordinator, reflection (Layer 4)
│   │   ├── __init__.py               # Exports WakeCoordinator, run_headless, SessionStore, HumanInbox [read] agent/session/__init__.py:1-12
│   │   ├── coordinator.py            # Non-UI WakeCoordinator: session lifecycle, handoff, human inbox [read] agent/session/coordinator.py:1-903
│   │   ├── conversation.py           # Independent background conversation manager with dedicated LLM [read] agent/session/conversation.py:1-140
│   │   ├── reflection.py             # Scheduled background reflection threads and human Q&A [read] agent/session/reflection.py:1-360
│   │   ├── session.py                # Inter-session handoff, crash recovery, active_session.json [read] agent/session/session.py:1-240
│   │   └── version_check.py          # Pre-boot code hash verification moved to Layer 4 [read] agent/session/version_check.py:1-42
│   │
│   ├── tools/                        # Built-in base tools and dynamic tool creation (Layer 2)
│   │   ├── __init__.py               # Exports ToolRunner, ToolRegistry, TOOL_DEFINITIONS [read] agent/tools/__init__.py:1-8
│   │   ├── base_tools.py             # 22 built-in tools (shell, files, HTTP, plan, models, brain) delegating to body [read] agent/tools/base_tools.py:1-624
│   │   ├── benchmark.py              # Provider benchmark runner [read] agent/tools/benchmark.py:1-40
│   │   ├── tool_registry.py          # Dynamic tool creation pipeline, critic review, test runner [read] agent/tools/tool_registry.py:1-448
│   │   └── tool_worker.py            # Subprocess entry point executing custom tools via stdin JSON [read] agent/tools/tool_worker.py:1-28
│   │
│   ├── ui/                           # Terminal TUI front-end, cardiac monitor, voice (Layer 5)
│   │   ├── __init__.py               # Exports WakeCoordinator, run_tui, run_headless [read] agent/ui/__init__.py:1-8
│   │   ├── disk_tool_demo.py         # Live demonstration of disk usage tool [read] agent/ui/disk_tool_demo.py:1-60
│   │   ├── phase8_verify.py          # Verification CLI for Phase 8 identity and plan integration [read] agent/ui/phase8_verify.py:1-110
│   │   ├── version_check.py          # Backward-compatible shim re-exporting agent.session.version_check [read] agent/ui/version_check.py:1-55
│   │   ├── voice.py                  # Text-to-speech voice output helper [read] agent/ui/voice.py:1-125
│   │   └── wake.py                   # Textual UI front-end (SelfApp), cardiac trace, delegating to coordinator [read] agent/ui/wake.py:1-1390

│   │
│   └── tests/                        # 157 unit tests across all agent subsystems [ran]
│
├── eval/                             # Host-only hidden evaluation and A/B campaign framework [read] docker-compose.yml:25-50
│   ├── __init__.py                   # Package root
│   ├── ab_analyze.py                 # Analyzes A/B campaign outcomes and token spend
│   ├── ab_plan.py                    # Generates deterministic randomized A/B campaign execution plans
│   ├── ab_tasks.json                 # Task definitions for evaluation (hidden from agent image)
│   ├── ab_verify.py                  # Evaluates workspace artifacts produced by evaluation runs
│   ├── calibrate.py                  # Calibrates scoring models against reference ratings
│   ├── runner.py                     # Execution harness running evaluation runs inside isolated containers
│   └── tests/                        # 11 unit tests verifying evaluation harness isolation and scoring [ran]
│
├── scripts/                          # Host-side development, CI, and verification scripts
│   ├── ab-run.ps1                    # PowerShell runner for automated A/B evaluation campaigns
│   ├── build_system_map.py           # Deterministically generates docs/architecture/system-map.json [read]
│   ├── check_architecture_docs.py    # Static CI check ensuring system-map.json matches code [read]
│   ├── check_docstrings.py           # Validates python docstring presence and format
│   ├── migrate_identity_framing.py   # Migrates identity files to autonomy-first framing
│   ├── migrate_memory_framing.py     # Migrates memory files to autonomy-first framing
│   ├── plan-audit.ps1                # Audits plan store updates across cycles
│   ├── run-tests.ps1                 # Builds image and runs all harness and eval unit tests in Docker [read]
│   ├── run-tests.sh                  # Shell script equivalent of run-tests.ps1 for Linux hosts [read]
│   ├── verify-phase7.ps1             # Verification runner for Phase 7 milestones
│   └── verify-phase8.ps1             # Verification runner for Phase 8 milestones
│
├── docs/                             # Project documentation
│   └── architecture/                 # Full architecture specification and briefing (THIS DIRECTORY)
│
└── workspace/                        # Runtime persistent volume mounted to /home/entity [read] docker-compose.yml:17-18
    ├── logs/                         # actions.jsonl event log [read]
    ├── memory/                       # lessons.jsonl [read]
    ├── plugins/                      # Human-installed plugins (<name>/plugin.json, tools/, state/) [read]
    ├── self/                         # Writable extension layer (prompts, heuristics, themes) [read]
    ├── state/                        # Durable state files (plan.json, identity.json, models.json, etc.) [read]
    └── tools/                        # Registered agent-created tools with history/ and attempts/ [read]
```

---

## 2. Entry Points

| Entry Point | Path | Type | Invocation Command | Description |
| :--- | :--- | :--- | :--- | :--- |
| `agent.wake` | `agent/ui/wake.py` | Service / CLI | `python -m agent.wake [--headless]` | Container default entry point `[read] Dockerfile:52`. Textual TUI front-end delegating to headless WakeCoordinator. |
| `agent.run` | `agent/run.py` | CLI | `python -m agent.run [--headless]` | Headless entry point running WakeCoordinator directly without Textual TUI dependencies. |
| `agent.runtime.loop` | `agent/runtime/loop.py` | CLI | `python -m agent.runtime.loop [--task "..."]` | Direct invocation of autonomous exploration loop `[read] agent/runtime/loop.py:753`. Runs cycles until bounds or STOP. |
| `agent.reporting.report` | `agent/reporting/report.py` | CLI | `python -m agent.reporting.report [--since "..."]` | Generates markdown summary report of agent activity, token spend, and discoveries `[read] agent/reporting/report.py:228`. |
| `agent.helper_models.model_outcomes` | `agent/helper_models/model_outcomes.py` | CLI | `python -m agent.helper_models.model_outcomes [workspace]` | Displays summary table of helper model decisions, outcomes, and stats `[read] agent/helper_models/model_outcomes.py:114`. |
| `agent.helper_models.model_decisions` | `agent/helper_models/model_decisions.py` | CLI | `python -m agent.helper_models.model_decisions [workspace]` | Displays summary of model decisions recorded in `state/model_decisions.jsonl` `[read] agent/helper_models/model_decisions.py:719`. |
| `agent.ui.version_check` | `agent/ui/version_check.py` | CLI / Hook | `python -m agent.ui.version_check` | Verifies harness source hash against expected image version `[read] agent/ui/version_check.py:53`. |
| `agent.ui.phase8_verify` | `agent/ui/phase8_verify.py` | CLI | `python -m agent.ui.phase8_verify` | Verification CLI for Phase 8 identity and plan integration `[read] agent/ui/phase8_verify.py:108`. |
| `agent.tools.tool_worker` | `agent/tools/tool_worker.py` | Subprocess | `python /opt/agent/tools/tool_worker.py` | Subprocess execution wrapper for custom tools; reads arguments on stdin, executes `run()`, writes envelope to stdout `[read] agent/tools/tool_worker.py:27`. |
| `scripts/run-tests.ps1` | `scripts/run-tests.ps1` | Host Script | `.\scripts\run-tests.ps1` | Builds test image, runs 157 harness unit tests and 11 isolated eval tests in Docker `[read] scripts/run-tests.ps1:1-25`. |
| `scripts/run-tests.sh` | `scripts/run-tests.sh` | Host Script | `./scripts/run-tests.sh` | Shell script equivalent for POSIX hosts `[read] scripts/run-tests.sh:1-19`. |
| `scripts/live-check.ps1` | `scripts/live-check.ps1` | Host Script | `.\scripts\live-check.ps1` | Diagnostic health check verifying image freshness, plan, models, errors, framing, and environment. |


---

## 3. How the Agent Starts in Practice

### Host vs. Container Topology
- **Host System:** Runs Docker daemon, hosts `.env` configuration, hosts `workspace/` bind mount, and executes administrative scripts (`run-tests.ps1`, `kill.sh`) `[read] docker-compose.yml:1-24`.
- **Container Environment:** The agent process runs entirely inside an isolated Debian Bookworm Linux container named `self-self-1` (or `self`) `[read] Dockerfile:1, docker-compose.yml:2-3`.

### Docker Compose Service Configuration (`self`)
`[read] docker-compose.yml:1-24`:
- **Image:** `self-self:latest`
- **Build Context:** Current directory (`.`) using `Dockerfile`.
- **Restart Policy:** `"no"` (does not automatically restart on failure or stop).
- **Resource Limits:**
  - `mem_limit: 4g` (4 gigabytes max RAM)
  - `cpus: 2` (maximum 2 CPU cores)
  - `pids_limit: 512` (maximum 512 processes, preventing fork bombs)
- **TTY / Interactive:** `stdin_open: true`, `tty: true` (enables interactive Textual TUI).
- **Environment:** Loaded from host `.env` file (`env_file: - .env`).
- **Volume Mounts:**
  ```yaml
  volumes:
    - type: bind
      source: ${SELF_WORKSPACE_DIR:-./workspace}
      target: /home/entity
      read_only: false
  ```
  Only the single workspace path is mounted to `/home/entity`.
- **Network:** Default bridge network (`networks: - default`). Grants standard outbound internet access without exposing host ports or requiring host networking.
- **Capabilities & Privileges:** No `privileged: true`, no added Linux capabilities (`cap_add` is omitted). Default Docker container isolation is preserved.

### Dockerfile Layers & Security Hardening
`[read] Dockerfile:1-53`:
1. `FROM python:3.12-bookworm`: Base Debian Linux environment with Python 3.12.
2. `ENV DEBIAN_FRONTEND=noninteractive PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/opt:/opt/agent`: Sets Python search paths so both `/opt` and `/opt/agent` packages resolve.
3. `RUN apt-get update && apt-get install -y --no-install-recommends ...`: Installs container inspection tools (`git`, `curl`, `jq`, `nano`, `vim`, `procps`, `net-tools`, `iputils-ping`, `dnsutils`, `sqlite3`, `python3-venv`, `python3-pip`).
4. `WORKDIR /home/entity`: Default working directory matches the workspace volume mount.
5. `COPY agent/requirements.txt /opt/agent/requirements.txt` && `RUN pip install ...`: Installs runtime dependencies (`anthropic`, `textual`, `rich`, `jsonschema`).
6. `COPY agent/ /opt/agent/`: Copies harness code into the container image.
7. `RUN mkdir -p /opt/agent/core && ln -s ...`: Creates backward-compatible symbolic links in `/opt/agent/core/`.
8. `RUN chown -R root:root /opt/agent && find /opt/agent -type d -exec chmod 0555 {} + && find /opt/agent -type f -exec chmod 0444 {} +`: Hardens the harness code. All files are set read-only (`0444`), directories read/execute only (`0555`).
9. `USER root`: Execution user inside container namespace is intentionally root.
10. `ENTRYPOINT ["python", "-m", "agent.wake"]`: Container boots directly into the wake coordinator.

---

## 4. Module Execution Location (Host vs. Container)

| Module / Path | Runs On | Rationale & Evidence |
| :--- | :--- | :--- |
| `agent.*` (all 10 packages) | **Container** | Copied into image `[read] Dockerfile:32`. Executed by container Python entry point `[read] Dockerfile:52`. |
| `scripts/run-tests.ps1`, `scripts/run-tests.sh` | **Host** | Invokes Docker CLI to build images and launch test containers `[read] scripts/run-tests.ps1:9-21`. |
| `scripts/check_architecture_docs.py` | **Host** (CI/Pre-commit) & **Container** (compatible) | Verifies static system map consistency with code `[read] scripts/run-tests.ps1:9`. |
| `scripts/build_system_map.py` | **Host** | Maintenance generator updating `system-map.json` `[read]`. |
| `eval/runner.py`, `eval/ab_plan.py` | **Host** or **Eval Container** | Excluded from `self` image `[read] .dockerignore:4`. Executed only under compose profile `eval` `[read] docker-compose.yml:25-50` or host python. |
| `kill.sh` | **Host** | Sends docker stop/kill commands from the host shell `[read] kill.sh:1-17`. |

---

## 5. Complete Environment Variable Catalog

| Variable Name | Default Value | Where Read (File:Line) | Purpose & Operational Meaning |
| :--- | :--- | :--- | :--- |
| `ANTHROPIC_API_KEY` | `""` | `[read] agent/llm/llm.py:193` | Anthropic API key used when Ollama credentials are absent. |
| `ANTHROPIC_API_KEYS` | `""` | `[read] agent/llm/llm.py:193` | Comma/JSON list of Anthropic API keys rotated on 401/403/429 errors. |
| `ANTHROPIC_BASE_URL` | `"https://api.anthropic.com"` | `[read] agent/llm/llm.py:203` | Base URL for Anthropic API calls. |
| `ANTHROPIC_MODEL` | `"gpt-oss:120b-cloud"` | `[read] agent/llm/llm.py:214` | Primary model identifier when using Anthropic provider. |
| `EVAL_WORKSPACE_DIR` | `"./workspace"` | `[read] docker-compose.yml:34` | Host directory mounted as read-only workspace in eval service. |
| `HOST_AGENT_SOURCE_HASH`| `""` | `[read] agent/ui/version_check.py:46` | Host-side SHA256 of harness sources to detect stale container builds. |
| `LLM_AVAILABLE_MODELS` | `""` | `[read] agent/llm/llm.py:216` | Comma-separated list of helper models configured under the active provider key. |
| `OLLAMA_API_KEY` | `""` | `[read] agent/llm/llm.py:192` | Primary Ollama Cloud API key. |
| `OLLAMA_API_KEYS` | `""` | `[read] agent/llm/llm.py:192` | List of Ollama Cloud API keys rotated on rate limits. |
| `OLLAMA_BASE_URL` | `"https://ollama.com"` | `[read] agent/llm/llm.py:196` | Base URL for Ollama Cloud API endpoint. |
| `OLLAMA_LOCAL_BASE_URL` | `"http://127.0.0.1:11434"` | `[read] agent/llm/providers/adapters.py:179` | Internal endpoint for container-local Ollama daemon. |
| `OLLAMA_MODEL` | `"gpt-oss:120b-cloud"` | `[read] agent/llm/llm.py:213` | Primary Ollama model identifier. |
| `PYTHONPATH` | `"/opt:/opt/agent"` | `[read] Dockerfile:6` | Python module resolution path inside container image. |
| `SELF_CONVERSATION_MAX_TOKENS` | `0` (uses model cap) | `[read] agent/session/conversation.py:33` | Output token ceiling for background conversation responses. |
| `SELF_CRITIC_MODEL` | `""` (uses base) | `[read] agent/tools/tool_registry.py:270` | Model override for `create_tool` critic reviews when helper mode is off. |
| `SELF_CRITIC_SHADOW_TESTS`| `"true"` | `[read] agent/tools/tool_registry.py:348` | If true, execute candidate unittests even if critic rejected, logging objective results. |
| `SELF_DEFAULT_OUTPUT_CEILING` | `"32768"` | `[read] agent/llm/model_registry.py:293` | Fallback max tokens when neither model registry nor per-model env specifies a ceiling. |
| `SELF_EXPECTED_CODE_HASH` | `""` | `[read] agent/ui/version_check.py:46` | Expected harness code hash for startup verification. |
| `SELF_EXPECTED_OUTPUT_TOKENS` | `"1024"` | `[read] agent/llm/llm.py:73` | Output token estimate used for pre-call daily budget reservation. |
| `SELF_HELPER_MODELS` | `"on"` | `[read] agent/runtime/loop.py:186` | Enables multi-model features (`"on"` enables probes, decisions, delegation). |
| `SELF_MAX_CONVERSATION_WORKERS` | `"2"` | `[read] agent/session/conversation.py:32` | Thread pool worker count for independent background conversations. |
| `SELF_MAX_ITERATIONS` | `"0"` (unlimited) | `[read] agent/runtime/loop.py:696` | Maximum autonomous cycles per run before stopping cleanly. |
| `SELF_MAX_OUTPUT_CHARS` | `"20000"` | `[read] agent/tools/base_tools.py:334` | Maximum character length returned by file and shell tools. |
| `SELF_MAX_PROVIDER_CALLS`| `"0"` (unlimited) | `[read] agent/infra/provider_calls.py:14` | Hard upper limit on provider calls per process (used in A/B testing). |
| `SELF_MAX_TOKENS_PER_DAY`| `"200000"` | `[read] agent/infra/hardening.py:55` | Daily token ledger allowance reset at UTC midnight. |
| `SELF_MAX_WALL_CLOCK_SECONDS` | `"0"` (unlimited) | `[read] agent/runtime/loop.py:698` | Maximum wall-clock execution seconds per run. |
| `SELF_MODEL_FAILURE_COOLDOWN_SECONDS` | `"600"` | `[read] agent/helper_models/model_decisions.py:77` | Seconds to blacklist a helper model from delegation after a failure. |
| `SELF_OUTPUT_CAP_<MODEL>` | None | `[read] agent/llm/model_registry.py:275` | Dynamic per-model output cap override (e.g. `SELF_OUTPUT_CAP_GPT_OSS_120B_CLOUD`). |
| `SELF_PROBE_COOLDOWN_SECONDS` | `"3600"` | `[read] agent/llm/model_registry.py:97` | Minimum seconds between re-probing the same helper model. |
| `SELF_PROBES_PER_MODEL_PER_SESSION` | `"2"` | `[read] agent/llm/model_registry.py:99` | Maximum probe executions allowed per helper model in a single session. |
| `SELF_REFLECTION_ENABLED`| `"1"` (true) | `[read] agent/ui/wake.py:733` | Enables background session reflections. |
| `SELF_REFLECTION_MAX_PER_SESSION` | `"3"` | `[read] agent/ui/wake.py:734` | Maximum reflection threads initiated per wake session. |
| `SELF_REFLECTION_MAX_TOKENS` | `"384"` | `[read] agent/ui/wake.py:736` | Token ceiling for background reflection prompts. |
| `SELF_REFLECTION_MIN_CYCLES` | `"3"` | `[read] agent/ui/wake.py:735` | Minimum cycle count before background reflection can trigger. |
| `SELF_REPORT_AB_FILE` | `""` | `[read] agent/reporting/report.py:212` | Path to evaluation results file included in reporting. |
| `SELF_REPORT_CALIBRATION_FILE` | `""` | `[read] agent/reporting/report.py:211` | Path to calibration score file included in reporting. |
| `SELF_TOKEN_BUDGET` | `"0"` | `[read] agent/ui/wake.py:702` | Deprecated per-run token budget (daily ledger is active). |
| `SELF_TOP_K_TOOLS` | `"5"` | `[read] agent/runtime/loop.py:692` | Number of custom tools retrieved by keyword search per cycle step. |
| `SELF_TUI_TYPING_DELAY` | `"0.01"` | `[read] agent/ui/wake.py:1631` | Character delay in seconds for terminal typewriter chat animation. |
| `SELF_VOICE_ENABLED` | `"false"` | `[read] agent/ui/voice.py:19` | Enables local speech synthesis via system speech utilities. |
| `SELF_WORKSPACE_DIR` | `"./workspace"` | `[read] docker-compose.yml:17` | Host path bind-mounted into container `/home/entity`. |
