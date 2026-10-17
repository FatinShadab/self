# Document 10: Coupling, Host/Body Assumptions & Plugin Seams

**Git Commit:** `14ffa606468920a97c672b39fbf3a43fccc52bdf`  
**Date:** 2026-10-17  
**Status:** Read-only architecture documentation

---

## 1. Concrete Linux Container Assumptions

The codebase currently couples the agent's cognition directly to the assumption that its "body" is a root process inside a Docker Linux container. Transforming SELF into a reusable core with plug-and-unplug bodies (e.g. an antivirus engine, a robotic/IoT microcontroller body) requires isolating these assumptions:

### A. Narrative & Prompt Strings
*(Note: As of Prompt 10, all container narrative strings listed below have been extracted from core code into `agent.body.container.ContainerBody` and parameterized via `body.describe()`; core wording remains body-agnostic while preserving exact golden prompts for `ContainerBody`.)*
- `[read] agent/runtime/loop.py:35`: `SYSTEM_PROMPT = f"""You are SELF, an autonomous AI agent whose body is this Linux container."""`
- `[read] agent/runtime/loop.py:61`: `"You are root inside the container. The Docker container boundary is the security boundary."`
- `[read] agent/runtime/loop.py:63`: `"`/opt/agent/core/` is protected image-owned harness code. Read it when useful, but do not modify it with normal tools."`
- `[read] agent/runtime/loop.py:64`: `"`/home/entity/self/` is the editable extension layer..."`
- `[read] agent/session/conversation.py:77-78`: `"You are an autonomous AI agent with your own goals, whose operating environment is this Linux container."`
- `[read] agent/identity/identity.py:270`: `"I am an LLM-driven Python harness running in a Linux container."`
- `[read] agent/identity/identity.py:382`: `"Orientation: I am an LLM-driven agent running inside this Linux container."`
- `[read] agent/learning/learning.py:256`: `"I am SELF, a root process inside a Docker Linux container. I explore the container, retain verified discoveries..."`
- `[read] agent/tools/base_tools.py:76`: `run_shell` description: `"Run an unrestricted Bash command inside the container as root, with a timeout and bounded returned output."`
- `[read] agent/tools/base_tools.py:88`: `read_file` description: `"Read a UTF-8 text file from the container, returning bounded content."`
- `[read] agent/tools/base_tools.py:100`: `write_file` description: `"Write or append UTF-8 text inside the container except the image-owned /opt/agent harness..."`
- `[read] agent/tools/base_tools.py:113`: `list_dir` description: `"List a directory inside the container."`
- `[read] agent/tools/base_tools.py:249`: `probe_local_ollama` description: `"Check whether a local Ollama service and already-installed model are available within this container."`

### B. Linux Kernel & Virtual Filesystem Paths (`/proc`, `/sys`)
- `[read] agent/learning/learning.py:86`: Reads `Path("/proc/meminfo")` to extract total system RAM during map initialization.
- `[read] agent/llm/brain_router.py:185`: Reads `Path("/proc/meminfo")` to calculate available RAM before probing local Ollama.
- `[read] agent/ui/wake.py:651`: Reads `Path("/proc/net/dev")` to calculate network interface byte counters for the cardiac monitor.
- `[read] agent/ui/wake.py:962`: Reads `Path("/proc/uptime")` to detect whether container uptime reset between wake sessions.
- `[read] agent/ui/wake.py:585`: Reads `Path("/sys/fs/cgroup") / group / filename` for cgroup metrics.
- `[read] agent/ui/wake.py:600`: Reads `Path("/sys/fs/cgroup/cpu.stat")` for CPU throttle and usage stats.
- `[read] agent/ui/wake.py:615`: Reads `Path("/sys/fs/cgroup/cpu.max")` for container CPU quota and period.
- `[read] agent/ui/wake.py:636`: Reads `Path("/sys/fs/cgroup/memory.current")` for live cgroup RAM usage.
- `[read] agent/ui/wake.py:639`: Reads `Path("/sys/fs/cgroup/memory.max")` for container RAM ceiling.

### C. Hardcoded Filesystem Paths (`/home/entity` & `/opt/agent`)
- **Default Workspace Path `/home/entity`:**
  - `[read] agent/runtime/loop.py:98`: `AgentConfig.workspace: Path = Path("/home/entity")`
  - `[read] agent/runtime/loop.py:725`: `workspace = Path("/home/entity")` in `loop.py:main()`
  - `[read] agent/ui/wake.py:2435`: `parser.add_argument("--workspace", default="/home/entity")`
  - `[read] agent/identity/identity.py:40`: `workspace: str | Path = "/home/entity"`
  - `[read] agent/helper_models/model_outcomes.py:46, 114`: Default workspace `"/home/entity"`
  - `[read] agent/helper_models/model_decisions.py:719`: Default workspace `"/home/entity"`
  - `[read] agent/ui/phase8_verify.py:96`: Default workspace `"/home/entity"`
  - `[read] agent/reporting/report.py:210`: Default workspace `"/home/entity"`
  - `[read] Dockerfile:25`: `WORKDIR /home/entity`
  - `[read] docker-compose.yml:18, 35`: `target: /home/entity`
- **Protected Harness Path `/opt/agent` and `/opt/agent/core`:**
  - `[read] Dockerfile:6, 29, 32, 37-46`: Builds harness at `/opt/agent`, symlinks `/opt/agent/core/`.
  - `[read] agent/identity/identity.py:43`: `core_root: str | Path = "/opt/agent/core"`
  - `[read] agent/identity/identity.py:254`: Checks `candidate.parent == self.core_root and str(self.core_root) == "/opt/agent/core"`
  - `[read] agent/tools/base_tools.py:521`: `_is_core_path()` checks if path is relative to `self.core_root` or `self.agent_root` (`/opt/agent`)
  - `[read] agent/tools/base_tools.py:540-543`: Hardcoded error message citing `/opt/agent/core`
  - `[read] agent/ui/version_check.py:32`: `agent_root = Path("/opt/agent")`

### D. Shell & Package Tool Assumptions
- `[read] agent/tools/base_tools.py:461`: `run_shell` hardcodes execution via `run_process(["/bin/bash", "-lc", cmd], ...)`. Assumes a POSIX Bash shell exists at `/bin/bash`.
- `[read] agent/ui/wake.py:1385-1394`: Hardcodes startup priority: `"Immediately inventory the installed Python packages in this container. Use the relevant shell/tool action now..."`
- `[read] agent/ui/wake.py:986`: Spot checks verify `platform.system() == "Linux"`.
- `[read] workspace/tools/`: The agent's generated tools heavily assume Debian systemd architecture:
  - `parse_systemd_service`, `parse_systemd_timer`, `systemctl_list_timers`, `timer_service_info`, `timer_service_map`, `parse_proc_net_tcp`, `parse_passwd`.

---

## 2. Package Dependency Matrix & Import Graph

The repository has 10 packages organized in a strict 6-layer acyclic downward hierarchy enforced by unit test `agent/tests/infra/test_import_layers.py` `[read] agent/tests/infra/test_import_layers.py:11-22`:

```
Layer 0: agent.infra
   ▲
Layer 1: agent.llm
   ▲
Layer 2: agent.tools, agent.learning, agent.helper_models, agent.identity
   ▲
Layer 3: agent.runtime
   ▲
Layer 4: agent.session, agent.reporting
   ▲
Layer 5: agent.ui
```

### Import Dependency Matrix

| Importer Package (Row) \ Imported Package (Col) | `infra` | `llm` | `tools` | `learning` | `helper_models` | `identity` | `runtime` | `session` | `reporting` | `ui` |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **`agent.infra`** (Layer 0) | — |  |  |  |  |  |  |  |  |  |
| **`agent.llm`** (Layer 1) | **YES** | — |  |  |  |  |  |  |  |  |
| **`agent.tools`** (Layer 2) | **YES** | **YES** | — |  |  |  |  |  |  |  |
| **`agent.learning`** (Layer 2) | **YES** |  |  | — |  |  |  |  |  |  |
| **`agent.helper_models`** (Layer 2)| **YES** | **YES** |  |  | — |  |  |  |  |  |
| **`agent.identity`** (Layer 2) | **YES** |  |  |  |  | — |  |  |  |  |
| **`agent.runtime`** (Layer 3) | **YES** | **YES** | **YES** | **YES** | **YES** | **YES** | — |  |  |  |
| **`agent.session`** (Layer 4) | **YES** | **YES** |  | **YES** | **YES** |  |  | — |  |  |
| **`agent.reporting`** (Layer 4) | **YES** |  |  | **YES** |  |  |  |  | — |  |
| **`agent.ui`** (Layer 5) | **YES** | **YES** | **YES** | **YES** | **YES** | **YES** | **YES** | **YES** |  | — |

- **Circular Dependencies:** **ZERO**. There are no circular imports between any packages `[ran] test_import_layers.py passed`.
- **Key Architectural Fact:** `agent.runtime` is Layer 3 and imports Layer 2 packages (`tools`, `learning`, `identity`, `helper_models`). `agent.tools` does NOT import `runtime`.

---

## 3. Candidate Seams for Body & Plugin Interfaces

To transform SELF into a core engine with swappable bodies (Linux container, Windows host, Antivirus engine, Robotic/IoT controller) and modular plugins, the following seams must be introduced:

```mermaid
graph TD
    subgraph Core["Reusable Agent Core"]
        LOOP[AgentLoop & Cycle Engine]
        PLAN[PlanStore & Human Arbitration]
        ID[IdentityStore & Voice]
        MEM[LearningStore & Memory]
        LLM[BudgetedLLM & ModelRegistry]
    end

    subgraph BodyInterface["Body Interface Seam"]
        SENSE["Sense: Environment, Telemetry, Clock"]
        ACT["Act: Execute, Read, Write, Transmit"]
        PERM["Permissions: Boundary Checks, Redaction"]
    end

    subgraph Plugins["Specialization Plugins"]
        AV["Antivirus Body: Scanner, Quarantiner, YARA"]
        ROBOT["IoT Body: Sensors, Actuators, Serial"]
        CONTAINER["Container Body: Linux Shell, Docker cgroups"]
    end

    LOOP --> BodyInterface
    BodyInterface --> AV
    BodyInterface --> ROBOT
    BodyInterface --> CONTAINER
```

### Seam 1: The "Body" Interface (`Sense`, `Act`, `Permissions`)
- **Status:** **IMPLEMENTED (Prompt 10)** via `agent.body.base.Body` and `agent.body.container.ContainerBody`.
- **Target Interface:**
  - `Sense`: telemetry, system statistics (RAM, CPU, disk, interfaces via `ContainerMetrics`), orientation changes, uptime.
  - `Act`: `execute_action(action, params)` (`run_shell`, `read_file`, `write_file`, `list_dir`, `http_get`, `probe_local_ollama`).
  - `Permissions`: path validation (`is_safe_path`, `_is_core_path`), boundary checks.
- **Implementation:**
  - `agent/body/base.py`: Declares `Body` ABC with `describe()`, `capabilities()`, `sense()`, `act()`, `health()`, and `emergency_stop()`.
  - `agent/body/container.py`: Implements `ContainerBody(Body)` wrapping shell, filesystem, HTTP, Ollama, and cgroup/proc telemetry.
  - `agent/tools/base_tools.py`: `ToolRunner` delegates OS and filesystem operations to `self.body`.
  - `agent/session/coordinator.py`: Headless coordinator uses `self.body` for metrics, orientation changes, and initial startup tasks.

### Seam 2: Tool Registry & Tool Offerings
- **Current Tight Coupling:** `TOOL_DEFINITIONS` is a hardcoded static list in `base_tools.py:23-270`. `AgentLoop` filters it via `HELPER_TOOL_NAMES`.
- **Target Interface:** `ToolProvider` protocol allowing plugins to register tool suites (e.g. `antivirus_scan`, `quarantine_file`, `motor_step`, `read_lidar`).
- **Code to Change:**
  - `agent/tools/base_tools.py`: Change `TOOL_DEFINITIONS` from static list to dynamic registry with `register_tool_spec()`.
  - `agent/runtime/loop.py:539-542`: Accept tool providers rather than importing `TOOL_DEFINITIONS` directly.
- **Difficulty:** **LOW**. The custom tool pipeline (`ToolRegistry`) already supports dynamic tool addition; extending this to base tools is straightforward.

### Seam 3: Prompt Assembly & Standing Goal
- **Status:** **IMPLEMENTED (Prompt 10)** via `assemble_system_prompt(body)` and `assemble_conversation_system_prompt(body)`.
- **Implementation:**
  - `agent/runtime/loop.py`: Decomposed `SYSTEM_PROMPT` into core rules (`CORE_SYSTEM_PROMPT_HEAD`, `CORE_CAPABILITY_RULE`, `CORE_IDENTITY_RULES`) and dynamically appends `body.describe().embodiment`. `AgentLoop` accepts `body` parameter.
  - `agent/session/conversation.py`: Parameterized conversation system prompt using `body.describe().conversation_environment`.
  - `agent/learning/learning.py`: Parameterized self notes preamble using `body.describe().notes_preamble`.

### Seam 4: Plan Seeding & Curriculum
- **Status:** **IMPLEMENTED (Prompt 10)** via `body.initial_orientation_task()`.
- **Implementation:**
  - `agent/session/coordinator.py`: Startup priority delegates to `self.body.initial_orientation_task()` instead of hardcoded container package inventory.
  - `agent/learning/plan.py`: Plan seeding uses body-provided initial orientation.

### Seam 5: Identity & Persona Framing
- **Status:** **IMPLEMENTED (Prompt 10)** via `IdentityStore.default_identity(body)`.
- **Implementation:**
  - `agent/identity/identity.py`: Default interests and self-inquiry questions are supplied by `body.describe().default_interests` and `body.describe().identity_harness_context`. Core autonomy, voice, and traits remain preserved.

### Seam 6: State Folders & Persistence Partitioning
- **Current Tight Coupling:** `workspace/state/` contains an unpartitioned mix of cognitive files (`plan.json`, `identity.json`, `models.json`) and container-specific artifacts (`etc_recursive.json`, `service_dependency_map.json`).
- **Target Interface:** Clean partitioning between core cognitive state (`core_state/`) and body/plugin state (`plugins/<plugin_name>/state/`).
- **Code to Change:**
  - `agent/learning/learning.py`: Move ad-hoc map files into plugin namespaces.
- **Difficulty:** **MEDIUM**. Requires file path migrations and updating paths in tools.

---

## 4. Ranked Difficulty Summary of Seams

| Rank | Seam | Difficulty | Primary Challenge & Rationale |
| :---: | :--- | :---: | :--- |
| **1** | **Body Interface (`Sense` / `Act` / `Permissions`)** | **HIGH** | `base_tools.py`, `process_runner.py`, and `wake.py` contain deep, pervasive assumptions about Linux bash, root execution, cgroups, `/proc`, and container filesystems. Abstracting these into an interface without breaking existing tool behavior or security requires substantial refactoring. |
| **2** | **Prompt Assembly & System Prompt** | **MEDIUM** | Prompts are fragile. Splitting `SYSTEM_PROMPT` into core autonomy vs. body embodiment requires careful phrasing so the agent retains its first-person non-subservient voice and strict safety rules regardless of body. |
| **3** | **State Partitioning & File Organization** | **MEDIUM** | Existing workspace state files have interdependencies across `learning.py`, `plan.py`, and `report.py`. Moving files into namespaced subdirectories requires careful path migrations. |
| **4** | **Tool Registry & Dynamic Offerings** | **LOW** | `ToolRegistry` already dynamically loads and tests tools; wrapping base tools into provider interfaces is a natural extension of existing design. |
| **5** | **Plan Seeding & Startup Tasks** | **LOW** | Removing the hardcoded Python package inventory startup priority and parameterizing `seed_task` is localized to `wake.py:1385` and `loop.py:394`. |
| **6** | **Identity Framing & Default Interests** | **LOW** | Parameterizing `interests` in `default_identity()` is localized to `agent/identity/identity.py:86`. |

---

## 5. What Would Break If a Plugin Were Unplugged Mid-Run

If a body or specialization plugin (e.g. an antivirus scanner or IoT motor plugin) is unplugged while the agent is running:

1. **Tool Invocation Failures (`ValueError`):**
   - The LLM's conversation history retains memory of the plugin's tools.
   - If the LLM generates a `tool_use` block for a vanished tool, `ToolRunner.execute()` raises `ValueError("Tool not offered in this step")` `[read] agent/runtime/loop.py:593`.
   - *Impact:* The cycle records a tool error. The agent receives the error observation in the next turn and must adapt.
2. **Stalled Plan Goals:**
   - Active goals in `state/plan.json` may depend on plugin capabilities (e.g., `goal-4: "Scan filesystem for malware signatures"`).
   - *Impact:* Without the plugin tool, the goal cannot be achieved. The agent's plan review requirement `[read] agent/runtime/loop.py:488` will eventually mark the goal `"blocked"` or `"dropped"` citing the missing tool observation.
3. **Keyword Retrieval Misses:**
   - `ToolRegistry.retrieve()` will no longer return the plugin's tools. Keyword queries will fall back to base tools.
4. **State & Map Staleness:**
   - Map entries recorded by the plugin in `state/map.json` remain on disk. The agent may cite stale facts until spot-checks detect they no longer exist.
5. **Clean Recovery:**
   - The core runtime will **NOT** crash. The inner tool round catches tool errors as standard observations `[read] agent/tools/base_tools.py:431-432`, appends them to message history, and allows the agent to reason about the failure and update its plan.
