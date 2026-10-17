# Runtime

## Purpose

The bounded autonomous action loop. It joins model calls, tools, memory, identity, and helper decisions into each cycle.

## Read first

1. `loop.py` — Config, context retrieval, cycle execution, CLI.

## Files

| File | Responsibility | Key classes or functions |
| --- | --- | --- |
| `loop.py` | Config, context retrieval, cycle execution, CLI | `AgentConfig, AgentLoop, retrieve_context, main` |

## How it works

AgentLoop builds the prompt and available tools, calls the base model with the model ceiling, executes tool actions, records outcomes, and stops on STOP, iteration, or clock limits. When the daily token allowance is reached, it pauses cleanly until reset.

## State it touches

Workspace paths: state/checkpoint.json, state/models.json, logs/actions.jsonl, memory/, tools/, STOP.

## Depends on / used by

Depends on infra, llm, tools, learning, helper_models, and identity. Used by session and ui.

## Tests

Run `python -m unittest discover -s /opt/agent/tests/runtime -v` in the container.

## Gotchas

loop.py remains a single 653-line file: read AgentConfig and retrieve_context, then AgentLoop setup, cycle dispatch, and CLI main.
