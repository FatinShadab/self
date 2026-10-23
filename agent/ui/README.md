# Ui

## Purpose

Wake coordinator, Textual terminal interface, optional voice, and verification CLI. The UI is the top-level entry point for an interactive session.

## Read first

1. `wake.py` — Backward-compatible facade re-exporting TUI, formatting, and CLI entry points.
2. `tui/app.py` — Textual `SelfApp` composition root and `run_tui`.
3. `tui/commands/` — Command-pattern registry and handlers for slash commands.
4. `tui/views/` — FullScreenView overlay views for coverage, archive, and conversation history.
5. `voice.py` — Optional voice input/output.
6. `phase8_verify.py` — Phase 8 verification CLI.
7. `disk_tool_demo.py` — Live create_tool acceptance demo.

## Files

| File | Responsibility | Key classes or functions |
| --- | --- | --- |
| `wake.py` | Backward-compatible re-exporting facade | `WakeCoordinator, run_tui, run_headless, main` |
| `cli.py` | Command-line argument parsing and signals | `main` |
| `cardiac_monitor.py` | Animated ECG presence indicator | `cardiac_monitor_intensity, cardiac_monitor_frame` |
| `formatting/rich_markup.py` | Untrusted string escaping for Rich | `escape_rich_markup` |
| `formatting/goals_panel.py` | Goals panel formatting and height clamping | `format_goals_panel, clamped_plan_height` |
| `formatting/archive_view.py` | Two-column archive view builder | `build_archive_views` |
| `formatting/conversation_view.py` | Paginated conversation history formatter | `format_conversation_history_view` |
| `formatting/models_view.py` | Readable model registry snapshot formatter | `format_models_snapshot` |
| `tui/app.py` | Textual `SelfApp` UI application and `run_tui` | `SelfApp, run_tui` |
| `tui/widgets.py` | Custom draggable divider widget | `PlanResizeHandle` |
| `tui/activity_log.py` | Worklog activity queuing and async draining | `queue_activity, drain_activity` |
| `tui/chat_pipeline.py` | Chat bubble queuing, typing, and history persistence | `queue_chat, drain_chat, render_message` |
| `tui/status_panels.py` | Status panel refresh and formatting | `refresh_all_status_panels` |
| `tui/commands/registry.py` | Command pattern registry for slash commands | `CommandRegistry` |
| `tui/commands/handlers.py` | Specific handlers for slash commands | `ViewCommandHandler, LifecycleCommandHandler, etc.` |
| `tui/views/coverage.py` | Exploration coverage full-screen overlay | `open_coverage, back_from_coverage` |
| `tui/views/archive.py` | Archive plans & goals full-screen overlay | `open_archive, back_from_archive` |
| `tui/views/conversation_history.py` | Conversation history full-screen overlay | `open_conversation_history, back_from_conversation_history` |
| `voice.py` | Optional voice input/output | `VoiceController` |
| `phase8_verify.py` | Phase 8 verification CLI | `verify, main` |
| `disk_tool_demo.py` | Live create_tool acceptance demo | `main` |

## How it works

`WakeCoordinator` coordinates startup and cycles. In interactive mode, `run_tui` launches `SelfApp`, which renders cardiac monitor presence, live activity feeds, status panels, and a chat stream with typing effects. Slash commands are dispatched through `CommandRegistry`. Overlay views (`coverage`, `archive`, `conversation_history`) provide focused full-screen views with `/back` navigation.

## State it touches

Workspace paths: state/session.json, state/handoff.json, state/models.json, state/conversation_history.jsonl, logs/actions.jsonl, STOP.

## Depends on / used by

Depends on infra, llm, tools, learning, helper_models, identity, runtime, and session. Invoked by agent.wake.

## Tests

Run `python -m unittest discover -s /opt/agent/tests/ui -v` in the container.

## Gotchas

`wake.py` re-exports all public symbols for backwards compatibility. Textual imports are guarded so headless execution and unit tests remain portable.
