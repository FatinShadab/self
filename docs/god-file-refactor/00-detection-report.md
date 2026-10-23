# God File Detection Report

This report identifies candidate 'god files' in the SELF agent harness (`agent/`) according to static analysis criteria defined in the refactoring specification.

## Detection Criteria
- **LOC > 400**: Total line count exceeds 400.
- **Class Methods > 15**: A single class defines more than 15 methods.
- **Function Lines > 60**: A single function or method exceeds 60 lines.
- **Responsibilities > 3**: Module exhibits more than 3 distinct architectural responsibilities.
- **Constructor Wiring > 6**: A class constructor takes more than 6 dependency collaborators.

## Summary of Findings
- **Total Files Analyzed**: 96
- **God Files Flagged**: 45
- **Compliant Files**: 51

## Ranked God Files Table

| Rank | File | LOC | Classes | Max Methods | Long Funcs (>60L) | Fan-Out | Responsibilities | Flags |
| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| 1 | `agent/ui/wake.py` | 1455 | 4 | 39 | 6 | 9 | 7 | LOC > 400 (1455)<br>Class > 15 methods: SelfApp (39)<br>Functions > 60 lines: 6 (longest: run_tui (902 lines))<br>Responsibilities > 3 (7: Command Routing & Dispatch, External / Subprocess / LLM, Formatting & Display, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction) |
| 2 | `agent/opencode/wrapper.py` | 775 | 1 | 14 | 4 | 3 | 5 | LOC > 400 (775)<br>Functions > 60 lines: 4 (longest: OpencodeDelegator.delegate_coding (356 lines))<br>Responsibilities > 3 (5: External / Subprocess / LLM, I/O & Persistence, Telemetry & Decision Tracking, UI & Interaction, Validation & Security)<br>Constructor wires > 6 collaborators (7) |
| 3 | `agent/plugins/self_dev.py` | 912 | 1 | 12 | 10 | 3 | 7 | LOC > 400 (912)<br>Functions > 60 lines: 10 (longest: PluginDevManager.propose_plugin (190 lines))<br>Responsibilities > 3 (7: Command Routing & Dispatch, External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security) |
| 4 | `agent/session/coordinator.py` | 1191 | 3 | 36 | 12 | 11 | 8 | LOC > 400 (1191)<br>Class > 15 methods: WakeCoordinator (36)<br>Functions > 60 lines: 12 (longest: WakeCoordinator._run_session (113 lines))<br>Responsibilities > 3 (8: Command Routing & Dispatch, External / Subprocess / LLM, Formatting & Display, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security) |
| 5 | `agent/runtime/loop.py` | 931 | 4 | 12 | 6 | 9 | 7 | LOC > 400 (931)<br>Functions > 60 lines: 6 (longest: AgentLoop.run (344 lines))<br>Responsibilities > 3 (7: External / Subprocess / LLM, Formatting & Display, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security) |
| 6 | `agent/helper_models/model_decisions.py` | 904 | 1 | 19 | 12 | 3 | 5 | LOC > 400 (904)<br>Class > 15 methods: ModelDecisions (19)<br>Functions > 60 lines: 12 (longest: ModelDecisions.decide_model (160 lines))<br>Responsibilities > 3 (5: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, Validation & Security) |
| 7 | `agent/tools/base_tools.py` | 944 | 2 | 37 | 2 | 5 | 7 | LOC > 400 (944)<br>Class > 15 methods: ToolRunner (37)<br>Functions > 60 lines: 2 (longest: ToolRunner.execute (167 lines))<br>Responsibilities > 3 (7: Command Routing & Dispatch, External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security)<br>Constructor wires > 6 collaborators (8) |
| 8 | `agent/learning/plan.py` | 783 | 1 | 17 | 7 | 2 | 5 | LOC > 400 (783)<br>Class > 15 methods: PlanStore (17)<br>Functions > 60 lines: 7 (longest: PlanStore.update_plan (195 lines))<br>Responsibilities > 3 (5: I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security) |
| 9 | `agent/identity/identity.py` | 811 | 1 | 39 | 2 | 4 | 6 | LOC > 400 (811)<br>Class > 15 methods: IdentityStore (39)<br>Functions > 60 lines: 2 (longest: IdentityStore.run_first_awakening (72 lines))<br>Responsibilities > 3 (6: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security) |
| 10 | `agent/tools/tool_registry.py` | 470 | 3 | 9 | 2 | 3 | 7 | LOC > 400 (470)<br>Functions > 60 lines: 2 (longest: ToolRegistry.create_tool (226 lines))<br>Responsibilities > 3 (7: External / Subprocess / LLM, Formatting & Display, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security) |
| 11 | `agent/plugins/manager.py` | 770 | 2 | 25 | 4 | 2 | 5 | LOC > 400 (770)<br>Class > 15 methods: PluginManager (25)<br>Functions > 60 lines: 4 (longest: PluginManager.load_plugin (101 lines))<br>Responsibilities > 3 (5: Command Routing & Dispatch, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, Validation & Security) |
| 12 | `agent/helper_models/model_probe.py` | 513 | 3 | 4 | 5 | 3 | 7 | LOC > 400 (513)<br>Functions > 60 lines: 5 (longest: ModelProber.research_model (127 lines))<br>Responsibilities > 3 (7: Command Routing & Dispatch, External / Subprocess / LLM, Formatting & Display, I/O & Persistence, Telemetry & Decision Tracking, UI & Interaction, Validation & Security) |
| 13 | `agent/infra/migration.py` | 468 | 0 | 0 | 2 | 0 | 4 | LOC > 400 (468)<br>Functions > 60 lines: 2 (longest: run_migration_p14 (235 lines))<br>Responsibilities > 3 (4: I/O & Persistence, Lifecycle & Orchestration, UI & Interaction, Validation & Security) |
| 14 | `agent/body/container.py` | 575 | 3 | 17 | 4 | 3 | 7 | LOC > 400 (575)<br>Class > 15 methods: ContainerBody (17)<br>Functions > 60 lines: 4 (longest: ContainerBody.capabilities (82 lines))<br>Responsibilities > 3 (7: Command Routing & Dispatch, External / Subprocess / LLM, Formatting & Display, I/O & Persistence, Telemetry & Decision Tracking, UI & Interaction, Validation & Security)<br>Constructor wires > 6 collaborators (7) |
| 15 | `agent/llm/model_registry.py` | 613 | 1 | 22 | 2 | 1 | 5 | LOC > 400 (613)<br>Class > 15 methods: ModelRegistry (22)<br>Functions > 60 lines: 2 (longest: ModelRegistry._initialize (110 lines))<br>Responsibilities > 3 (5: External / Subprocess / LLM, Formatting & Display, I/O & Persistence, Telemetry & Decision Tracking, Validation & Security) |
| 16 | `agent/plugins/cli.py` | 597 | 0 | 0 | 4 | 1 | 3 | LOC > 400 (597)<br>Functions > 60 lines: 4 (longest: cmd_validate (182 lines)) |
| 17 | `agent/body/sim.py` | 547 | 1 | 19 | 4 | 1 | 6 | LOC > 400 (547)<br>Class > 15 methods: SimBody (19)<br>Functions > 60 lines: 4 (longest: SimBody._action_step (77 lines))<br>Responsibilities > 3 (6: Command Routing & Dispatch, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security) |
| 18 | `agent/infra/cost_ledger.py` | 343 | 1 | 7 | 2 | 0 | 5 | Functions > 60 lines: 2 (longest: CostLedger.build_from_events (183 lines))<br>Responsibilities > 3 (5: I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security) |
| 19 | `agent/infra/permission_broker.py` | 421 | 6 | 10 | 2 | 0 | 4 | LOC > 400 (421)<br>Functions > 60 lines: 2 (longest: PermissionBroker.authorize (107 lines))<br>Responsibilities > 3 (4: I/O & Persistence, Telemetry & Decision Tracking, UI & Interaction, Validation & Security)<br>Constructor wires > 6 collaborators (10) |
| 20 | `agent/session/reflection.py` | 352 | 1 | 13 | 2 | 4 | 5 | Functions > 60 lines: 2 (longest: ReflectionManager._reflect (141 lines))<br>Responsibilities > 3 (5: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, Validation & Security) |
| 21 | `agent/plugins/manifest.py` | 393 | 6 | 1 | 1 | 0 | 4 | Functions > 60 lines: 1 (longest: parse_manifest (182 lines))<br>Responsibilities > 3 (4: External / Subprocess / LLM, I/O & Persistence, Telemetry & Decision Tracking, Validation & Security) |
| 22 | `agent/llm/llm.py` | 374 | 4 | 6 | 2 | 1 | 6 | Functions > 60 lines: 2 (longest: LLMClient.call (109 lines))<br>Responsibilities > 3 (6: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security) |
| 23 | `agent/learning/learning.py` | 427 | 1 | 17 | 0 | 2 | 6 | LOC > 400 (427)<br>Class > 15 methods: LearningStore (17)<br>Responsibilities > 3 (6: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security) |
| 24 | `agent/reporting/run_analysis.py` | 322 | 1 | 0 | 2 | 0 | 4 | Functions > 60 lines: 2 (longest: analyze_run (200 lines))<br>Responsibilities > 3 (4: I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction) |
| 25 | `agent/opencode/status.py` | 476 | 1 | 13 | 3 | 1 | 3 | LOC > 400 (476)<br>Functions > 60 lines: 3 (longest: OpencodeStatusTracker.usability (63 lines)) |
| 26 | `agent/reporting/report.py` | 239 | 0 | 0 | 2 | 2 | 4 | Functions > 60 lines: 2 (longest: create_report (99 lines))<br>Responsibilities > 3 (4: I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, Validation & Security) |
| 27 | `agent/opencode/sandbox.py` | 396 | 1 | 6 | 0 | 0 | 4 | Responsibilities > 3 (4: Command Routing & Dispatch, External / Subprocess / LLM, I/O & Persistence, Validation & Security) |
| 28 | `agent/identity/migration.py` | 141 | 0 | 0 | 1 | 1 | 5 | Functions > 60 lines: 1 (longest: migrate_persisted_identity (115 lines))<br>Responsibilities > 3 (5: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, UI & Interaction, Validation & Security) |
| 29 | `agent/helper_models/model_outcomes.py` | 213 | 2 | 3 | 1 | 1 | 4 | Functions > 60 lines: 1 (longest: print_outcome_summary (65 lines))<br>Responsibilities > 3 (4: I/O & Persistence, Telemetry & Decision Tracking, UI & Interaction, Validation & Security) |
| 30 | `agent/session/session.py` | 214 | 2 | 10 | 0 | 2 | 6 | Responsibilities > 3 (6: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security) |
| 31 | `agent/llm/providers/registry.py` | 189 | 1 | 10 | 0 | 1 | 6 | Responsibilities > 3 (6: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security) |
| 32 | `agent/plugins/examples/pet_companion/plugin.py` | 238 | 0 | 0 | 0 | 0 | 4 | Responsibilities > 3 (4: I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction) |
| 33 | `agent/llm/brain_router.py` | 196 | 1 | 13 | 0 | 1 | 5 | Responsibilities > 3 (5: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, Validation & Security) |
| 34 | `agent/opencode/tools.py` | 187 | 0 | 0 | 0 | 1 | 5 | Responsibilities > 3 (5: External / Subprocess / LLM, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security) |
| 35 | `agent/session/conversation.py` | 118 | 1 | 5 | 0 | 4 | 5 | Responsibilities > 3 (5: External / Subprocess / LLM, I/O & Persistence, Telemetry & Decision Tracking, UI & Interaction, Validation & Security) |
| 36 | `agent/infra/stop_watcher.py` | 175 | 1 | 14 | 0 | 0 | 4 | Responsibilities > 3 (4: I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, Validation & Security) |
| 37 | `agent/ui/phase8_verify.py` | 108 | 1 | 1 | 0 | 4 | 4 | Responsibilities > 3 (4: I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction) |
| 38 | `agent/infra/hardening.py` | 133 | 3 | 6 | 0 | 0 | 5 | Responsibilities > 3 (5: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, Validation & Security) |
| 39 | `agent/learning/memory_migration.py` | 108 | 0 | 0 | 1 | 0 | 2 | Functions > 60 lines: 1 (longest: migrate_memory_store (97 lines)) |
| 40 | `agent/prompts/system.py` | 86 | 0 | 0 | 0 | 0 | 6 | Responsibilities > 3 (6: Command Routing & Dispatch, External / Subprocess / LLM, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security) |
| 41 | `agent/infra/process_runner.py` | 102 | 0 | 0 | 1 | 0 | 2 | Functions > 60 lines: 1 (longest: run_process (90 lines)) |
| 42 | `agent/ui/disk_tool_demo.py` | 42 | 0 | 0 | 0 | 5 | 4 | Responsibilities > 3 (4: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking) |
| 43 | `agent/infra/event_log.py` | 107 | 2 | 5 | 0 | 0 | 4 | Responsibilities > 3 (4: I/O & Persistence, Telemetry & Decision Tracking, UI & Interaction, Validation & Security) |
| 44 | `agent/infra/__init__.py` | 59 | 0 | 0 | 0 | 0 | 4 | Responsibilities > 3 (4: External / Subprocess / LLM, Lifecycle & Orchestration, Telemetry & Decision Tracking, Validation & Security) |
| 45 | `agent/prompts/critics.py` | 34 | 0 | 0 | 0 | 0 | 4 | Responsibilities > 3 (4: Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security) |

## Detailed Analysis per Flagged God File

### 1. `agent/ui/wake.py` (LOC: 1455, Severity Score: 5040)

- **Responsibilities (7)**: Command Routing & Dispatch, External / Subprocess / LLM, Formatting & Display, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction
- **Agent Package Fan-Out (9)**: `body, helper_models, identity, infra, learning, llm, runtime, session, tools`
- **Max Methods in Single Class**: 39
- **Max Constructor Collaborators**: 1

**Triggered Flags**:
- LOC > 400 (1455)
- Class > 15 methods: SelfApp (39)
- Functions > 60 lines: 6 (longest: run_tui (902 lines))
- Responsibilities > 3 (7: Command Routing & Dispatch, External / Subprocess / LLM, Formatting & Display, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction)

**Functions / Methods > 60 lines**:
- `run_tui`: 902 lines
- `SelfApp.on_input_submitted`: 218 lines
- `on_input_submitted`: 218 lines
- `build_archive_views`: 193 lines
- `SelfApp._refresh`: 82 lines
- `_refresh`: 82 lines

### 2. `agent/opencode/wrapper.py` (LOC: 775, Severity Score: 2912)

- **Responsibilities (5)**: External / Subprocess / LLM, I/O & Persistence, Telemetry & Decision Tracking, UI & Interaction, Validation & Security
- **Agent Package Fan-Out (3)**: `helper_models, infra, prompts`
- **Max Methods in Single Class**: 14
- **Max Constructor Collaborators**: 7

**Triggered Flags**:
- LOC > 400 (775)
- Functions > 60 lines: 4 (longest: OpencodeDelegator.delegate_coding (356 lines))
- Responsibilities > 3 (5: External / Subprocess / LLM, I/O & Persistence, Telemetry & Decision Tracking, UI & Interaction, Validation & Security)
- Constructor wires > 6 collaborators (7)

**Functions / Methods > 60 lines**:
- `OpencodeDelegator.delegate_coding`: 356 lines
- `delegate_coding`: 356 lines
- `OpencodeDelegator.apply_delegation`: 162 lines
- `apply_delegation`: 162 lines

### 3. `agent/plugins/self_dev.py` (LOC: 912, Severity Score: 2881)

- **Responsibilities (7)**: Command Routing & Dispatch, External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security
- **Agent Package Fan-Out (3)**: `infra, prompts, tools`
- **Max Methods in Single Class**: 12
- **Max Constructor Collaborators**: 4

**Triggered Flags**:
- LOC > 400 (912)
- Functions > 60 lines: 10 (longest: PluginDevManager.propose_plugin (190 lines))
- Responsibilities > 3 (7: Command Routing & Dispatch, External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security)

**Functions / Methods > 60 lines**:
- `PluginDevManager.propose_plugin`: 190 lines
- `PluginDevManager.validate_plugin`: 190 lines
- `propose_plugin`: 190 lines
- `validate_plugin`: 190 lines
- `PluginDevManager.request_plugin_review`: 119 lines
- `request_plugin_review`: 119 lines
- `PluginDevManager.test_plugin`: 96 lines
- `test_plugin`: 96 lines
- `PluginDevManager.promote_draft_by_human`: 76 lines
- `promote_draft_by_human`: 76 lines

### 4. `agent/session/coordinator.py` (LOC: 1191, Severity Score: 2850)

- **Responsibilities (8)**: Command Routing & Dispatch, External / Subprocess / LLM, Formatting & Display, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security
- **Agent Package Fan-Out (11)**: `body, helper_models, identity, infra, learning, llm, opencode, plugins, prompts, runtime, tools`
- **Max Methods in Single Class**: 36
- **Max Constructor Collaborators**: 1

**Triggered Flags**:
- LOC > 400 (1191)
- Class > 15 methods: WakeCoordinator (36)
- Functions > 60 lines: 12 (longest: WakeCoordinator._run_session (113 lines))
- Responsibilities > 3 (8: Command Routing & Dispatch, External / Subprocess / LLM, Formatting & Display, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security)

**Functions / Methods > 60 lines**:
- `WakeCoordinator._run_session`: 113 lines
- `_run_session`: 113 lines
- `WakeCoordinator.boot`: 98 lines
- `boot`: 98 lines
- `WakeCoordinator._reflection`: 96 lines
- `_reflection`: 96 lines
- `WakeCoordinator.__init__`: 95 lines
- `__init__`: 95 lines
- `WakeCoordinator.handle_plugins_command`: 78 lines
- `handle_plugins_command`: 78 lines
- `WakeCoordinator._update_telemetry`: 61 lines
- `_update_telemetry`: 61 lines

### 5. `agent/runtime/loop.py` (LOC: 931, Severity Score: 2758)

- **Responsibilities (7)**: External / Subprocess / LLM, Formatting & Display, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security
- **Agent Package Fan-Out (9)**: `body, helper_models, identity, infra, learning, llm, plugins, prompts, tools`
- **Max Methods in Single Class**: 12
- **Max Constructor Collaborators**: 4

**Triggered Flags**:
- LOC > 400 (931)
- Functions > 60 lines: 6 (longest: AgentLoop.run (344 lines))
- Responsibilities > 3 (7: External / Subprocess / LLM, Formatting & Display, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security)

**Functions / Methods > 60 lines**:
- `AgentLoop.run`: 344 lines
- `run`: 344 lines
- `AgentLoop.__init__`: 86 lines
- `__init__`: 86 lines
- `AgentLoop._check_active_plugin_projects`: 63 lines
- `_check_active_plugin_projects`: 63 lines

### 6. `agent/helper_models/model_decisions.py` (LOC: 904, Severity Score: 2421)

- **Responsibilities (5)**: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, Validation & Security
- **Agent Package Fan-Out (3)**: `infra, llm, prompts`
- **Max Methods in Single Class**: 19
- **Max Constructor Collaborators**: 5

**Triggered Flags**:
- LOC > 400 (904)
- Class > 15 methods: ModelDecisions (19)
- Functions > 60 lines: 12 (longest: ModelDecisions.decide_model (160 lines))
- Responsibilities > 3 (5: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, Validation & Security)

**Functions / Methods > 60 lines**:
- `ModelDecisions.decide_model`: 160 lines
- `decide_model`: 160 lines
- `ModelDecisions.ask_model`: 153 lines
- `ask_model`: 153 lines
- `ModelDecisions.build_route_stats`: 78 lines
- `build_route_stats`: 78 lines
- `ModelDecisions._summary_entry`: 74 lines
- `_summary_entry`: 74 lines
- `ModelDecisions._migrate_legacy_records`: 67 lines
- `_migrate_legacy_records`: 67 lines
- `ModelDecisions.record_build_outcome`: 61 lines
- `record_build_outcome`: 61 lines

### 7. `agent/tools/base_tools.py` (LOC: 944, Severity Score: 2307)

- **Responsibilities (7)**: Command Routing & Dispatch, External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security
- **Agent Package Fan-Out (5)**: `body, helper_models, infra, llm, opencode`
- **Max Methods in Single Class**: 37
- **Max Constructor Collaborators**: 8

**Triggered Flags**:
- LOC > 400 (944)
- Class > 15 methods: ToolRunner (37)
- Functions > 60 lines: 2 (longest: ToolRunner.execute (167 lines))
- Responsibilities > 3 (7: Command Routing & Dispatch, External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security)
- Constructor wires > 6 collaborators (8)

**Functions / Methods > 60 lines**:
- `ToolRunner.execute`: 167 lines
- `execute`: 167 lines

### 8. `agent/learning/plan.py` (LOC: 783, Severity Score: 2057)

- **Responsibilities (5)**: I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security
- **Agent Package Fan-Out (2)**: `infra, prompts`
- **Max Methods in Single Class**: 17
- **Max Constructor Collaborators**: 3

**Triggered Flags**:
- LOC > 400 (783)
- Class > 15 methods: PlanStore (17)
- Functions > 60 lines: 7 (longest: PlanStore.update_plan (195 lines))
- Responsibilities > 3 (5: I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security)

**Functions / Methods > 60 lines**:
- `PlanStore.update_plan`: 195 lines
- `update_plan`: 195 lines
- `PlanStore.record_human_input_decision`: 86 lines
- `record_human_input_decision`: 86 lines
- `consolidate_plan_items`: 80 lines
- `PlanStore.hygiene`: 70 lines
- `hygiene`: 70 lines

### 9. `agent/identity/identity.py` (LOC: 811, Severity Score: 1679)

- **Responsibilities (6)**: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security
- **Agent Package Fan-Out (4)**: `body, infra, opencode, prompts`
- **Max Methods in Single Class**: 39
- **Max Constructor Collaborators**: 2

**Triggered Flags**:
- LOC > 400 (811)
- Class > 15 methods: IdentityStore (39)
- Functions > 60 lines: 2 (longest: IdentityStore.run_first_awakening (72 lines))
- Responsibilities > 3 (6: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security)

**Functions / Methods > 60 lines**:
- `IdentityStore.run_first_awakening`: 72 lines
- `run_first_awakening`: 72 lines

### 10. `agent/tools/tool_registry.py` (LOC: 470, Severity Score: 1619)

- **Responsibilities (7)**: External / Subprocess / LLM, Formatting & Display, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security
- **Agent Package Fan-Out (3)**: `infra, llm, prompts`
- **Max Methods in Single Class**: 9
- **Max Constructor Collaborators**: 4

**Triggered Flags**:
- LOC > 400 (470)
- Functions > 60 lines: 2 (longest: ToolRegistry.create_tool (226 lines))
- Responsibilities > 3 (7: External / Subprocess / LLM, Formatting & Display, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security)

**Functions / Methods > 60 lines**:
- `ToolRegistry.create_tool`: 226 lines
- `create_tool`: 226 lines

### 11. `agent/plugins/manager.py` (LOC: 770, Severity Score: 1596)

- **Responsibilities (5)**: Command Routing & Dispatch, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, Validation & Security
- **Agent Package Fan-Out (2)**: `infra, tools`
- **Max Methods in Single Class**: 25
- **Max Constructor Collaborators**: 5

**Triggered Flags**:
- LOC > 400 (770)
- Class > 15 methods: PluginManager (25)
- Functions > 60 lines: 4 (longest: PluginManager.load_plugin (101 lines))
- Responsibilities > 3 (5: Command Routing & Dispatch, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, Validation & Security)

**Functions / Methods > 60 lines**:
- `PluginManager.load_plugin`: 101 lines
- `load_plugin`: 101 lines
- `PluginManager.sync_at_cycle_boundary`: 68 lines
- `sync_at_cycle_boundary`: 68 lines

### 12. `agent/helper_models/model_probe.py` (LOC: 513, Severity Score: 1518)

- **Responsibilities (7)**: Command Routing & Dispatch, External / Subprocess / LLM, Formatting & Display, I/O & Persistence, Telemetry & Decision Tracking, UI & Interaction, Validation & Security
- **Agent Package Fan-Out (3)**: `infra, llm, prompts`
- **Max Methods in Single Class**: 4
- **Max Constructor Collaborators**: 5

**Triggered Flags**:
- LOC > 400 (513)
- Functions > 60 lines: 5 (longest: ModelProber.research_model (127 lines))
- Responsibilities > 3 (7: Command Routing & Dispatch, External / Subprocess / LLM, Formatting & Display, I/O & Persistence, Telemetry & Decision Tracking, UI & Interaction, Validation & Security)

**Functions / Methods > 60 lines**:
- `ModelProber.research_model`: 127 lines
- `research_model`: 127 lines
- `ModelProber.probe_model`: 105 lines
- `probe_model`: 105 lines
- `extract_model_facts`: 96 lines

### 13. `agent/infra/migration.py` (LOC: 468, Severity Score: 1420)

- **Responsibilities (4)**: I/O & Persistence, Lifecycle & Orchestration, UI & Interaction, Validation & Security
- **Agent Package Fan-Out (0)**: `None`
- **Max Methods in Single Class**: 0
- **Max Constructor Collaborators**: 0

**Triggered Flags**:
- LOC > 400 (468)
- Functions > 60 lines: 2 (longest: run_migration_p14 (235 lines))
- Responsibilities > 3 (4: I/O & Persistence, Lifecycle & Orchestration, UI & Interaction, Validation & Security)

**Functions / Methods > 60 lines**:
- `run_migration_p14`: 235 lines
- `deterministic_summary`: 171 lines

### 14. `agent/body/container.py` (LOC: 575, Severity Score: 1400)

- **Responsibilities (7)**: Command Routing & Dispatch, External / Subprocess / LLM, Formatting & Display, I/O & Persistence, Telemetry & Decision Tracking, UI & Interaction, Validation & Security
- **Agent Package Fan-Out (3)**: `infra, opencode, prompts`
- **Max Methods in Single Class**: 17
- **Max Constructor Collaborators**: 7

**Triggered Flags**:
- LOC > 400 (575)
- Class > 15 methods: ContainerBody (17)
- Functions > 60 lines: 4 (longest: ContainerBody.capabilities (82 lines))
- Responsibilities > 3 (7: Command Routing & Dispatch, External / Subprocess / LLM, Formatting & Display, I/O & Persistence, Telemetry & Decision Tracking, UI & Interaction, Validation & Security)
- Constructor wires > 6 collaborators (7)

**Functions / Methods > 60 lines**:
- `ContainerBody.capabilities`: 82 lines
- `capabilities`: 82 lines
- `ContainerMetrics.snapshot`: 68 lines
- `snapshot`: 68 lines

### 15. `agent/llm/model_registry.py` (LOC: 613, Severity Score: 1398)

- **Responsibilities (5)**: External / Subprocess / LLM, Formatting & Display, I/O & Persistence, Telemetry & Decision Tracking, Validation & Security
- **Agent Package Fan-Out (1)**: `infra`
- **Max Methods in Single Class**: 22
- **Max Constructor Collaborators**: 4

**Triggered Flags**:
- LOC > 400 (613)
- Class > 15 methods: ModelRegistry (22)
- Functions > 60 lines: 2 (longest: ModelRegistry._initialize (110 lines))
- Responsibilities > 3 (5: External / Subprocess / LLM, Formatting & Display, I/O & Persistence, Telemetry & Decision Tracking, Validation & Security)

**Functions / Methods > 60 lines**:
- `ModelRegistry._initialize`: 110 lines
- `_initialize`: 110 lines

### 16. `agent/plugins/cli.py` (LOC: 597, Severity Score: 1252)

- **Responsibilities (3)**: Command Routing & Dispatch, I/O & Persistence, Validation & Security
- **Agent Package Fan-Out (1)**: `infra`
- **Max Methods in Single Class**: 0
- **Max Constructor Collaborators**: 0

**Triggered Flags**:
- LOC > 400 (597)
- Functions > 60 lines: 4 (longest: cmd_validate (182 lines))

**Functions / Methods > 60 lines**:
- `cmd_validate`: 182 lines
- `cmd_list`: 92 lines
- `cmd_check`: 84 lines
- `cmd_new`: 72 lines

### 17. `agent/body/sim.py` (LOC: 547, Severity Score: 1234)

- **Responsibilities (6)**: Command Routing & Dispatch, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security
- **Agent Package Fan-Out (1)**: `infra`
- **Max Methods in Single Class**: 19
- **Max Constructor Collaborators**: 5

**Triggered Flags**:
- LOC > 400 (547)
- Class > 15 methods: SimBody (19)
- Functions > 60 lines: 4 (longest: SimBody._action_step (77 lines))
- Responsibilities > 3 (6: Command Routing & Dispatch, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security)

**Functions / Methods > 60 lines**:
- `SimBody._action_step`: 77 lines
- `_action_step`: 77 lines
- `SimBody.act`: 71 lines
- `act`: 71 lines

### 18. `agent/infra/cost_ledger.py` (LOC: 343, Severity Score: 1135)

- **Responsibilities (5)**: I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security
- **Agent Package Fan-Out (0)**: `None`
- **Max Methods in Single Class**: 7
- **Max Constructor Collaborators**: 1

**Triggered Flags**:
- Functions > 60 lines: 2 (longest: CostLedger.build_from_events (183 lines))
- Responsibilities > 3 (5: I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security)

**Functions / Methods > 60 lines**:
- `CostLedger.build_from_events`: 183 lines
- `build_from_events`: 183 lines

### 19. `agent/infra/permission_broker.py` (LOC: 421, Severity Score: 1089)

- **Responsibilities (4)**: I/O & Persistence, Telemetry & Decision Tracking, UI & Interaction, Validation & Security
- **Agent Package Fan-Out (0)**: `None`
- **Max Methods in Single Class**: 10
- **Max Constructor Collaborators**: 10

**Triggered Flags**:
- LOC > 400 (421)
- Functions > 60 lines: 2 (longest: PermissionBroker.authorize (107 lines))
- Responsibilities > 3 (4: I/O & Persistence, Telemetry & Decision Tracking, UI & Interaction, Validation & Security)
- Constructor wires > 6 collaborators (10)

**Functions / Methods > 60 lines**:
- `PermissionBroker.authorize`: 107 lines
- `authorize`: 107 lines

### 20. `agent/session/reflection.py` (LOC: 352, Severity Score: 1036)

- **Responsibilities (5)**: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, Validation & Security
- **Agent Package Fan-Out (4)**: `helper_models, infra, llm, prompts`
- **Max Methods in Single Class**: 13
- **Max Constructor Collaborators**: 4

**Triggered Flags**:
- Functions > 60 lines: 2 (longest: ReflectionManager._reflect (141 lines))
- Responsibilities > 3 (5: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, Validation & Security)

**Functions / Methods > 60 lines**:
- `ReflectionManager._reflect`: 141 lines
- `_reflect`: 141 lines

### 21. `agent/plugins/manifest.py` (LOC: 393, Severity Score: 917)

- **Responsibilities (4)**: External / Subprocess / LLM, I/O & Persistence, Telemetry & Decision Tracking, Validation & Security
- **Agent Package Fan-Out (0)**: `None`
- **Max Methods in Single Class**: 1
- **Max Constructor Collaborators**: 0

**Triggered Flags**:
- Functions > 60 lines: 1 (longest: parse_manifest (182 lines))
- Responsibilities > 3 (4: External / Subprocess / LLM, I/O & Persistence, Telemetry & Decision Tracking, Validation & Security)

**Functions / Methods > 60 lines**:
- `parse_manifest`: 182 lines

### 22. `agent/llm/llm.py` (LOC: 374, Severity Score: 905)

- **Responsibilities (6)**: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security
- **Agent Package Fan-Out (1)**: `infra`
- **Max Methods in Single Class**: 6
- **Max Constructor Collaborators**: 4

**Triggered Flags**:
- Functions > 60 lines: 2 (longest: LLMClient.call (109 lines))
- Responsibilities > 3 (6: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security)

**Functions / Methods > 60 lines**:
- `LLMClient.call`: 109 lines
- `call`: 109 lines

### 23. `agent/learning/learning.py` (LOC: 427, Severity Score: 897)

- **Responsibilities (6)**: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security
- **Agent Package Fan-Out (2)**: `infra, prompts`
- **Max Methods in Single Class**: 17
- **Max Constructor Collaborators**: 4

**Triggered Flags**:
- LOC > 400 (427)
- Class > 15 methods: LearningStore (17)
- Responsibilities > 3 (6: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security)

### 24. `agent/reporting/run_analysis.py` (LOC: 322, Severity Score: 884)

- **Responsibilities (4)**: I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction
- **Agent Package Fan-Out (0)**: `None`
- **Max Methods in Single Class**: 0
- **Max Constructor Collaborators**: 0

**Triggered Flags**:
- Functions > 60 lines: 2 (longest: analyze_run (200 lines))
- Responsibilities > 3 (4: I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction)

**Functions / Methods > 60 lines**:
- `analyze_run`: 200 lines
- `print_report`: 61 lines

### 25. `agent/opencode/status.py` (LOC: 476, Severity Score: 765)

- **Responsibilities (3)**: External / Subprocess / LLM, I/O & Persistence, Validation & Security
- **Agent Package Fan-Out (1)**: `infra`
- **Max Methods in Single Class**: 13
- **Max Constructor Collaborators**: 4

**Triggered Flags**:
- LOC > 400 (476)
- Functions > 60 lines: 3 (longest: OpencodeStatusTracker.usability (63 lines))

**Functions / Methods > 60 lines**:
- `OpencodeStatusTracker.usability`: 63 lines
- `usability`: 63 lines
- `classify_failure`: 61 lines

### 26. `agent/reporting/report.py` (LOC: 239, Severity Score: 635)

- **Responsibilities (4)**: I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, Validation & Security
- **Agent Package Fan-Out (2)**: `infra, learning`
- **Max Methods in Single Class**: 0
- **Max Constructor Collaborators**: 0

**Triggered Flags**:
- Functions > 60 lines: 2 (longest: create_report (99 lines))
- Responsibilities > 3 (4: I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, Validation & Security)

**Functions / Methods > 60 lines**:
- `create_report`: 99 lines
- `helper_model_section`: 64 lines

### 27. `agent/opencode/sandbox.py` (LOC: 396, Severity Score: 576)

- **Responsibilities (4)**: Command Routing & Dispatch, External / Subprocess / LLM, I/O & Persistence, Validation & Security
- **Agent Package Fan-Out (0)**: `None`
- **Max Methods in Single Class**: 6
- **Max Constructor Collaborators**: 3

**Triggered Flags**:
- Responsibilities > 3 (4: Command Routing & Dispatch, External / Subprocess / LLM, I/O & Persistence, Validation & Security)

### 28. `agent/identity/migration.py` (LOC: 141, Severity Score: 566)

- **Responsibilities (5)**: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, UI & Interaction, Validation & Security
- **Agent Package Fan-Out (1)**: `prompts`
- **Max Methods in Single Class**: 0
- **Max Constructor Collaborators**: 0

**Triggered Flags**:
- Functions > 60 lines: 1 (longest: migrate_persisted_identity (115 lines))
- Responsibilities > 3 (5: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, UI & Interaction, Validation & Security)

**Functions / Methods > 60 lines**:
- `migrate_persisted_identity`: 115 lines

### 29. `agent/helper_models/model_outcomes.py` (LOC: 213, Severity Score: 518)

- **Responsibilities (4)**: I/O & Persistence, Telemetry & Decision Tracking, UI & Interaction, Validation & Security
- **Agent Package Fan-Out (1)**: `infra`
- **Max Methods in Single Class**: 3
- **Max Constructor Collaborators**: 2

**Triggered Flags**:
- Functions > 60 lines: 1 (longest: print_outcome_summary (65 lines))
- Responsibilities > 3 (4: I/O & Persistence, Telemetry & Decision Tracking, UI & Interaction, Validation & Security)

**Functions / Methods > 60 lines**:
- `print_outcome_summary`: 65 lines

### 30. `agent/session/session.py` (LOC: 214, Severity Score: 464)

- **Responsibilities (6)**: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security
- **Agent Package Fan-Out (2)**: `infra, learning`
- **Max Methods in Single Class**: 10
- **Max Constructor Collaborators**: 3

**Triggered Flags**:
- Responsibilities > 3 (6: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security)

### 31. `agent/llm/providers/registry.py` (LOC: 189, Severity Score: 424)

- **Responsibilities (6)**: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security
- **Agent Package Fan-Out (1)**: `infra`
- **Max Methods in Single Class**: 10
- **Max Constructor Collaborators**: 2

**Triggered Flags**:
- Responsibilities > 3 (6: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security)

### 32. `agent/plugins/examples/pet_companion/plugin.py` (LOC: 238, Severity Score: 418)

- **Responsibilities (4)**: I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction
- **Agent Package Fan-Out (0)**: `None`
- **Max Methods in Single Class**: 0
- **Max Constructor Collaborators**: 0

**Triggered Flags**:
- Responsibilities > 3 (4: I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction)

### 33. `agent/llm/brain_router.py` (LOC: 196, Severity Score: 411)

- **Responsibilities (5)**: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, Validation & Security
- **Agent Package Fan-Out (1)**: `infra`
- **Max Methods in Single Class**: 13
- **Max Constructor Collaborators**: 3

**Triggered Flags**:
- Responsibilities > 3 (5: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, Validation & Security)

### 34. `agent/opencode/tools.py` (LOC: 187, Severity Score: 402)

- **Responsibilities (5)**: External / Subprocess / LLM, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security
- **Agent Package Fan-Out (1)**: `infra`
- **Max Methods in Single Class**: 0
- **Max Constructor Collaborators**: 0

**Triggered Flags**:
- Responsibilities > 3 (5: External / Subprocess / LLM, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security)

### 35. `agent/session/conversation.py` (LOC: 118, Severity Score: 378)

- **Responsibilities (5)**: External / Subprocess / LLM, I/O & Persistence, Telemetry & Decision Tracking, UI & Interaction, Validation & Security
- **Agent Package Fan-Out (4)**: `body, infra, llm, prompts`
- **Max Methods in Single Class**: 5
- **Max Constructor Collaborators**: 4

**Triggered Flags**:
- Responsibilities > 3 (5: External / Subprocess / LLM, I/O & Persistence, Telemetry & Decision Tracking, UI & Interaction, Validation & Security)

### 36. `agent/infra/stop_watcher.py` (LOC: 175, Severity Score: 355)

- **Responsibilities (4)**: I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, Validation & Security
- **Agent Package Fan-Out (0)**: `None`
- **Max Methods in Single Class**: 14
- **Max Constructor Collaborators**: 6

**Triggered Flags**:
- Responsibilities > 3 (4: I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, Validation & Security)

### 37. `agent/ui/phase8_verify.py` (LOC: 108, Severity Score: 348)

- **Responsibilities (4)**: I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction
- **Agent Package Fan-Out (4)**: `identity, infra, llm, tools`
- **Max Methods in Single Class**: 1
- **Max Constructor Collaborators**: 0

**Triggered Flags**:
- Responsibilities > 3 (4: I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction)

### 38. `agent/infra/hardening.py` (LOC: 133, Severity Score: 333)

- **Responsibilities (5)**: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, Validation & Security
- **Agent Package Fan-Out (0)**: `None`
- **Max Methods in Single Class**: 6
- **Max Constructor Collaborators**: 3

**Triggered Flags**:
- Responsibilities > 3 (5: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, Validation & Security)

### 39. `agent/learning/memory_migration.py` (LOC: 108, Severity Score: 322)

- **Responsibilities (2)**: I/O & Persistence, Validation & Security
- **Agent Package Fan-Out (0)**: `None`
- **Max Methods in Single Class**: 0
- **Max Constructor Collaborators**: 0

**Triggered Flags**:
- Functions > 60 lines: 1 (longest: migrate_memory_store (97 lines))

**Functions / Methods > 60 lines**:
- `migrate_memory_store`: 97 lines

### 40. `agent/prompts/system.py` (LOC: 86, Severity Score: 306)

- **Responsibilities (6)**: Command Routing & Dispatch, External / Subprocess / LLM, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security
- **Agent Package Fan-Out (0)**: `None`
- **Max Methods in Single Class**: 0
- **Max Constructor Collaborators**: 0

**Triggered Flags**:
- Responsibilities > 3 (6: Command Routing & Dispatch, External / Subprocess / LLM, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security)

### 41. `agent/infra/process_runner.py` (LOC: 102, Severity Score: 302)

- **Responsibilities (2)**: External / Subprocess / LLM, I/O & Persistence
- **Agent Package Fan-Out (0)**: `None`
- **Max Methods in Single Class**: 0
- **Max Constructor Collaborators**: 0

**Triggered Flags**:
- Functions > 60 lines: 1 (longest: run_process (90 lines))

**Functions / Methods > 60 lines**:
- `run_process`: 90 lines

### 42. `agent/ui/disk_tool_demo.py` (LOC: 42, Severity Score: 297)

- **Responsibilities (4)**: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking
- **Agent Package Fan-Out (5)**: `infra, llm, prompts, runtime, tools`
- **Max Methods in Single Class**: 0
- **Max Constructor Collaborators**: 0

**Triggered Flags**:
- Responsibilities > 3 (4: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking)

### 43. `agent/infra/event_log.py` (LOC: 107, Severity Score: 287)

- **Responsibilities (4)**: I/O & Persistence, Telemetry & Decision Tracking, UI & Interaction, Validation & Security
- **Agent Package Fan-Out (0)**: `None`
- **Max Methods in Single Class**: 5
- **Max Constructor Collaborators**: 1

**Triggered Flags**:
- Responsibilities > 3 (4: I/O & Persistence, Telemetry & Decision Tracking, UI & Interaction, Validation & Security)

### 44. `agent/infra/__init__.py` (LOC: 59, Severity Score: 239)

- **Responsibilities (4)**: External / Subprocess / LLM, Lifecycle & Orchestration, Telemetry & Decision Tracking, Validation & Security
- **Agent Package Fan-Out (0)**: `None`
- **Max Methods in Single Class**: 0
- **Max Constructor Collaborators**: 0

**Triggered Flags**:
- Responsibilities > 3 (4: External / Subprocess / LLM, Lifecycle & Orchestration, Telemetry & Decision Tracking, Validation & Security)

### 45. `agent/prompts/critics.py` (LOC: 34, Severity Score: 214)

- **Responsibilities (4)**: Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security
- **Agent Package Fan-Out (0)**: `None`
- **Max Methods in Single Class**: 0
- **Max Constructor Collaborators**: 0

**Triggered Flags**:
- Responsibilities > 3 (4: Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security)

## Clean / Compliant Files

| File | LOC | Classes | Functions | Responsibilities |
| :--- | :---: | :---: | :---: | :---: |
| `agent/plugins/examples/pet_companion/habitat.py` | 256 | 3 | 0 | 2 |
| `agent/llm/providers/adapters.py` | 192 | 9 | 2 | 3 |
| `agent/infra/audit_trail.py` | 167 | 1 | 2 | 3 |
| `agent/identity/name_context.py` | 154 | 0 | 2 | 2 |
| `agent/prompts/cycle.py` | 133 | 0 | 7 | 3 |
| `agent/infra/untrusted.py` | 117 | 0 | 6 | 2 |
| `agent/ui/voice.py` | 125 | 1 | 0 | 2 |
| `agent/learning/exploration_coverage.py` | 97 | 1 | 4 | 3 |
| `agent/session/version_check.py` | 64 | 0 | 2 | 3 |
| `agent/tools/benchmark.py` | 38 | 0 | 1 | 3 |
| `agent/plugins/examples/pet_companion/phrase_engine.py` | 104 | 0 | 2 | 1 |
| `agent/body/base.py` | 78 | 3 | 0 | 2 |
| `agent/infra/egress_allowlist.py` | 48 | 1 | 0 | 3 |
| `agent/run.py` | 50 | 0 | 1 | 2 |
| `agent/infra/file_lock.py` | 40 | 0 | 1 | 3 |
| `agent/ui/version_check.py` | 27 | 0 | 1 | 2 |
| `agent/prompts/container_body.py` | 55 | 0 | 0 | 2 |
| `agent/prompts/reflection.py` | 53 | 0 | 2 | 2 |
| `agent/plugins/__init__.py` | 36 | 0 | 0 | 1 |
| `agent/infra/provider_calls.py` | 32 | 0 | 1 | 1 |
| `agent/opencode/__init__.py` | 32 | 0 | 0 | 1 |
| `agent/llm/providers/base.py` | 49 | 5 | 0 | 0 |
| `agent/tools/tool_worker.py` | 27 | 0 | 1 | 1 |
| `agent/prompts/conversation.py` | 26 | 0 | 2 | 1 |
| `agent/loop.py` | 7 | 0 | 0 | 1 |
| `agent/prompts/identity.py` | 42 | 0 | 1 | 0 |
| `agent/plugins/hello/plugin.py` | 21 | 0 | 3 | 1 |
| `agent/prompts/model_selection.py` | 21 | 0 | 0 | 1 |
| `agent/prompts/safety.py` | 21 | 0 | 0 | 1 |
| `agent/session/__init__.py` | 18 | 0 | 0 | 1 |
| `agent/body/__init__.py` | 15 | 0 | 0 | 1 |
| `agent/prompts/delegation.py` | 30 | 0 | 1 | 0 |
| `agent/prompts/tasks.py` | 27 | 0 | 0 | 0 |
| `agent/disk_tool_demo.py` | 7 | 0 | 0 | 0 |
| `agent/model_outcomes.py` | 7 | 0 | 0 | 0 |
| `agent/report.py` | 7 | 0 | 0 | 0 |
| `agent/wake.py` | 7 | 0 | 0 | 0 |
| `agent/event_log.py` | 4 | 0 | 0 | 0 |
| `agent/prompts/probes.py` | 11 | 0 | 0 | 0 |
| `agent/llm/providers/__init__.py` | 6 | 0 | 0 | 0 |
| `agent/plugins/__main__.py` | 6 | 0 | 0 | 0 |
| `agent/prompts/__init__.py` | 2 | 0 | 0 | 0 |
| `agent/__init__.py` | 1 | 0 | 0 | 0 |
| `agent/helper_models/__init__.py` | 1 | 0 | 0 | 0 |
| `agent/identity/__init__.py` | 1 | 0 | 0 | 0 |
| `agent/learning/__init__.py` | 1 | 0 | 0 | 0 |
| `agent/llm/__init__.py` | 1 | 0 | 0 | 0 |
| `agent/reporting/__init__.py` | 1 | 0 | 0 | 0 |
| `agent/runtime/__init__.py` | 1 | 0 | 0 | 0 |
| `agent/tools/__init__.py` | 1 | 0 | 0 | 0 |
| `agent/ui/__init__.py` | 1 | 0 | 0 | 0 |
