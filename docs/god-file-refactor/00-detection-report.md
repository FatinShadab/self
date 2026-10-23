# God File Detection Report

This report identifies candidate 'god files' in the SELF agent harness (`agent/`) according to static analysis criteria defined in the refactoring specification.

## Detection Criteria
- **LOC > 400**: Total line count exceeds 400.
- **Class Methods > 15**: A single class defines more than 15 methods.
- **Function Lines > 60**: A single function or method exceeds 60 lines.
- **Responsibilities > 3**: Module exhibits more than 3 distinct architectural responsibilities.
- **Constructor Wiring > 6**: A class constructor takes more than 6 dependency collaborators.

## Summary of Findings
- **Total Files Analyzed**: 163
- **God Files Flagged**: 74
- **Compliant Files**: 89

## Ranked God Files Table

| Rank | File | LOC | Classes | Max Methods | Long Funcs (>60L) | Fan-Out | Responsibilities | Flags |
| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| 1 | `agent/opencode/wrapper.py` | 775 | 1 | 14 | 4 | 3 | 5 | LOC > 400 (775)<br>Functions > 60 lines: 4 (longest: OpencodeDelegator.delegate_coding (356 lines))<br>Responsibilities > 3 (5: External / Subprocess / LLM, I/O & Persistence, Telemetry & Decision Tracking, UI & Interaction, Validation & Security)<br>Constructor wires > 6 collaborators (7) |
| 2 | `agent/plugins/self_dev.py` | 912 | 1 | 12 | 10 | 3 | 7 | LOC > 400 (912)<br>Functions > 60 lines: 10 (longest: PluginDevManager.propose_plugin (190 lines))<br>Responsibilities > 3 (7: Command Routing & Dispatch, External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security) |
| 3 | `agent/helper_models/model_decisions.py` | 904 | 1 | 19 | 12 | 3 | 5 | LOC > 400 (904)<br>Class > 15 methods: ModelDecisions (19)<br>Functions > 60 lines: 12 (longest: ModelDecisions.decide_model (160 lines))<br>Responsibilities > 3 (5: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, Validation & Security) |
| 4 | `agent/learning/plan.py` | 783 | 1 | 17 | 7 | 2 | 5 | LOC > 400 (783)<br>Class > 15 methods: PlanStore (17)<br>Functions > 60 lines: 7 (longest: PlanStore.update_plan (195 lines))<br>Responsibilities > 3 (5: I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security) |
| 5 | `agent/identity/identity.py` | 811 | 1 | 39 | 2 | 4 | 6 | LOC > 400 (811)<br>Class > 15 methods: IdentityStore (39)<br>Functions > 60 lines: 2 (longest: IdentityStore.run_first_awakening (72 lines))<br>Responsibilities > 3 (6: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security) |
| 6 | `agent/tools/tool_registry.py` | 470 | 3 | 9 | 2 | 3 | 7 | LOC > 400 (470)<br>Functions > 60 lines: 2 (longest: ToolRegistry.create_tool (226 lines))<br>Responsibilities > 3 (7: External / Subprocess / LLM, Formatting & Display, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security) |
| 7 | `agent/plugins/manager.py` | 770 | 2 | 25 | 4 | 2 | 5 | LOC > 400 (770)<br>Class > 15 methods: PluginManager (25)<br>Functions > 60 lines: 4 (longest: PluginManager.load_plugin (101 lines))<br>Responsibilities > 3 (5: Command Routing & Dispatch, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, Validation & Security) |
| 8 | `agent/helper_models/model_probe.py` | 513 | 3 | 4 | 5 | 3 | 7 | LOC > 400 (513)<br>Functions > 60 lines: 5 (longest: ModelProber.research_model (127 lines))<br>Responsibilities > 3 (7: Command Routing & Dispatch, External / Subprocess / LLM, Formatting & Display, I/O & Persistence, Telemetry & Decision Tracking, UI & Interaction, Validation & Security) |
| 9 | `agent/infra/migration.py` | 468 | 0 | 0 | 2 | 0 | 4 | LOC > 400 (468)<br>Functions > 60 lines: 2 (longest: run_migration_p14 (235 lines))<br>Responsibilities > 3 (4: I/O & Persistence, Lifecycle & Orchestration, UI & Interaction, Validation & Security) |
| 10 | `agent/llm/model_registry.py` | 613 | 1 | 22 | 2 | 1 | 5 | LOC > 400 (613)<br>Class > 15 methods: ModelRegistry (22)<br>Functions > 60 lines: 2 (longest: ModelRegistry._initialize (110 lines))<br>Responsibilities > 3 (5: External / Subprocess / LLM, Formatting & Display, I/O & Persistence, Telemetry & Decision Tracking, Validation & Security) |
| 11 | `agent/body/container.py` | 568 | 2 | 17 | 4 | 3 | 7 | LOC > 400 (568)<br>Class > 15 methods: ContainerBody (17)<br>Functions > 60 lines: 4 (longest: ContainerBody.capabilities (82 lines))<br>Responsibilities > 3 (7: Command Routing & Dispatch, External / Subprocess / LLM, Formatting & Display, I/O & Persistence, Telemetry & Decision Tracking, UI & Interaction, Validation & Security)<br>Constructor wires > 6 collaborators (7) |
| 12 | `agent/runtime/cycle_runner.py` | 367 | 0 | 0 | 1 | 4 | 7 | Functions > 60 lines: 1 (longest: run_agent_loop (343 lines))<br>Responsibilities > 3 (7: External / Subprocess / LLM, Formatting & Display, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security) |
| 13 | `agent/session/coordinator.py` | 391 | 1 | 36 | 2 | 5 | 7 | Class > 15 methods: WakeCoordinator (36)<br>Functions > 60 lines: 2 (longest: WakeCoordinator.__init__ (101 lines))<br>Responsibilities > 3 (7: Command Routing & Dispatch, External / Subprocess / LLM, Formatting & Display, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, Validation & Security) |
| 14 | `agent/plugins/cli.py` | 597 | 0 | 0 | 4 | 1 | 3 | LOC > 400 (597)<br>Functions > 60 lines: 4 (longest: cmd_validate (182 lines)) |
| 15 | `agent/body/sim.py` | 547 | 1 | 19 | 4 | 1 | 6 | LOC > 400 (547)<br>Class > 15 methods: SimBody (19)<br>Functions > 60 lines: 4 (longest: SimBody._action_step (77 lines))<br>Responsibilities > 3 (6: Command Routing & Dispatch, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security) |
| 16 | `agent/infra/cost_ledger.py` | 343 | 1 | 7 | 2 | 0 | 5 | Functions > 60 lines: 2 (longest: CostLedger.build_from_events (183 lines))<br>Responsibilities > 3 (5: I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security) |
| 17 | `agent/infra/permission_broker.py` | 421 | 6 | 10 | 2 | 0 | 4 | LOC > 400 (421)<br>Functions > 60 lines: 2 (longest: PermissionBroker.authorize (107 lines))<br>Responsibilities > 3 (4: I/O & Persistence, Telemetry & Decision Tracking, UI & Interaction, Validation & Security)<br>Constructor wires > 6 collaborators (10) |
| 18 | `agent/tools/base_tools.py` | 392 | 1 | 37 | 0 | 2 | 7 | Class > 15 methods: ToolRunner (37)<br>Responsibilities > 3 (7: Command Routing & Dispatch, External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security)<br>Constructor wires > 6 collaborators (8) |
| 19 | `agent/session/reflection.py` | 352 | 1 | 13 | 2 | 4 | 5 | Functions > 60 lines: 2 (longest: ReflectionManager._reflect (141 lines))<br>Responsibilities > 3 (5: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, Validation & Security) |
| 20 | `agent/plugins/manifest.py` | 393 | 6 | 1 | 1 | 0 | 4 | Functions > 60 lines: 1 (longest: parse_manifest (182 lines))<br>Responsibilities > 3 (4: External / Subprocess / LLM, I/O & Persistence, Telemetry & Decision Tracking, Validation & Security) |
| 21 | `agent/llm/llm.py` | 374 | 4 | 6 | 2 | 1 | 6 | Functions > 60 lines: 2 (longest: LLMClient.call (109 lines))<br>Responsibilities > 3 (6: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security) |
| 22 | `agent/ui/tui/app.py` | 368 | 1 | 35 | 0 | 2 | 5 | Class > 15 methods: SelfApp (35)<br>Responsibilities > 3 (5: Command Routing & Dispatch, Formatting & Display, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction) |
| 23 | `agent/learning/learning.py` | 427 | 1 | 17 | 0 | 2 | 6 | LOC > 400 (427)<br>Class > 15 methods: LearningStore (17)<br>Responsibilities > 3 (6: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security) |
| 24 | `agent/reporting/run_analysis.py` | 322 | 1 | 0 | 2 | 0 | 4 | Functions > 60 lines: 2 (longest: analyze_run (200 lines))<br>Responsibilities > 3 (4: I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction) |
| 25 | `agent/ui/formatting/archive_view.py` | 215 | 0 | 0 | 1 | 1 | 5 | Functions > 60 lines: 1 (longest: build_archive_views (198 lines))<br>Responsibilities > 3 (5: Command Routing & Dispatch, Formatting & Display, I/O & Persistence, Lifecycle & Orchestration, UI & Interaction) |
| 26 | `agent/ui/tui/commands/handlers.py` | 369 | 8 | 2 | 2 | 1 | 6 | Functions > 60 lines: 2 (longest: IdentityCommandHandler.handle (81 lines))<br>Responsibilities > 3 (6: Command Routing & Dispatch, External / Subprocess / LLM, Formatting & Display, I/O & Persistence, Lifecycle & Orchestration, UI & Interaction) |
| 27 | `agent/opencode/status.py` | 476 | 1 | 13 | 3 | 1 | 3 | LOC > 400 (476)<br>Functions > 60 lines: 3 (longest: OpencodeStatusTracker.usability (63 lines)) |
| 28 | `agent/runtime/wiring.py` | 185 | 1 | 0 | 1 | 8 | 5 | Functions > 60 lines: 1 (longest: wire_loop_collaborators (133 lines))<br>Responsibilities > 3 (5: External / Subprocess / LLM, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security) |
| 29 | `agent/session/session_runner.py` | 178 | 0 | 0 | 1 | 5 | 4 | Functions > 60 lines: 1 (longest: run_session (137 lines))<br>Responsibilities > 3 (4: External / Subprocess / LLM, Lifecycle & Orchestration, UI & Interaction, Validation & Security) |
| 30 | `agent/reporting/report.py` | 239 | 0 | 0 | 2 | 2 | 4 | Functions > 60 lines: 2 (longest: create_report (99 lines))<br>Responsibilities > 3 (4: I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, Validation & Security) |
| 31 | `agent/session/shutdown_reflection.py` | 147 | 0 | 0 | 1 | 3 | 5 | Functions > 60 lines: 1 (longest: run_session_reflection (126 lines))<br>Responsibilities > 3 (5: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, UI & Interaction, Validation & Security) |
| 32 | `agent/runtime/tool_round.py` | 129 | 0 | 0 | 1 | 2 | 6 | Functions > 60 lines: 1 (longest: execute_tool_round (119 lines))<br>Responsibilities > 3 (6: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security) |
| 33 | `agent/opencode/sandbox.py` | 396 | 1 | 6 | 0 | 0 | 4 | Responsibilities > 3 (4: Command Routing & Dispatch, External / Subprocess / LLM, I/O & Persistence, Validation & Security) |
| 34 | `agent/identity/migration.py` | 141 | 0 | 0 | 1 | 1 | 5 | Functions > 60 lines: 1 (longest: migrate_persisted_identity (115 lines))<br>Responsibilities > 3 (5: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, UI & Interaction, Validation & Security) |
| 35 | `agent/runtime/loop.py` | 275 | 1 | 12 | 0 | 3 | 7 | Responsibilities > 3 (7: External / Subprocess / LLM, Formatting & Display, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security) |
| 36 | `agent/helper_models/model_outcomes.py` | 213 | 2 | 3 | 1 | 1 | 4 | Functions > 60 lines: 1 (longest: print_outcome_summary (65 lines))<br>Responsibilities > 3 (4: I/O & Persistence, Telemetry & Decision Tracking, UI & Interaction, Validation & Security) |
| 37 | `agent/session/plugin_commands.py` | 139 | 0 | 0 | 1 | 1 | 6 | Functions > 60 lines: 1 (longest: handle_plugins_command (78 lines))<br>Responsibilities > 3 (6: Command Routing & Dispatch, External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, UI & Interaction, Validation & Security) |
| 38 | `agent/session/boot.py` | 204 | 0 | 0 | 1 | 1 | 4 | Functions > 60 lines: 1 (longest: run_boot_sequence (65 lines))<br>Responsibilities > 3 (4: Command Routing & Dispatch, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking) |
| 39 | `agent/session/session.py` | 214 | 2 | 10 | 0 | 2 | 6 | Responsibilities > 3 (6: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security) |
| 40 | `agent/runtime/cycle_prompt.py` | 87 | 0 | 0 | 1 | 3 | 4 | Functions > 60 lines: 1 (longest: build_system_prompt_for_cycle (67 lines))<br>Responsibilities > 3 (4: I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, Validation & Security) |
| 41 | `agent/llm/providers/registry.py` | 189 | 1 | 10 | 0 | 1 | 6 | Responsibilities > 3 (6: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security) |
| 42 | `agent/plugins/examples/pet_companion/plugin.py` | 238 | 0 | 0 | 0 | 0 | 4 | Responsibilities > 3 (4: I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction) |
| 43 | `agent/llm/brain_router.py` | 196 | 1 | 13 | 0 | 1 | 5 | Responsibilities > 3 (5: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, Validation & Security) |
| 44 | `agent/opencode/tools.py` | 187 | 0 | 0 | 0 | 1 | 5 | Responsibilities > 3 (5: External / Subprocess / LLM, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security) |
| 45 | `agent/ui/tui/chat_pipeline.py` | 201 | 0 | 0 | 0 | 1 | 4 | Responsibilities > 3 (4: Formatting & Display, I/O & Persistence, Lifecycle & Orchestration, UI & Interaction) |
| 46 | `agent/runtime/plugin_projects.py` | 80 | 0 | 0 | 1 | 1 | 4 | Functions > 60 lines: 1 (longest: check_active_plugin_projects (70 lines))<br>Responsibilities > 3 (4: I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction) |
| 47 | `agent/session/conversation.py` | 118 | 1 | 5 | 0 | 4 | 5 | Responsibilities > 3 (5: External / Subprocess / LLM, I/O & Persistence, Telemetry & Decision Tracking, UI & Interaction, Validation & Security) |
| 48 | `agent/infra/stop_watcher.py` | 175 | 1 | 14 | 0 | 0 | 4 | Responsibilities > 3 (4: I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, Validation & Security) |
| 49 | `agent/ui/phase8_verify.py` | 108 | 1 | 1 | 0 | 4 | 4 | Responsibilities > 3 (4: I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction) |
| 50 | `agent/infra/hardening.py` | 133 | 3 | 6 | 0 | 0 | 5 | Responsibilities > 3 (5: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, Validation & Security) |
| 51 | `agent/runtime/stop_control.py` | 113 | 0 | 0 | 0 | 1 | 5 | Responsibilities > 3 (5: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, Validation & Security) |
| 52 | `agent/ui/tui/status_panels.py` | 146 | 0 | 0 | 0 | 0 | 4 | Responsibilities > 3 (4: Formatting & Display, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction) |
| 53 | `agent/session/plan_recovery.py` | 129 | 0 | 0 | 0 | 1 | 4 | Responsibilities > 3 (4: Formatting & Display, Lifecycle & Orchestration, UI & Interaction, Validation & Security) |
| 54 | `agent/learning/memory_migration.py` | 108 | 0 | 0 | 1 | 0 | 2 | Functions > 60 lines: 1 (longest: migrate_memory_store (97 lines)) |
| 55 | `agent/session/human_input.py` | 139 | 0 | 0 | 0 | 0 | 4 | Responsibilities > 3 (4: Formatting & Display, I/O & Persistence, Lifecycle & Orchestration, Validation & Security) |
| 56 | `agent/prompts/system.py` | 86 | 0 | 0 | 0 | 0 | 6 | Responsibilities > 3 (6: Command Routing & Dispatch, External / Subprocess / LLM, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security) |
| 57 | `agent/infra/process_runner.py` | 102 | 0 | 0 | 1 | 0 | 2 | Functions > 60 lines: 1 (longest: run_process (90 lines)) |
| 58 | `agent/tools/definitions/plugins.py` | 101 | 0 | 0 | 0 | 0 | 5 | Responsibilities > 3 (5: External / Subprocess / LLM, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security) |
| 59 | `agent/ui/wake.py` | 91 | 1 | 0 | 0 | 2 | 4 | Responsibilities > 3 (4: External / Subprocess / LLM, Formatting & Display, Telemetry & Decision Tracking, UI & Interaction) |
| 60 | `agent/ui/disk_tool_demo.py` | 42 | 0 | 0 | 0 | 5 | 4 | Responsibilities > 3 (4: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking) |
| 61 | `agent/session/telemetry.py` | 154 | 2 | 0 | 1 | 0 | 1 | Functions > 60 lines: 1 (longest: update_telemetry (71 lines)) |
| 62 | `agent/tools/handlers/files.py` | 99 | 0 | 0 | 0 | 1 | 4 | Responsibilities > 3 (4: External / Subprocess / LLM, I/O & Persistence, UI & Interaction, Validation & Security) |
| 63 | `agent/runtime/tool_narration.py` | 54 | 0 | 0 | 0 | 1 | 6 | Responsibilities > 3 (6: External / Subprocess / LLM, Formatting & Display, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security) |
| 64 | `agent/infra/event_log.py` | 107 | 2 | 5 | 0 | 0 | 4 | Responsibilities > 3 (4: I/O & Persistence, Telemetry & Decision Tracking, UI & Interaction, Validation & Security) |
| 65 | `agent/session/handoff_builder.py` | 104 | 0 | 0 | 0 | 0 | 4 | Responsibilities > 3 (4: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, UI & Interaction) |
| 66 | `agent/tools/execution/authorization.py` | 83 | 0 | 0 | 0 | 1 | 4 | Responsibilities > 3 (4: External / Subprocess / LLM, Telemetry & Decision Tracking, UI & Interaction, Validation & Security) |
| 67 | `agent/tools/dispatch.py` | 82 | 0 | 0 | 0 | 1 | 4 | Responsibilities > 3 (4: Command Routing & Dispatch, External / Subprocess / LLM, Telemetry & Decision Tracking, Validation & Security) |
| 68 | `agent/tools/execution/call_logging.py` | 46 | 0 | 0 | 0 | 1 | 5 | Responsibilities > 3 (5: External / Subprocess / LLM, I/O & Persistence, Telemetry & Decision Tracking, UI & Interaction, Validation & Security) |
| 69 | `agent/llm/structured_call.py` | 90 | 0 | 0 | 1 | 0 | 1 | Functions > 60 lines: 1 (longest: call_structured_json (81 lines)) |
| 70 | `agent/tools/handlers/plugin_dev.py` | 71 | 0 | 0 | 0 | 0 | 4 | Responsibilities > 3 (4: Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security) |
| 71 | `agent/infra/__init__.py` | 59 | 0 | 0 | 0 | 0 | 4 | Responsibilities > 3 (4: External / Subprocess / LLM, Lifecycle & Orchestration, Telemetry & Decision Tracking, Validation & Security) |
| 72 | `agent/tools/handlers/plan.py` | 58 | 0 | 0 | 0 | 0 | 4 | Responsibilities > 3 (4: Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security) |
| 73 | `agent/ui/formatting/models_view.py` | 39 | 0 | 0 | 0 | 0 | 4 | Responsibilities > 3 (4: Command Routing & Dispatch, Formatting & Display, I/O & Persistence, UI & Interaction) |
| 74 | `agent/prompts/critics.py` | 34 | 0 | 0 | 0 | 0 | 4 | Responsibilities > 3 (4: Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security) |

## Detailed Analysis per Flagged God File

### 1. `agent/opencode/wrapper.py` (LOC: 775, Severity Score: 2912)

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

### 2. `agent/plugins/self_dev.py` (LOC: 912, Severity Score: 2881)

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

### 3. `agent/helper_models/model_decisions.py` (LOC: 904, Severity Score: 2421)

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

### 4. `agent/learning/plan.py` (LOC: 783, Severity Score: 2057)

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

### 5. `agent/identity/identity.py` (LOC: 811, Severity Score: 1679)

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

### 6. `agent/tools/tool_registry.py` (LOC: 470, Severity Score: 1619)

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

### 7. `agent/plugins/manager.py` (LOC: 770, Severity Score: 1596)

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

### 8. `agent/helper_models/model_probe.py` (LOC: 513, Severity Score: 1518)

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

### 9. `agent/infra/migration.py` (LOC: 468, Severity Score: 1420)

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

### 10. `agent/llm/model_registry.py` (LOC: 613, Severity Score: 1398)

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

### 11. `agent/body/container.py` (LOC: 568, Severity Score: 1393)

- **Responsibilities (7)**: Command Routing & Dispatch, External / Subprocess / LLM, Formatting & Display, I/O & Persistence, Telemetry & Decision Tracking, UI & Interaction, Validation & Security
- **Agent Package Fan-Out (3)**: `infra, opencode, prompts`
- **Max Methods in Single Class**: 17
- **Max Constructor Collaborators**: 7

**Triggered Flags**:
- LOC > 400 (568)
- Class > 15 methods: ContainerBody (17)
- Functions > 60 lines: 4 (longest: ContainerBody.capabilities (82 lines))
- Responsibilities > 3 (7: Command Routing & Dispatch, External / Subprocess / LLM, Formatting & Display, I/O & Persistence, Telemetry & Decision Tracking, UI & Interaction, Validation & Security)
- Constructor wires > 6 collaborators (7)

**Functions / Methods > 60 lines**:
- `ContainerBody.capabilities`: 82 lines
- `capabilities`: 82 lines
- `ContainerMetrics.snapshot`: 68 lines
- `snapshot`: 68 lines

### 12. `agent/runtime/cycle_runner.py` (LOC: 367, Severity Score: 1333)

- **Responsibilities (7)**: External / Subprocess / LLM, Formatting & Display, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security
- **Agent Package Fan-Out (4)**: `infra, llm, prompts, tools`
- **Max Methods in Single Class**: 0
- **Max Constructor Collaborators**: 0

**Triggered Flags**:
- Functions > 60 lines: 1 (longest: run_agent_loop (343 lines))
- Responsibilities > 3 (7: External / Subprocess / LLM, Formatting & Display, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security)

**Functions / Methods > 60 lines**:
- `run_agent_loop`: 343 lines

### 13. `agent/session/coordinator.py` (LOC: 391, Severity Score: 1280)

- **Responsibilities (7)**: Command Routing & Dispatch, External / Subprocess / LLM, Formatting & Display, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, Validation & Security
- **Agent Package Fan-Out (5)**: `body, identity, infra, learning, plugins`
- **Max Methods in Single Class**: 36
- **Max Constructor Collaborators**: 1

**Triggered Flags**:
- Class > 15 methods: WakeCoordinator (36)
- Functions > 60 lines: 2 (longest: WakeCoordinator.__init__ (101 lines))
- Responsibilities > 3 (7: Command Routing & Dispatch, External / Subprocess / LLM, Formatting & Display, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, Validation & Security)

**Functions / Methods > 60 lines**:
- `WakeCoordinator.__init__`: 101 lines
- `__init__`: 101 lines

### 14. `agent/plugins/cli.py` (LOC: 597, Severity Score: 1252)

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

### 15. `agent/body/sim.py` (LOC: 547, Severity Score: 1234)

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

### 16. `agent/infra/cost_ledger.py` (LOC: 343, Severity Score: 1135)

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

### 17. `agent/infra/permission_broker.py` (LOC: 421, Severity Score: 1089)

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

### 18. `agent/tools/base_tools.py` (LOC: 392, Severity Score: 1082)

- **Responsibilities (7)**: Command Routing & Dispatch, External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security
- **Agent Package Fan-Out (2)**: `body, infra`
- **Max Methods in Single Class**: 37
- **Max Constructor Collaborators**: 8

**Triggered Flags**:
- Class > 15 methods: ToolRunner (37)
- Responsibilities > 3 (7: Command Routing & Dispatch, External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security)
- Constructor wires > 6 collaborators (8)

### 19. `agent/session/reflection.py` (LOC: 352, Severity Score: 1036)

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

### 20. `agent/plugins/manifest.py` (LOC: 393, Severity Score: 917)

- **Responsibilities (4)**: External / Subprocess / LLM, I/O & Persistence, Telemetry & Decision Tracking, Validation & Security
- **Agent Package Fan-Out (0)**: `None`
- **Max Methods in Single Class**: 1
- **Max Constructor Collaborators**: 0

**Triggered Flags**:
- Functions > 60 lines: 1 (longest: parse_manifest (182 lines))
- Responsibilities > 3 (4: External / Subprocess / LLM, I/O & Persistence, Telemetry & Decision Tracking, Validation & Security)

**Functions / Methods > 60 lines**:
- `parse_manifest`: 182 lines

### 21. `agent/llm/llm.py` (LOC: 374, Severity Score: 905)

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

### 22. `agent/ui/tui/app.py` (LOC: 368, Severity Score: 898)

- **Responsibilities (5)**: Command Routing & Dispatch, Formatting & Display, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction
- **Agent Package Fan-Out (2)**: `body, session`
- **Max Methods in Single Class**: 35
- **Max Constructor Collaborators**: 1

**Triggered Flags**:
- Class > 15 methods: SelfApp (35)
- Responsibilities > 3 (5: Command Routing & Dispatch, Formatting & Display, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction)

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

### 25. `agent/ui/formatting/archive_view.py` (LOC: 215, Severity Score: 806)

- **Responsibilities (5)**: Command Routing & Dispatch, Formatting & Display, I/O & Persistence, Lifecycle & Orchestration, UI & Interaction
- **Agent Package Fan-Out (1)**: `learning`
- **Max Methods in Single Class**: 0
- **Max Constructor Collaborators**: 0

**Triggered Flags**:
- Functions > 60 lines: 1 (longest: build_archive_views (198 lines))
- Responsibilities > 3 (5: Command Routing & Dispatch, Formatting & Display, I/O & Persistence, Lifecycle & Orchestration, UI & Interaction)

**Functions / Methods > 60 lines**:
- `build_archive_views`: 198 lines

### 26. `agent/ui/tui/commands/handlers.py` (LOC: 369, Severity Score: 788)

- **Responsibilities (6)**: Command Routing & Dispatch, External / Subprocess / LLM, Formatting & Display, I/O & Persistence, Lifecycle & Orchestration, UI & Interaction
- **Agent Package Fan-Out (1)**: `session`
- **Max Methods in Single Class**: 2
- **Max Constructor Collaborators**: 0

**Triggered Flags**:
- Functions > 60 lines: 2 (longest: IdentityCommandHandler.handle (81 lines))
- Responsibilities > 3 (6: Command Routing & Dispatch, External / Subprocess / LLM, Formatting & Display, I/O & Persistence, Lifecycle & Orchestration, UI & Interaction)

**Functions / Methods > 60 lines**:
- `IdentityCommandHandler.handle`: 81 lines
- `handle`: 81 lines

### 27. `agent/opencode/status.py` (LOC: 476, Severity Score: 765)

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

### 28. `agent/runtime/wiring.py` (LOC: 185, Severity Score: 751)

- **Responsibilities (5)**: External / Subprocess / LLM, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security
- **Agent Package Fan-Out (8)**: `body, helper_models, identity, infra, learning, llm, plugins, tools`
- **Max Methods in Single Class**: 0
- **Max Constructor Collaborators**: 0

**Triggered Flags**:
- Functions > 60 lines: 1 (longest: wire_loop_collaborators (133 lines))
- Responsibilities > 3 (5: External / Subprocess / LLM, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security)

**Functions / Methods > 60 lines**:
- `wire_loop_collaborators`: 133 lines

### 29. `agent/session/session_runner.py` (LOC: 178, Severity Score: 687)

- **Responsibilities (4)**: External / Subprocess / LLM, Lifecycle & Orchestration, UI & Interaction, Validation & Security
- **Agent Package Fan-Out (5)**: `infra, llm, prompts, runtime, tools`
- **Max Methods in Single Class**: 0
- **Max Constructor Collaborators**: 0

**Triggered Flags**:
- Functions > 60 lines: 1 (longest: run_session (137 lines))
- Responsibilities > 3 (4: External / Subprocess / LLM, Lifecycle & Orchestration, UI & Interaction, Validation & Security)

**Functions / Methods > 60 lines**:
- `run_session`: 137 lines

### 30. `agent/reporting/report.py` (LOC: 239, Severity Score: 635)

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

### 31. `agent/session/shutdown_reflection.py` (LOC: 147, Severity Score: 624)

- **Responsibilities (5)**: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, UI & Interaction, Validation & Security
- **Agent Package Fan-Out (3)**: `helper_models, llm, prompts`
- **Max Methods in Single Class**: 0
- **Max Constructor Collaborators**: 0

**Triggered Flags**:
- Functions > 60 lines: 1 (longest: run_session_reflection (126 lines))
- Responsibilities > 3 (5: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, UI & Interaction, Validation & Security)

**Functions / Methods > 60 lines**:
- `run_session_reflection`: 126 lines

### 32. `agent/runtime/tool_round.py` (LOC: 129, Severity Score: 597)

- **Responsibilities (6)**: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security
- **Agent Package Fan-Out (2)**: `infra, llm`
- **Max Methods in Single Class**: 0
- **Max Constructor Collaborators**: 0

**Triggered Flags**:
- Functions > 60 lines: 1 (longest: execute_tool_round (119 lines))
- Responsibilities > 3 (6: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security)

**Functions / Methods > 60 lines**:
- `execute_tool_round`: 119 lines

### 33. `agent/opencode/sandbox.py` (LOC: 396, Severity Score: 576)

- **Responsibilities (4)**: Command Routing & Dispatch, External / Subprocess / LLM, I/O & Persistence, Validation & Security
- **Agent Package Fan-Out (0)**: `None`
- **Max Methods in Single Class**: 6
- **Max Constructor Collaborators**: 3

**Triggered Flags**:
- Responsibilities > 3 (4: Command Routing & Dispatch, External / Subprocess / LLM, I/O & Persistence, Validation & Security)

### 34. `agent/identity/migration.py` (LOC: 141, Severity Score: 566)

- **Responsibilities (5)**: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, UI & Interaction, Validation & Security
- **Agent Package Fan-Out (1)**: `prompts`
- **Max Methods in Single Class**: 0
- **Max Constructor Collaborators**: 0

**Triggered Flags**:
- Functions > 60 lines: 1 (longest: migrate_persisted_identity (115 lines))
- Responsibilities > 3 (5: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, UI & Interaction, Validation & Security)

**Functions / Methods > 60 lines**:
- `migrate_persisted_identity`: 115 lines

### 35. `agent/runtime/loop.py` (LOC: 275, Severity Score: 560)

- **Responsibilities (7)**: External / Subprocess / LLM, Formatting & Display, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security
- **Agent Package Fan-Out (3)**: `infra, llm, tools`
- **Max Methods in Single Class**: 12
- **Max Constructor Collaborators**: 4

**Triggered Flags**:
- Responsibilities > 3 (7: External / Subprocess / LLM, Formatting & Display, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security)

### 36. `agent/helper_models/model_outcomes.py` (LOC: 213, Severity Score: 518)

- **Responsibilities (4)**: I/O & Persistence, Telemetry & Decision Tracking, UI & Interaction, Validation & Security
- **Agent Package Fan-Out (1)**: `infra`
- **Max Methods in Single Class**: 3
- **Max Constructor Collaborators**: 2

**Triggered Flags**:
- Functions > 60 lines: 1 (longest: print_outcome_summary (65 lines))
- Responsibilities > 3 (4: I/O & Persistence, Telemetry & Decision Tracking, UI & Interaction, Validation & Security)

**Functions / Methods > 60 lines**:
- `print_outcome_summary`: 65 lines

### 37. `agent/session/plugin_commands.py` (LOC: 139, Severity Score: 510)

- **Responsibilities (6)**: Command Routing & Dispatch, External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, UI & Interaction, Validation & Security
- **Agent Package Fan-Out (1)**: `plugins`
- **Max Methods in Single Class**: 0
- **Max Constructor Collaborators**: 0

**Triggered Flags**:
- Functions > 60 lines: 1 (longest: handle_plugins_command (78 lines))
- Responsibilities > 3 (6: Command Routing & Dispatch, External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, UI & Interaction, Validation & Security)

**Functions / Methods > 60 lines**:
- `handle_plugins_command`: 78 lines

### 38. `agent/session/boot.py` (LOC: 204, Severity Score: 509)

- **Responsibilities (4)**: Command Routing & Dispatch, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking
- **Agent Package Fan-Out (1)**: `opencode`
- **Max Methods in Single Class**: 0
- **Max Constructor Collaborators**: 0

**Triggered Flags**:
- Functions > 60 lines: 1 (longest: run_boot_sequence (65 lines))
- Responsibilities > 3 (4: Command Routing & Dispatch, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking)

**Functions / Methods > 60 lines**:
- `run_boot_sequence`: 65 lines

### 39. `agent/session/session.py` (LOC: 214, Severity Score: 464)

- **Responsibilities (6)**: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security
- **Agent Package Fan-Out (2)**: `infra, learning`
- **Max Methods in Single Class**: 10
- **Max Constructor Collaborators**: 3

**Triggered Flags**:
- Responsibilities > 3 (6: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security)

### 40. `agent/runtime/cycle_prompt.py` (LOC: 87, Severity Score: 426)

- **Responsibilities (4)**: I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, Validation & Security
- **Agent Package Fan-Out (3)**: `helper_models, infra, prompts`
- **Max Methods in Single Class**: 0
- **Max Constructor Collaborators**: 0

**Triggered Flags**:
- Functions > 60 lines: 1 (longest: build_system_prompt_for_cycle (67 lines))
- Responsibilities > 3 (4: I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, Validation & Security)

**Functions / Methods > 60 lines**:
- `build_system_prompt_for_cycle`: 67 lines

### 41. `agent/llm/providers/registry.py` (LOC: 189, Severity Score: 424)

- **Responsibilities (6)**: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security
- **Agent Package Fan-Out (1)**: `infra`
- **Max Methods in Single Class**: 10
- **Max Constructor Collaborators**: 2

**Triggered Flags**:
- Responsibilities > 3 (6: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security)

### 42. `agent/plugins/examples/pet_companion/plugin.py` (LOC: 238, Severity Score: 418)

- **Responsibilities (4)**: I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction
- **Agent Package Fan-Out (0)**: `None`
- **Max Methods in Single Class**: 0
- **Max Constructor Collaborators**: 0

**Triggered Flags**:
- Responsibilities > 3 (4: I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction)

### 43. `agent/llm/brain_router.py` (LOC: 196, Severity Score: 411)

- **Responsibilities (5)**: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, Validation & Security
- **Agent Package Fan-Out (1)**: `infra`
- **Max Methods in Single Class**: 13
- **Max Constructor Collaborators**: 3

**Triggered Flags**:
- Responsibilities > 3 (5: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, Validation & Security)

### 44. `agent/opencode/tools.py` (LOC: 187, Severity Score: 402)

- **Responsibilities (5)**: External / Subprocess / LLM, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security
- **Agent Package Fan-Out (1)**: `infra`
- **Max Methods in Single Class**: 0
- **Max Constructor Collaborators**: 0

**Triggered Flags**:
- Responsibilities > 3 (5: External / Subprocess / LLM, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security)

### 45. `agent/ui/tui/chat_pipeline.py` (LOC: 201, Severity Score: 396)

- **Responsibilities (4)**: Formatting & Display, I/O & Persistence, Lifecycle & Orchestration, UI & Interaction
- **Agent Package Fan-Out (1)**: `session`
- **Max Methods in Single Class**: 0
- **Max Constructor Collaborators**: 0

**Triggered Flags**:
- Responsibilities > 3 (4: Formatting & Display, I/O & Persistence, Lifecycle & Orchestration, UI & Interaction)

### 46. `agent/runtime/plugin_projects.py` (LOC: 80, Severity Score: 395)

- **Responsibilities (4)**: I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction
- **Agent Package Fan-Out (1)**: `prompts`
- **Max Methods in Single Class**: 0
- **Max Constructor Collaborators**: 0

**Triggered Flags**:
- Functions > 60 lines: 1 (longest: check_active_plugin_projects (70 lines))
- Responsibilities > 3 (4: I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction)

**Functions / Methods > 60 lines**:
- `check_active_plugin_projects`: 70 lines

### 47. `agent/session/conversation.py` (LOC: 118, Severity Score: 378)

- **Responsibilities (5)**: External / Subprocess / LLM, I/O & Persistence, Telemetry & Decision Tracking, UI & Interaction, Validation & Security
- **Agent Package Fan-Out (4)**: `body, infra, llm, prompts`
- **Max Methods in Single Class**: 5
- **Max Constructor Collaborators**: 4

**Triggered Flags**:
- Responsibilities > 3 (5: External / Subprocess / LLM, I/O & Persistence, Telemetry & Decision Tracking, UI & Interaction, Validation & Security)

### 48. `agent/infra/stop_watcher.py` (LOC: 175, Severity Score: 355)

- **Responsibilities (4)**: I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, Validation & Security
- **Agent Package Fan-Out (0)**: `None`
- **Max Methods in Single Class**: 14
- **Max Constructor Collaborators**: 6

**Triggered Flags**:
- Responsibilities > 3 (4: I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, Validation & Security)

### 49. `agent/ui/phase8_verify.py` (LOC: 108, Severity Score: 348)

- **Responsibilities (4)**: I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction
- **Agent Package Fan-Out (4)**: `identity, infra, llm, tools`
- **Max Methods in Single Class**: 1
- **Max Constructor Collaborators**: 0

**Triggered Flags**:
- Responsibilities > 3 (4: I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction)

### 50. `agent/infra/hardening.py` (LOC: 133, Severity Score: 333)

- **Responsibilities (5)**: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, Validation & Security
- **Agent Package Fan-Out (0)**: `None`
- **Max Methods in Single Class**: 6
- **Max Constructor Collaborators**: 3

**Triggered Flags**:
- Responsibilities > 3 (5: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, Validation & Security)

### 51. `agent/runtime/stop_control.py` (LOC: 113, Severity Score: 328)

- **Responsibilities (5)**: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, Validation & Security
- **Agent Package Fan-Out (1)**: `infra`
- **Max Methods in Single Class**: 0
- **Max Constructor Collaborators**: 0

**Triggered Flags**:
- Responsibilities > 3 (5: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking, Validation & Security)

### 52. `agent/ui/tui/status_panels.py` (LOC: 146, Severity Score: 326)

- **Responsibilities (4)**: Formatting & Display, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction
- **Agent Package Fan-Out (0)**: `None`
- **Max Methods in Single Class**: 0
- **Max Constructor Collaborators**: 0

**Triggered Flags**:
- Responsibilities > 3 (4: Formatting & Display, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction)

### 53. `agent/session/plan_recovery.py` (LOC: 129, Severity Score: 324)

- **Responsibilities (4)**: Formatting & Display, Lifecycle & Orchestration, UI & Interaction, Validation & Security
- **Agent Package Fan-Out (1)**: `learning`
- **Max Methods in Single Class**: 0
- **Max Constructor Collaborators**: 0

**Triggered Flags**:
- Responsibilities > 3 (4: Formatting & Display, Lifecycle & Orchestration, UI & Interaction, Validation & Security)

### 54. `agent/learning/memory_migration.py` (LOC: 108, Severity Score: 322)

- **Responsibilities (2)**: I/O & Persistence, Validation & Security
- **Agent Package Fan-Out (0)**: `None`
- **Max Methods in Single Class**: 0
- **Max Constructor Collaborators**: 0

**Triggered Flags**:
- Functions > 60 lines: 1 (longest: migrate_memory_store (97 lines))

**Functions / Methods > 60 lines**:
- `migrate_memory_store`: 97 lines

### 55. `agent/session/human_input.py` (LOC: 139, Severity Score: 319)

- **Responsibilities (4)**: Formatting & Display, I/O & Persistence, Lifecycle & Orchestration, Validation & Security
- **Agent Package Fan-Out (0)**: `None`
- **Max Methods in Single Class**: 0
- **Max Constructor Collaborators**: 0

**Triggered Flags**:
- Responsibilities > 3 (4: Formatting & Display, I/O & Persistence, Lifecycle & Orchestration, Validation & Security)

### 56. `agent/prompts/system.py` (LOC: 86, Severity Score: 306)

- **Responsibilities (6)**: Command Routing & Dispatch, External / Subprocess / LLM, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security
- **Agent Package Fan-Out (0)**: `None`
- **Max Methods in Single Class**: 0
- **Max Constructor Collaborators**: 0

**Triggered Flags**:
- Responsibilities > 3 (6: Command Routing & Dispatch, External / Subprocess / LLM, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security)

### 57. `agent/infra/process_runner.py` (LOC: 102, Severity Score: 302)

- **Responsibilities (2)**: External / Subprocess / LLM, I/O & Persistence
- **Agent Package Fan-Out (0)**: `None`
- **Max Methods in Single Class**: 0
- **Max Constructor Collaborators**: 0

**Triggered Flags**:
- Functions > 60 lines: 1 (longest: run_process (90 lines))

**Functions / Methods > 60 lines**:
- `run_process`: 90 lines

### 58. `agent/tools/definitions/plugins.py` (LOC: 101, Severity Score: 301)

- **Responsibilities (5)**: External / Subprocess / LLM, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security
- **Agent Package Fan-Out (0)**: `None`
- **Max Methods in Single Class**: 0
- **Max Constructor Collaborators**: 0

**Triggered Flags**:
- Responsibilities > 3 (5: External / Subprocess / LLM, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security)

### 59. `agent/ui/wake.py` (LOC: 91, Severity Score: 301)

- **Responsibilities (4)**: External / Subprocess / LLM, Formatting & Display, Telemetry & Decision Tracking, UI & Interaction
- **Agent Package Fan-Out (2)**: `learning, session`
- **Max Methods in Single Class**: 0
- **Max Constructor Collaborators**: 0

**Triggered Flags**:
- Responsibilities > 3 (4: External / Subprocess / LLM, Formatting & Display, Telemetry & Decision Tracking, UI & Interaction)

### 60. `agent/ui/disk_tool_demo.py` (LOC: 42, Severity Score: 297)

- **Responsibilities (4)**: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking
- **Agent Package Fan-Out (5)**: `infra, llm, prompts, runtime, tools`
- **Max Methods in Single Class**: 0
- **Max Constructor Collaborators**: 0

**Triggered Flags**:
- Responsibilities > 3 (4: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, Telemetry & Decision Tracking)

### 61. `agent/session/telemetry.py` (LOC: 154, Severity Score: 296)

- **Responsibilities (1)**: Telemetry & Decision Tracking
- **Agent Package Fan-Out (0)**: `None`
- **Max Methods in Single Class**: 0
- **Max Constructor Collaborators**: 0

**Triggered Flags**:
- Functions > 60 lines: 1 (longest: update_telemetry (71 lines))

**Functions / Methods > 60 lines**:
- `update_telemetry`: 71 lines

### 62. `agent/tools/handlers/files.py` (LOC: 99, Severity Score: 294)

- **Responsibilities (4)**: External / Subprocess / LLM, I/O & Persistence, UI & Interaction, Validation & Security
- **Agent Package Fan-Out (1)**: `opencode`
- **Max Methods in Single Class**: 0
- **Max Constructor Collaborators**: 0

**Triggered Flags**:
- Responsibilities > 3 (4: External / Subprocess / LLM, I/O & Persistence, UI & Interaction, Validation & Security)

### 63. `agent/runtime/tool_narration.py` (LOC: 54, Severity Score: 289)

- **Responsibilities (6)**: External / Subprocess / LLM, Formatting & Display, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security
- **Agent Package Fan-Out (1)**: `infra`
- **Max Methods in Single Class**: 0
- **Max Constructor Collaborators**: 0

**Triggered Flags**:
- Responsibilities > 3 (6: External / Subprocess / LLM, Formatting & Display, Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security)

### 64. `agent/infra/event_log.py` (LOC: 107, Severity Score: 287)

- **Responsibilities (4)**: I/O & Persistence, Telemetry & Decision Tracking, UI & Interaction, Validation & Security
- **Agent Package Fan-Out (0)**: `None`
- **Max Methods in Single Class**: 5
- **Max Constructor Collaborators**: 1

**Triggered Flags**:
- Responsibilities > 3 (4: I/O & Persistence, Telemetry & Decision Tracking, UI & Interaction, Validation & Security)

### 65. `agent/session/handoff_builder.py` (LOC: 104, Severity Score: 284)

- **Responsibilities (4)**: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, UI & Interaction
- **Agent Package Fan-Out (0)**: `None`
- **Max Methods in Single Class**: 0
- **Max Constructor Collaborators**: 0

**Triggered Flags**:
- Responsibilities > 3 (4: External / Subprocess / LLM, I/O & Persistence, Lifecycle & Orchestration, UI & Interaction)

### 66. `agent/tools/execution/authorization.py` (LOC: 83, Severity Score: 278)

- **Responsibilities (4)**: External / Subprocess / LLM, Telemetry & Decision Tracking, UI & Interaction, Validation & Security
- **Agent Package Fan-Out (1)**: `infra`
- **Max Methods in Single Class**: 0
- **Max Constructor Collaborators**: 0

**Triggered Flags**:
- Responsibilities > 3 (4: External / Subprocess / LLM, Telemetry & Decision Tracking, UI & Interaction, Validation & Security)

### 67. `agent/tools/dispatch.py` (LOC: 82, Severity Score: 277)

- **Responsibilities (4)**: Command Routing & Dispatch, External / Subprocess / LLM, Telemetry & Decision Tracking, Validation & Security
- **Agent Package Fan-Out (1)**: `llm`
- **Max Methods in Single Class**: 0
- **Max Constructor Collaborators**: 0

**Triggered Flags**:
- Responsibilities > 3 (4: Command Routing & Dispatch, External / Subprocess / LLM, Telemetry & Decision Tracking, Validation & Security)

### 68. `agent/tools/execution/call_logging.py` (LOC: 46, Severity Score: 261)

- **Responsibilities (5)**: External / Subprocess / LLM, I/O & Persistence, Telemetry & Decision Tracking, UI & Interaction, Validation & Security
- **Agent Package Fan-Out (1)**: `infra`
- **Max Methods in Single Class**: 0
- **Max Constructor Collaborators**: 0

**Triggered Flags**:
- Responsibilities > 3 (5: External / Subprocess / LLM, I/O & Persistence, Telemetry & Decision Tracking, UI & Interaction, Validation & Security)

### 69. `agent/llm/structured_call.py` (LOC: 90, Severity Score: 252)

- **Responsibilities (1)**: I/O & Persistence
- **Agent Package Fan-Out (0)**: `None`
- **Max Methods in Single Class**: 0
- **Max Constructor Collaborators**: 0

**Triggered Flags**:
- Functions > 60 lines: 1 (longest: call_structured_json (81 lines))

**Functions / Methods > 60 lines**:
- `call_structured_json`: 81 lines

### 70. `agent/tools/handlers/plugin_dev.py` (LOC: 71, Severity Score: 251)

- **Responsibilities (4)**: Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security
- **Agent Package Fan-Out (0)**: `None`
- **Max Methods in Single Class**: 0
- **Max Constructor Collaborators**: 0

**Triggered Flags**:
- Responsibilities > 3 (4: Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security)

### 71. `agent/infra/__init__.py` (LOC: 59, Severity Score: 239)

- **Responsibilities (4)**: External / Subprocess / LLM, Lifecycle & Orchestration, Telemetry & Decision Tracking, Validation & Security
- **Agent Package Fan-Out (0)**: `None`
- **Max Methods in Single Class**: 0
- **Max Constructor Collaborators**: 0

**Triggered Flags**:
- Responsibilities > 3 (4: External / Subprocess / LLM, Lifecycle & Orchestration, Telemetry & Decision Tracking, Validation & Security)

### 72. `agent/tools/handlers/plan.py` (LOC: 58, Severity Score: 238)

- **Responsibilities (4)**: Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security
- **Agent Package Fan-Out (0)**: `None`
- **Max Methods in Single Class**: 0
- **Max Constructor Collaborators**: 0

**Triggered Flags**:
- Responsibilities > 3 (4: Lifecycle & Orchestration, Telemetry & Decision Tracking, UI & Interaction, Validation & Security)

### 73. `agent/ui/formatting/models_view.py` (LOC: 39, Severity Score: 219)

- **Responsibilities (4)**: Command Routing & Dispatch, Formatting & Display, I/O & Persistence, UI & Interaction
- **Agent Package Fan-Out (0)**: `None`
- **Max Methods in Single Class**: 0
- **Max Constructor Collaborators**: 0

**Triggered Flags**:
- Responsibilities > 3 (4: Command Routing & Dispatch, Formatting & Display, I/O & Persistence, UI & Interaction)

### 74. `agent/prompts/critics.py` (LOC: 34, Severity Score: 214)

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
| `agent/ui/tui/views/coverage.py` | 118 | 0 | 5 | 3 |
| `agent/identity/name_context.py` | 154 | 0 | 2 | 2 |
| `agent/prompts/cycle.py` | 133 | 0 | 7 | 3 |
| `agent/tools/handlers/opencode.py` | 72 | 0 | 10 | 3 |
| `agent/infra/untrusted.py` | 117 | 0 | 6 | 2 |
| `agent/tools/definitions/__init__.py` | 112 | 0 | 0 | 3 |
| `agent/ui/voice.py` | 125 | 1 | 0 | 2 |
| `agent/ui/tui/views/archive.py` | 101 | 0 | 5 | 3 |
| `agent/learning/exploration_coverage.py` | 97 | 1 | 4 | 3 |
| `agent/session/version_check.py` | 64 | 0 | 2 | 3 |
| `agent/runtime/config.py` | 62 | 3 | 0 | 3 |
| `agent/session/event_router.py` | 89 | 0 | 2 | 3 |
| `agent/ui/formatting/goals_panel.py` | 87 | 0 | 2 | 2 |
| `agent/tools/definitions/models.py` | 100 | 0 | 0 | 2 |
| `agent/tools/definitions/plan.py` | 96 | 0 | 0 | 2 |
| `agent/tools/permissions.py` | 54 | 0 | 0 | 3 |
| `agent/tools/benchmark.py` | 38 | 0 | 1 | 3 |
| `agent/runtime/context_retrieval.py` | 50 | 0 | 1 | 3 |
| `agent/plugins/examples/pet_companion/phrase_engine.py` | 104 | 0 | 2 | 1 |
| `agent/body/base.py` | 78 | 3 | 0 | 2 |
| `agent/ui/tui/views/conversation_history.py` | 77 | 0 | 3 | 2 |
| `agent/tools/definitions/core.py` | 73 | 0 | 0 | 2 |
| `agent/ui/formatting/conversation_view.py` | 69 | 0 | 1 | 2 |
| `agent/ui/tui/commands/registry.py` | 49 | 1 | 0 | 3 |
| `agent/infra/egress_allowlist.py` | 48 | 1 | 0 | 3 |
| `agent/run.py` | 50 | 0 | 1 | 2 |
| `agent/session/reflection_scheduler.py` | 83 | 0 | 4 | 1 |
| `agent/infra/file_lock.py` | 40 | 0 | 1 | 3 |
| `agent/ui/cardiac_monitor.py` | 80 | 1 | 2 | 1 |
| `agent/ui/cli.py` | 43 | 0 | 1 | 2 |
| `agent/ui/version_check.py` | 27 | 0 | 1 | 2 |
| `agent/prompts/container_body.py` | 55 | 0 | 0 | 2 |
| `agent/runtime/prompts.py` | 44 | 0 | 1 | 1 |
| `agent/prompts/reflection.py` | 53 | 0 | 2 | 2 |
| `agent/ui/tui/activity_log.py` | 50 | 0 | 2 | 2 |
| `agent/ui/tui/widgets.py` | 47 | 1 | 0 | 2 |
| `agent/ui/tui/views/base.py` | 46 | 1 | 2 | 2 |
| `agent/session/headless.py` | 45 | 0 | 1 | 2 |
| `agent/tools/definitions/system.py` | 24 | 0 | 0 | 3 |
| `agent/ui/formatting/rich_markup.py` | 21 | 0 | 1 | 3 |
| `agent/tools/definitions/provider.py` | 40 | 0 | 0 | 2 |
| `agent/tools/execution/model_arg_validation.py` | 53 | 0 | 1 | 1 |
| `agent/tools/handlers/provider.py` | 70 | 0 | 6 | 0 |
| `agent/ui/formatting/__init__.py` | 24 | 0 | 0 | 2 |
| `agent/infra/redirect_handler.py` | 21 | 1 | 0 | 2 |
| `agent/learning/plan_statuses.py` | 39 | 0 | 2 | 1 |
| `agent/plugins/__init__.py` | 36 | 0 | 0 | 1 |
| `agent/infra/provider_calls.py` | 32 | 0 | 1 | 1 |
| `agent/opencode/__init__.py` | 32 | 0 | 0 | 1 |
| `agent/tools/handlers/system.py` | 31 | 0 | 2 | 1 |
| `agent/llm/providers/base.py` | 49 | 5 | 0 | 0 |
| `agent/tools/tool_worker.py` | 27 | 0 | 1 | 1 |
| `agent/infra/atomic_io.py` | 26 | 0 | 2 | 1 |
| `agent/prompts/conversation.py` | 26 | 0 | 2 | 1 |
| `agent/loop.py` | 7 | 0 | 0 | 1 |
| `agent/prompts/identity.py` | 42 | 0 | 1 | 0 |
| `agent/plugins/hello/plugin.py` | 21 | 0 | 3 | 1 |
| `agent/prompts/model_selection.py` | 21 | 0 | 0 | 1 |
| `agent/prompts/safety.py` | 21 | 0 | 0 | 1 |
| `agent/ui/tui/views/__init__.py` | 20 | 0 | 0 | 1 |
| `agent/session/__init__.py` | 18 | 0 | 0 | 1 |
| `agent/body/__init__.py` | 15 | 0 | 0 | 1 |
| `agent/prompts/delegation.py` | 30 | 0 | 1 | 0 |
| `agent/ui/tui/__init__.py` | 9 | 0 | 0 | 1 |
| `agent/ui/tui/commands/__init__.py` | 8 | 0 | 0 | 1 |
| `agent/prompts/tasks.py` | 27 | 0 | 0 | 0 |
| `agent/disk_tool_demo.py` | 7 | 0 | 0 | 0 |
| `agent/model_outcomes.py` | 7 | 0 | 0 | 0 |
| `agent/report.py` | 7 | 0 | 0 | 0 |
| `agent/wake.py` | 7 | 0 | 0 | 0 |
| `agent/ui/tui/commands/base.py` | 21 | 1 | 0 | 0 |
| `agent/event_log.py` | 4 | 0 | 0 | 0 |
| `agent/prompts/probes.py` | 11 | 0 | 0 | 0 |
| `agent/infra/timestamp.py` | 9 | 0 | 1 | 0 |
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
