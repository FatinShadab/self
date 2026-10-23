# Learning

## Purpose

Persistent memory, environment facts, and coverage summaries. The loop reads this material to choose useful next work.

## Read first

1. `learning.py` — Memory retrieval, environment map, curriculum.
2. `plan.py` — Autonomous plan store, goal lifecycle, and hygiene.
3. `exploration_coverage.py` — Visited directories and registered tool coverage.

## Files

| File | Responsibility | Key classes or functions |
| --- | --- | --- |
| `learning.py` | Memory retrieval, environment map, curriculum | `LearningStore` |
| `plan.py` | Persistent plan store and goal lifecycle (facade) | `PlanStore, visible_plan_items, consolidate_plan_items` |
| `plan_statuses.py` | Plan item status constants and visibility filters | `COMPLETED_PLAN_STATUSES, ACTIVE_PLAN_STATUSES` |
| `plans/consolidation.py` | Plan size capping by consolidation | `consolidate_plan_items` |
| `plans/archive.py` | Archive log management for completed/dropped goals | `append_archive_records, read_archived_items` |
| `plans/persistence.py` | Atomic plan serialization and seed goal generation | `save_plan_atomic, load_plan_data, build_seed_goal` |
| `plans/queries.py` | Plan queries, retrieval query derivation, prompt summary | `filter_top_items, build_retrieval_query, format_prompt_summary` |
| `plans/actions.py` | Plan mutation actions (add, edit, drop, mark_done, reorder) | `find_plan_item, apply_add_action, apply_edit_action` |
| `plans/human_decisions.py` | Human input decision processing and tracking | `process_human_input_decision` |
| `plans/hygiene.py` | Plan hygiene maintenance (archive purge, stale marking) | `apply_plan_hygiene` |
| `plans/plugin_lifecycle.py` | Goal suspension and resumption for plugin lifecycles | `suspend_plugin_goals, resume_plugin_goals` |
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
