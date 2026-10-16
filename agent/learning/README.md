# Learning

## Purpose

Persistent memory, environment facts, and coverage summaries. The loop reads this material to choose useful next work.

## Read first

1. `learning.py` — Memory retrieval, environment map, curriculum.
2. `exploration_coverage.py` — Visited directories and registered tool coverage.

## Files

| File | Responsibility | Key classes or functions |
| --- | --- | --- |
| `learning.py` | Memory retrieval, environment map, curriculum | `LearningStore` |
| `exploration_coverage.py` | Visited directories and registered tool coverage | `build_coverage, directory_visits, registered_tools` |

## How it works

LearningStore stores facts and retrieves relevant memories. build_coverage combines action events and registered tools for the TUI.

## State it touches

Workspace paths: memory/memory.jsonl, memory/lessons.jsonl, state/map.json, logs/actions.jsonl, tools/.

## Depends on / used by

Depends on infra. Used by runtime, reporting, and ui.

## Tests

Run `python -m unittest discover -s /opt/agent/tests/learning -v` in the container.

## Gotchas

Coverage counts observed successful actions, not every filesystem item.
