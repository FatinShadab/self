# Session

## Purpose

Durable session state, human inbox, conversations, and reflections. These modules support wake and recovery across runs.

## Read first

1. `session.py` — Handoff, journal, inbox, and plan state.
2. `conversation.py` — Bounded read-only conversation work.
3. `reflection.py` — Background reflection.

## Files

| File | Responsibility | Key classes or functions |
| --- | --- | --- |
| `session.py` | Handoff, journal, inbox, and plan state | `SessionStore, HumanInbox, default_plan` |
| `conversation.py` | Bounded read-only conversation work | `ConversationManager` |
| `reflection.py` | Background reflection | `ReflectionManager` |

## How it works

SessionStore persists plans and handoffs; ConversationManager handles messages in bounded workers; ReflectionManager writes reflection results for the wake coordinator.

## State it touches

Workspace paths: state/session.json, state/handoff.json, state/human_inbox.jsonl, memory/, logs/actions.jsonl.

## Depends on / used by

Depends on infra, llm, and helper_models. Used by ui.

## Tests

Run `python -m unittest discover -s /opt/agent/tests/session -v` in the container.

## Gotchas

Late worker results must not revive a stopped session.
