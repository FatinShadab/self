# Tools

## Purpose

Built-in actions and the create_tool pipeline. Generated tools live in the writable workspace, separate from this image-owned harness.

## Read first

1. `base_tools.py` — Built-in tool definitions and dispatch.
2. `tool_registry.py` — Review, test, register, and retrieve custom tools.
3. `tool_worker.py` — Subprocess entry point for custom tool calls.
4. `benchmark.py` — Small provider benchmark.

## Files

| File | Responsibility | Key classes or functions |
| --- | --- | --- |
| `base_tools.py` | Built-in tool definitions and dispatch | `ToolRunner, TOOL_DEFINITIONS` |
| `tool_registry.py` | Review, test, register, and retrieve custom tools | `ToolRegistry, schema_from_code` |
| `tool_worker.py` | Subprocess entry point for custom tool calls | `main` |
| `benchmark.py` | Small provider benchmark | `run_benchmark` |

## How it works

ToolRunner dispatches base actions. ToolRegistry reviews candidates, runs tests through process_runner, and registers passing code; tool_worker invokes registered code in a child process.

## State it touches

Workspace paths: tools/<name>/tool.py, tools/<name>/meta.json, tools/<name>/attempts/, memory/lessons.jsonl, state/provider_scores.json.

## Depends on / used by

Depends on infra and llm. Used by runtime and ui.

## Tests

Run `python -m unittest discover -s /opt/agent/tests/tools -v` in the container.

## Gotchas

The provider benchmark makes live provider calls; tests use fake router responses.
