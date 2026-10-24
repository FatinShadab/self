# Self-Developing Plugins & Cost-Aware Capability Synthesis

This document specifies the agent's autonomous plugin self-development architecture, the capability ladder, the measured cost ledger model, the development lifecycle, and human governance controls.

---

## 1. Principle: A Plugin is NOT a Tool

The agent strictly distinguishes between lightweight ad-hoc tools and specialization plugins:

| Dimension | Custom Tool (`create_tool`) | Specialization Plugin (`propose_plugin`) |
| :--- | :--- | :--- |
| **Effort & Time** | Minutes, 1 to 2 cycles | Multi-cycle project (many cycles, wall-clock time) |
| **Token Investment** | Low (~1,500 - 3,500 tokens) | High (~10,000 - 50,000+ tokens) |
| **Review Rigor** | Single LLM critic check + unittests | Stricter 5-factor plugin critic + diff + permission summary |
| **Lifecycle & Enablement**| Active immediately on registration | Scaffolded in `plugin_dev/`; requires human promotion and enablement |
| **Permissions** | Container workspace privileges | Explicit declared permissions (L0-L3) & risk classes; L1-L3 denied by default |
| **Maintenance** | Single function (`tool.py`) | Embodiment, sensors, actions, state directory, hooks, ongoing maintenance |

Cost information serves as a decision aid for the agent's planning, not as an artificial limit: the daily token ledger (`DailyTokenLedger`) remains the only enforced hard token budget.

---

## 2. The Capability Ladder

When SELF encounters a problem, capability gap, or new goal, it evaluates the **Capability Ladder** from the lowest rung upward. The agent must prefer the lowest rung that works and explain why lower rungs were insufficient:

```
[Rung E] Request Capability Expansion (Human Host Action: .env, mounts, credentials)
   ▲
[Rung D] Develop a Specialization Plugin (Multi-cycle project, human approval required)
   ▲
[Rung C] Create a Tool (Cheap, single-cycle Python function via create_tool)
   ▲
[Rung B] Query a Helper Model (Delegate sub-task via ask_model)
   ▲
[Rung A] Use Existing Tools (Built-ins, active plugins, retrieved workspace tools)
```

1. **Rung A — Use Existing Tools:**  
   Query verified built-in tools (`read_file`, `write_file`, `run_shell`, etc.) and active plugins.
2. **Rung B — Call a Helper Model:**  
   For bounded plain-text reasoning, translation, or data summarization, delegate via `ask_model`.
3. **Rung C — Create a Tool (`create_tool`):**  
   For ad-hoc computations, formatting, or parsing, generate a tested Python function under `workspace/tools/<name>/`.
4. **Rung D — Develop a Specialization Plugin (`propose_plugin`):**  
   When a capability requires durable embodiment, isolated private state, new sensors, multiple coordinated actions, or specialized slash commands. Requires a formal proposal, stop-loss reviews, human promotion, and enablement.
5. **Rung E — Request Capability Expansion (`request_capability`):**  
   When the task requires new host mounts, network ports, API credentials, or external accounts. SELF writes `state/capability_requests.md` and pauses for host operator action.

---

## 3. Measured Cost Ledger Model

Estimates are **measured, not guessed**. The system builds `state/cost_ledger.jsonl` from event telemetry:

- **Tracked metrics:** Tokens spent, LLM calls made, wall-clock time elapsed, and autonomous cycles consumed per `create_tool` attempt and per plugin project.
- **Tool baselines as the absolute floor:** The tool baseline numbers (median and 90th percentile p90) represent the floor for plugin estimates. A plugin is composed of multiple tool-sized components, integration glue, simulation tests, heavier critic reviews, human review time, and ongoing maintenance.
- **Empty ledger bootstrap baseline:** On a brand new workspace where `state/cost_ledger.jsonl` contains 0 entries, `cost_ledger.get_summary()` provides a documented fallback baseline floor (tool tokens: median 1,500, p90 3,500; 2 LLM calls; 15s wall time; 1 cycle). The agent cites this fallback bootstrap floor in its derivation (e.g. `Cold-start bootstrap baseline citing default floor of 1500 tokens median for 3 cycles = 4500 tokens`). An estimate of 0 tokens is rejected, as building a plugin inherently incurs token expenditure.
- **Query tool:** The agent calls `read_cost_ledger` to inspect current baselines and active project totals before formulating estimates.

---

## 4. Self-Development Workflow

### Step 1: Query Ledger Baselines
Before proposing a plugin, the agent queries `read_cost_ledger` to obtain measured median and p90 figures for tokens, cycles, and wall time.

### Step 2: Propose Plugin (`propose_plugin`)
The agent invokes `propose_plugin` with 10 mandatory fields:
1. `name`: Lowercase snake_case identifier.
2. `need`: Specific capability gap justifying a plugin over a tool.
3. `evidence`: Durable facts from environment observation or prior cycles.
4. `alternatives_considered`: Why lower rungs (tools, helper models) were insufficient.
5. `estimate`: Explicit ranges for `tokens`, `cycles`, `wall_time`, `human_review_minutes`, and a `derivation` citing ledger baselines.
6. `expected_benefit`: Anticipated durable value to autonomous exploration.
7. `actions_needed_with_risk_levels`: Declared sensors (L0) and actions (L0-L3).
8. `maintenance_burden`: Storage, state footprint, and unplug impact.
9. `stop_loss`: Review triggers at 25%, 50%, and 100% of the estimate.
10. `rollback`: Procedure if abandoned or rejected.

The proposal is appended to `state/plugin_proposals.jsonl`, its milestones are seeded into `state/plan.json`, and human operators are notified via `/proposals`.

### Step 3: Scaffold Draft in Isolation (`scaffold_plugin`)
The agent scaffolds the plugin skeleton into `workspace/plugin_dev/<name>/` from the template.  
**Critical boundary:** The plugin loader (`PluginManager.discover()`) **never** scans or loads from `plugin_dev/`. A draft cannot be activated while in development.

### Step 4: Implement Handlers
The agent writes handlers in `workspace/plugin_dev/<name>/plugin.py`, configuring `plugin.json` with appropriate risk classes (`reads`, `writes`, `executes`, `network`) and required permission levels (`L0` to `L3`).

### Step 5: Static Validation (`validate_plugin`)
Before testing or review, the agent runs `validate_plugin(name)`:
- Validates manifest schema and version ranges (`core_api`).
- Checks tool namespacing (must not collide with core tools).
- Verifies permission declarations (sensors must be L0 and reversible).
- Scans code for secret reads (forbids referencing credential markers like `API_KEY` in environment variables).
- Checks for undeclared network or subprocess calls.
- Scans all files for prompt injection patterns or delimiter escape attempts.

#### Limits of Validation
`validate_plugin` is strictly an advisory static checker, not a hard security boundary:
- **Bypassable static checks:** Static AST parsing and text regexes are easily bypassed by dynamic Python patterns, such as `__import__("socket")`, dynamic attribute access (`getattr(os, "system")`), or runtime string construction for paths and secret files (`"".join(["/", "etc", "/", "shadow"])`).
- **Real controls:** Hard security depends on human review, SHA-256 hash pinning in `/config/plugins.json`, the runtime `PermissionBroker`, and the Docker container boundary. The default profile runs shell commands as container root.

### Step 6: Isolated Testing (`test_plugin`)
Runs plugin tests in `workspace/plugin_dev/<name>/tests/` in an isolated subprocess with secrets stripped and network access blocked:
- `_child_env` strips all credential and token environment variables matching secret markers.
- All outbound network calls are routed to dead loopback endpoints (`http://127.0.0.1:0`) via proxy environment variables.
- An in-process PEP 578 audit hook monitors socket creation and sensitive file access during the test run.
- **Audit Hook vs. Container Boundary:** The in-process audit hook is an advisory speed bump, not a security sandbox. Subprocesses (`os.system("curl ...")`), dynamic C calls (`ctypes`), symlinks, or obfuscated paths pass in-process hooks. The default Docker profile has a writable workspace mount, read-only config mount, and container-root shell execution. The optional hardened profile drops privileges and capabilities.
- Tests run against deterministic simulation models (`SimBody`) and scenarios—never against real external services or host resources.
- If a stop-loss review is pending, `test_plugin` is blocked until an explicit decision is recorded in the plan.

### Step 7: Heavier Critic Review (`request_plugin_review`)
Invokes a specialized plugin critic prompt (`PLUGIN_CRITIC_PROMPT`) evaluating 5 strict dimensions:
1. Accuracy of risk levels against declared actions.
2. Defensive untrusted-data handling.
3. Strict state isolation (writing only to `state/`).
4. Graceful unplug and deactivation behavior.
5. Objective test quality and failure-mode coverage.

Produces a review packet (`review_packet.json`) with a unified diff and permission summary for the operator.

---

## 5. Stop-Loss Reviews

At **25%**, **50%**, and **100%** of the estimated tokens or cycles (whichever occurs first), the harness triggers a mandatory stop-loss review:

- **Benchmark ceiling:** The 100% mark is benchmarked against the upper bound (`max` of `tokens` and `cycles`) declared in the proposal estimate.
- **Cycle Prompt Alert:** The cycle prompt flags the triggered threshold with measured spend vs. original estimate.
- **Enforcement on Silence:** Continuing is allowed; silence is not. If a stop-loss review is pending and unacknowledged, the cycle prompt re-prompts on every cycle AND:
  - All plugin development tools (`validate_plugin`, `test_plugin`, `request_plugin_review`) are **blocked** from executing.
  - File modifications (`write_file`) and shell executions (`run_shell`) targeting `workspace/plugin_dev/<name>` are **blocked** from modifying the draft.
  - Development remains blocked until the agent itself decides and records an explicit decision in its plan update (`update_plan` action=`decide_plugin_review`):
    - `continue`: Justify why continuing remains worthwhile despite spend.
    - `reduce_scope`: Prune non-essential actions to stay within bounds.
    - `abandon`: Terminate development and roll back draft files.
- **Attribution:** Project spend accumulates from granular plugin events and cycles where the active milestone is a plugin project goal; general exploration cycles attribute spend to general discovery.
- **Budget Reservation:** Critic LLM reviews dispatched via `request_plugin_review` use `BudgetedLLM` and strictly respect daily token ledger reservations (`DailyTokenLedger`).
- The harness logs `plugin_project_review` events for transparent auditability.

---

## 6. Normal Exploration Nudge

Developing a plugin takes many cycles, but autonomous environmental exploration must not halt:
- While a plugin project is active, the cycle prompt displays the project's active milestone and spend.
- The prompt includes a defined nudge: at least ~1 in every 3 cycles should be allocated to other plan goals (environment mapping, model evaluation, general exploration) unless the agent writes an explicit reason in its plan update explaining why consecutive plugin cycles are required.

---

## 7. Human Governance & Boundaries

1. **Viewing Proposals:** Human operators inspect pending and active proposals via the `/proposals` slash command. Core reserved slash commands (`RESERVED_SLASH_COMMANDS`) include `/proposals` and `/proposal` and cannot be shadowed by plugins.
2. **Operator Comments:** Operators can comment via `/proposals comment <name> <comment>`. Comments are delivered to the agent's inbox as advice to weigh; the agent decides how to adapt its plan.
3. **Promotion (`/plugins promote <name>`):**
   - Human-only slash command.
   - Validates the draft; if valid, copies it from `workspace/plugin_dev/<name>` to `workspace/plugins/<name>` as **DISABLED**.
   - Displays the unified diff and permission summary to the operator.
   - The agent cannot promote drafts.
4. **Enablement (`/plugins enable <name>`):**
   - Promotion is a convenience copy; the true security gate is **human enablement with content hash pinning**.
   - Even if the agent manually writes or copies files directly to `workspace/plugins/<name>` using base file or shell tools, the plugin loader leaves it in a strictly **DISABLED** state at every cycle boundary until the human explicitly reviews permissions and issues `/plugins enable <name>`.
   - Enabling computes and pins the SHA-256 content hash in `/config/plugins.json` and outputs declared tool permissions to the operator.
   - The agent cannot enable plugins.
5. **Permission Elevation:**
   - The agent cannot grant plugin permissions to itself. Plugin actions above `L0` remain denied until the human operator sets a plugin ceiling in `/config/plugins.json` or an equivalent grant in `/config/permissions.json`.
6. **Hard External Controls:**
   - Stop controls (`/stop`, `workspace/STOP`, SIGINT/SIGTERM) are hard external boundaries that cannot be overridden or deferred by the agent.
