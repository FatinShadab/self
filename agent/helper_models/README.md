# Helper Models

## Purpose

Bounded helper-model probes, task decisions, and outcome records. It stores agent judgments separately from objective signals.

## Read first

1. `model_probe.py` — Probe and official-page research.
2. `model_decisions.py` — Delegation and model-choice checkpoints.
3. `model_outcomes.py` — Objective and self-reported outcomes.

## Files

| File | Responsibility | Key classes or functions |
| --- | --- | --- |
| `model_probe.py` | Probe and official-page research | `ModelProber, check_code_output` |
| `model_decisions.py` | Delegation and model-choice checkpoints | `ModelDecisions, print_decision_summary` |
| `model_outcomes.py` | Objective and self-reported outcomes | `ModelOutcomes, print_outcome_summary` |

## How it works

ModelProber checks eligible models; ModelDecisions records a choice and optional delegation; ModelOutcomes links later signals to calls.
- **Official Model Research**: `research_model` extracts model parameters, context window, pricing, speed, and strengths from official documentation (up to 500 KB page bodies) and Ollama `/tags` sections. Navigation/header boilerplate is filtered out. Returns status `facts_found` (only when verified values are extracted with excerpts), `fetched_no_model_fact`, or `not_found` (with HTTP status), and reports `urls_tried`.
- **Picker Summary & Fact Provenance**: `_summary_entry` surfaces rich model profiles including `facts` with explicit origins (`web` vs unverified `model_knowledge`), top-level `facts_origin`, `probe_latency_ms` alongside measured call `avg_latency_ms`, truncation rate, and recorded stats.
- **Anti-Inference Prompting**: The model picker prompt explicitly directs the deciding model not to infer capability, parameter count, or architecture from model names (e.g. "120b", "ultra"), but instead compare using supplied facts (distinguishing web-verified facts from unverified `model_knowledge`) and recorded stats.
- **Unlimited Checkpoints & Moment Caching**: Checkpoint caps have been removed; every checkpoint decision is a real deliberate choice with a reason. Decisions are cached per moment within the active task and current tool attempt, and invalidated on a new tool name, task start, or failure.
- **Model Output Ceilings & Bounded Retries**: Calls utilize the model's output ceiling from the registry. If a structured call (checkpoint, critic, reflection) hits truncation, exactly one bounded retry is executed requesting concise output conforming to valid JSON.

## State it touches

Workspace paths: state/model_decisions.jsonl, state/model_outcomes.jsonl, state/model_task_observations.jsonl, state/models.json.

## Depends on / used by

Depends on infra and llm. Used by runtime, session, and ui.

## Tests

Run `python -m unittest discover -s /opt/agent/tests/helper_models -v` in the container.

## Gotchas

1. A helper being used is observational. Only randomized arm comparisons support a causal claim.
2. `critic_flagged_but_tests_passed` is ambiguous (the critic may have caught a subtle security flaw or bug that unit tests failed to test). It requires manual review and must not be treated as evidence against the critic model.
