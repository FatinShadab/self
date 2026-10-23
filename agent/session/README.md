# Session

## Purpose

Durable session state, human inbox, conversations, and reflections. These modules support wake and recovery across runs.

## Read first

1. `coordinator.py` — Wake coordinator composition root and lifecycle facade.
2. `session_runner.py` — Autonomous session loop execution and shutdown handoffs.
3. `session.py` — Handoff, journal, inbox, and plan state.
4. `boot.py` — Environment spot checks, orientation diffs, and greeting composition.
5. `conversation.py` — Bounded read-only conversation work.
6. `reflection.py` — Background reflection.

## Files

| File | Responsibility | Key classes or functions |
| --- | --- | --- |
| `coordinator.py` | Composition root and backward-compatible facade | `WakeCoordinator` |
| `telemetry.py` | Live runtime usage, state, and snapshot tracking | `RuntimeTelemetry`, `WakeStatus`, `update_telemetry`, `build_runtime_snapshot` |
| `event_router.py` | Event listener routing, activity logging, checkpointing | `handle_checkpoint_cycle`, `handle_session_event` |
| `reflection_scheduler.py` | Async reflection scheduling and triggers | `reflection_triggers`, `schedule_reflection`, `accept_reflection_reply` |
| `plugin_commands.py` | Human CLI handlers for plugins and proposals | `handle_plugins_command`, `handle_proposals_command`, `handle_slash_command` |
| `boot.py` | Wake boot sequence, spot checks, greeting builder | `run_boot_sequence`, `spot_check_map`, `compose_greeting` |
| `plan_recovery.py` | Plan normalization, display formatting, and budget recovery | `normalized_plan`, `visible_plan_items`, `recover_budget_blocked_plan` |
| `handoff_builder.py` | Durable handoff generation and pending input tracking | `make_handoff`, `pending_human_inputs`, `tool_list` |
| `shutdown_reflection.py` | Bounded LLM shutdown reflection with retry logic | `run_session_reflection` |
| `human_input.py` | Human input parsing, name extraction, and context building | `handle_receive_human_input`, `human_name_candidate`, `build_conversation_context` |
| `session_runner.py` | Core loop execution, evaluation setup, summary logging | `run_session`, `run_session_with_lock` |
| `headless.py` | Unattended foreground execution loop | `run_headless` |
| `session.py` | Handoff, journal, inbox, and plan state | `SessionStore`, `HumanInbox`, `default_plan` |
| `conversation.py` | Bounded read-only conversation work | `ConversationManager` |
| `reflection.py` | Background reflection | `ReflectionManager` |
| `version_check.py` | Code version verification on startup | `verify_startup_code_version` |

## How it works

`WakeCoordinator` coordinates startup, runtime telemetry, and shutdown. `run_session` executes the autonomous `AgentLoop` inside an advisory lock. At cycle boundaries and session end, `handle_checkpoint_cycle` and `make_handoff` record state into `SessionStore`. `ConversationManager` handles human conversations in bounded worker threads, while `ReflectionManager` handles background reflections.

## State it touches

Workspace paths: state/session.json, state/handoff.json, state/human_inbox.jsonl, memory/, logs/actions.jsonl.

## Depends on / used by

Depends on infra, llm, body, tools, learning, helper_models, identity, plugins, and runtime. Used by ui and run.py.

## Tests

Run `python -m unittest discover -s /opt/agent/tests/session -v` in the container.

## Gotchas

Late worker results must not revive a stopped session.
