# Ui

## Purpose

Wake coordinator, Textual terminal interface, optional voice, and verification CLI. The UI is the top-level entry point for an interactive session.

## Read first

1. `wake.py` — Boot, recovery, status, commands, TUI and headless CLI.
2. `voice.py` — Optional voice input/output.
3. `phase8_verify.py` — Phase 8 verification CLI.
4. `disk_tool_demo.py` — Live create_tool acceptance demo.

## Files

| File | Responsibility | Key classes or functions |
| --- | --- | --- |
| `wake.py` | Boot, recovery, status, commands, TUI and headless CLI | `WakeCoordinator, run_tui, run_headless` |
| `voice.py` | Optional voice input/output | `VoiceController` |
| `phase8_verify.py` | Phase 8 verification CLI | `verify, main` |
| `disk_tool_demo.py` | Live create_tool acceptance demo | `main` |

## How it works

WakeCoordinator loads state and starts a bounded AgentLoop. run_tui defines the Textual app, sends commands to the coordinator, and renders status and activity. `/models` formats registry evidence and the last ten decision origins; the status panel shows per-model call totals.

## State it touches

Workspace paths: state/session.json, state/handoff.json, state/models.json, logs/actions.jsonl, STOP.

## Depends on / used by

Depends on infra, llm, tools, learning, helper_models, identity, runtime, and session. Invoked by agent.wake.

## Tests

Run `python -m unittest discover -s /opt/agent/tests/ui -v` in the container.

## Gotchas

wake.py is 1,652 lines and stays intact because UI state and nested callbacks are shared. Read helpers and telemetry, WakeCoordinator, run_headless, run_tui, then CLI main.
`disk_tool_demo.py` makes live provider calls and is not part of provider-free verification.
