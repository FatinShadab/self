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

## State it touches

Workspace paths: state/model_decisions.jsonl, state/model_outcomes.jsonl, state/model_task_observations.jsonl, state/models.json.

## Depends on / used by

Depends on infra and llm. Used by runtime, session, and ui.

## Tests

Run `python -m unittest discover -s /opt/agent/tests/helper_models -v` in the container.

## Gotchas

A helper being used is observational. Only randomized arm comparisons support a causal claim.
