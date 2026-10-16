# Reporting

## Purpose

Human-readable summaries of actions and learning. Reports use workspace state without running a model.

## Read first

1. `report.py` — Learning report and CLI.

## Files

| File | Responsibility | Key classes or functions |
| --- | --- | --- |
| `report.py` | Learning report and CLI | `create_report, main` |

## How it works

create_report reads new events since its cursor, summarizes learning, failures, per-model calls, decisions, and provenance-labelled outcomes, then optionally advances the cursor. A host invocation can supply saved calibration and A/B text through `SELF_REPORT_CALIBRATION_FILE` and `SELF_REPORT_AB_FILE`; container invocations ignore those files.

## State it touches

Workspace paths: logs/actions.jsonl, memory/, state/map.json, state/report_cursor.json, state/providers.json.

## Depends on / used by

Depends on infra and learning. Invoked by agent.report and tests.

## Tests

Run `python -m unittest discover -s /opt/agent/tests/reporting -v` in the container.

## Gotchas

Use --no-advance when inspecting a report without moving the cursor.
