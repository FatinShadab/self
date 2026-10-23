# Runtime

## Purpose

The bounded autonomous action loop. It joins model calls, tools, memory, identity, and helper decisions into each cycle.

## Read first

1. `loop.py` — Autonomous loop facade, AgentLoop lifecycle facade, and CLI main.
2. `cycle_runner.py` — Cycle boundary orchestration, state accounting, and checkpoints.
3. `wiring.py` — Explicit dependency injection and collaborator wiring.

## Files

| File | Responsibility | Key classes or functions |
| --- | --- | --- |
| `loop.py` | Facade re-exporting public names, AgentLoop delegation, CLI | `AgentConfig, AgentLoop, retrieve_context, main` |
| `config.py` | Configuration dataclass and run summary types | `AgentConfig, RunSummary, LLMProtocol` |
| `prompts.py` | System prompt assembly and core prompt constants | `assemble_system_prompt, SYSTEM_PROMPT` |
| `context_retrieval.py` | Keyword workspace context retrieval | `retrieve_context` |
| `stop_control.py` | Stop checking, safe boundary pausing, and daily budget reset | `check_is_stopped, wait_while_paused, pause_until_daily_reset` |
| `tool_narration.py` | User-facing narration formatting for tool and model outputs | `format_tool_narration, format_content_narration` |
| `plugin_projects.py` | Active plugin projects stop-loss monitoring | `check_active_plugin_projects` |
| `cycle_prompt.py` | Per-cycle system and model prompt assembly | `build_system_prompt_for_cycle` |
| `wiring.py` | Collaborator wiring and explicit dependency injection | `wire_loop_collaborators, LoopCollaborators` |
| `tool_round.py` | Inner tool round execution and duplicate action guard | `execute_tool_round` |
| `cycle_runner.py` | Full autonomous cycle execution and outcome accounting | `run_agent_loop` |

## How it works

AgentLoop wires its collaborating systems via `wiring.py`, builds the per-cycle prompt and available tools via `cycle_prompt.py`, executes tool turns via `tool_round.py`, records outcomes, and stops on STOP, iteration, or clock limits via `cycle_runner.py`. When the daily token allowance is reached, it pauses cleanly via `stop_control.py` until reset.

## State it touches

Workspace paths: state/checkpoint.json, state/models.json, logs/actions.jsonl, memory/, tools/, STOP.

## Depends on / used by

Depends on infra, llm, tools, learning, helper_models, and identity. Used by session and ui.

## Tests

Run `python -m unittest discover -s /opt/agent/tests/runtime -v` in the container.

## Gotchas

1. Backward compatibility: `from agent.runtime.loop import AgentLoop, AgentConfig, retrieve_context, assemble_system_prompt, main` remains fully functional.
2. `time.sleep` patching in tests: `mock.patch("agent.runtime.loop.time.sleep")` is honored because `loop.py` imports `time` and passes `time.sleep` to the underlying stop control routines.
