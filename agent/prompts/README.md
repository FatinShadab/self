# Prompts

## Purpose

Centralized repository of all LLM prompt text in the SELF harness. Contains pure string constants and pure deterministic string-building functions with zero external dependencies and no runtime I/O.

## Read first

1. `safety.py` — Safety-critical rules: untrusted data delimiters, stop rules, and capability permission rules.
2. `system.py` — Core system prompt head, standing goal, opencode capability prompt, identity rules, neutral orientation task, and prompt assembly.
3. `container_body.py` — Optional container body narrative, expectations to verify, interests, and initial orientation task.
4. `cycle.py` — Loop exploration cycle message builders, helper hints, nudges, and model context.
5. `conversation.py` — Interactive conversation system prompt and user message formatting.
6. `critics.py` — Tool and plugin critic evaluation prompts and retry nudges.
7. `reflection.py` — Coordinator session reflection and background reflection prompts.
8. `identity.py` — Autonomous voice specification and identity prompt context builders.
9. `model_selection.py` — Helper model selection and decision prompts.
10. `delegation.py` — Sandbox coding delegation prompts for opencode.
11. `probes.py` — Model capability probe cases and evaluation system prompt.
12. `tasks.py` — Demo benchmark tasks and curriculum learning tasks.

## Files

| File | Responsibility | Key classes, constants, or functions |
| --- | --- | --- |
| `safety.py` | Delimiter and safety-critical rules | `UNTRUSTED_DATA_RULE, STOP_RULE, PERMISSION_RULE` |
| `system.py` | Core system prompt pieces, standing goal, and neutral orientation | `CORE_SYSTEM_PROMPT_HEAD, STANDING_GOAL, SEED_STANDING_GOAL, OPENCODE_CAPABILITY_PROMPT, ORIENTATION_TASK, CORE_CAPABILITY_RULE, CORE_IDENTITY_RULES, OFF_PROMPT_PREFIXES, render_core_system_prompt` |
| `container_body.py` | Optional container embodiment expectations and rules | `CONTAINER_EMBODIMENT_TEXT, CONTAINER_EMBODIMENT_CLAUSE, CONTAINER_BODY_RULES, CONTAINER_DEFAULT_INTERESTS, CONTAINER_INITIAL_ORIENTATION_TASK, CONTAINER_NOTES_PREAMBLE, DEFAULT_NOTES_PREAMBLE` |
| `cycle.py` | Cycle user message and runtime prompt assembly | `RECORD_DELEGATION_OUTCOME_REMINDER, HELPER_MODELS_AVAILABLE_PROMPT, build_helper_eval_hint, build_cycle_helper_prompt, build_mid_cycle_human_input_message, build_active_plugin_project_part, build_model_context_block, assemble_loop_system_prompt, build_cycle_user_message` |
| `conversation.py` | Interactive conversation prompts | `render_conversation_system_prompt, build_conversation_user_message` |
| `critics.py` | Tool and plugin critic prompts | `CRITIC_PROMPT, PLUGIN_CRITIC_PROMPT, TOOL_CRITIC_RETRY_NUDGE` |
| `reflection.py` | Session handoff and background reflection | `COORDINATOR_REFLECTION_SYSTEM_PROMPT, COORDINATOR_REFLECTION_RETRY_NUDGE, BACKGROUND_REFLECTION_SYSTEM_PROMPT, BACKGROUND_REFLECTION_RETRY_NUDGE, build_coordinator_reflection_base_prompt, build_startup_eval_instructions` |
| `identity.py` | Autonomous voice and identity context | `AUTONOMOUS_VOICE, NO_IDENTITY_RECORD_CONTEXT, IDENTITY_CONTEXT_HEADER, render_identity_prompt_context` |
| `model_selection.py` | Helper model picker and evaluation prompts | `ASK_MODEL_SYSTEM_PROMPT, ASK_MODEL_RETRY_NUDGE, DECIDE_MODEL_BASE_SYSTEM, DECIDE_MODEL_RETRY_SYSTEM, DECIDE_MODEL_RETRY_NUDGE` |
| `delegation.py` | Opencode coding sandbox delegation prompts | `OPENCODE_RETRY_NOTE, build_opencode_prompt` |
| `probes.py` | Probe test cases and evaluation system prompt | `PROBE_SYSTEM_PROMPT, PROBE_CASES` |
| `tasks.py` | Static exploration and benchmark tasks (demo-only) | `BUILD_TASK, REUSE_TASK, CURRICULUM_TASKS` |

## How it works

Every module is pure standard-library Python source with no side-effects or I/O. Prompts remain in the protected harness code tree under `agent/prompts/`. Callers import string constants directly or call pure builder functions (`build_*`, `render_*`).

The core prompt path is strictly environment-agnostic: by default, no body profile or location claims are injected, and SELF is given a neutral orientation task to discover its environment using tools. Body descriptions (such as `container_body.py`) are optional profiles loaded only when explicitly configured, and must describe expectations to verify rather than unconditional facts.

Plugin-supplied text (via slots such as `embodiment_clause`, `pre/post_capability_rules`, `plugin_embodiment`, `plugin_section`, `plugin_projects_section`, `env_context`, or `embodiment_block`) must describe expectations to verify, never facts about the environment, and must not override voice, stop, permission, or untrusted-data rules.

## State it touches

None. The `prompts` package has no runtime state, touches no files, and performs no I/O.

## Depends on / used by

Depends on the Python standard library only (`from __future__ import annotations`, `typing`).

Used by `infra` (`untrusted.py`), `body` (`container.py`), `tools` (`tool_registry.py`), `learning` (`plan.py`, `learning.py`), `helper_models` (`model_probe.py`, `model_decisions.py`), `identity` (`identity.py`, `migration.py`), `plugins` (`self_dev.py`), `runtime` (`loop.py`), `session` (`conversation.py`, `coordinator.py`, `reflection.py`), `opencode` (`wrapper.py`), and `ui` (`disk_tool_demo.py`).

## Tests

Run `python -m unittest discover -s agent/tests/prompts` to execute:
- `test_static_constants_sha256.py`: Verifies SHA-256 hashes of all static prompt constants.
- `test_golden_characterization.py`: Verifies exact byte-for-byte characterization captures from model calls.
- `test_import_identity.py`: Asserts backward compatibility and object identity across legacy import paths.
- `test_env_agnostic_prompts.py`: Regression tests ensuring default prompt paths are free of location/environment assumptions and optional profiles use expectation framing.

## Gotchas

Do not import any `agent.*` packages from `agent.prompts`. Do not perform file, environment, or network I/O. Preserve verbatim formatting and quirks of all prompt strings.
