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
| `base_tools.py` | Facade and ToolRunner composition root for built-in tools | `ToolRunner, TOOL_DEFINITIONS, HELPER_TOOL_NAMES, DEFAULT_OUTPUT_CAP` |
| `permissions.py` | Permission levels, reversibility flags, and output cap | `TOOL_PERMISSION_LEVELS, REVERSIBLE_TOOL_NAMES, DEFAULT_OUTPUT_CAP` |
| `dispatch.py` | Dispatches validated tool calls to handlers and plugins | `dispatch_tool` |
| `definitions/` | Single-purpose tool JSON schemas preserving canonical order | `models, core, plan, provider, system, plugins` |
| `execution/` | Logging, broker authorization, and argument validation | `call_logging, authorization, model_arg_validation` |
| `handlers/` | Concrete execution handlers for base tools and sandboxes | `files, plan, provider, plugin_dev, opencode, system` |
| `tool_registry.py` | Review, test, register, and retrieve custom tools | `ToolRegistry, schema_from_code` |
| `tool_worker.py` | Subprocess entry point for custom tool calls | `main` |
| `benchmark.py` | Small provider benchmark | `run_benchmark` |

## How it works

ToolRunner dispatches base actions. ToolRegistry reviews candidates, runs tests through process_runner, and registers passing code; tool_worker invokes registered code in a child process.

- **Model Tool Argument & Name Validation**: `ToolRunner.execute` intercepts calls to `probe_model`, `research_model`, `record_model_assessment`, and `ask_model`. Unexpected or missing arguments return actionable errors listing valid arguments rather than raising Python `TypeError`. Registry lookups provide alias hints (`+/- "-cloud"`) and reject asking the base model via `ask_model`. `record_model_assessment` and `research_model` accept optional `facts` allowing the agent to supply knowledge facts with `origin: "model_knowledge"` and `verified: false`.
- **Deduplicated Rejection Logging**: When an on-disk tool candidate has been modified outside `create_tool` (e.g. `test_tool.py`), `ToolRegistry.refresh` logs `tool_load_rejected` once per tool per session with explicit instructions to clear it by re-testing through `create_tool`.

## State it touches

Workspace paths: tools/<name>/tool.py, tools/<name>/meta.json, tools/<name>/attempts/, memory/lessons.jsonl, state/provider_scores.json.

## Depends on / used by

Depends on infra and llm. Used by runtime and ui.

## Tests

Run `python -m unittest discover -s /opt/agent/tests/tools -v` in the container.

## Gotchas

1. The provider benchmark makes live provider calls; tests use fake router responses.
2. In-cycle tool rejections are not logged repeatedly across cycles once reported for the session.
