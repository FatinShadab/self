"""Cycle memory logging and curriculum difficulty progression."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from agent.infra.event_log import EventLogger
from agent.infra.migration import deterministic_summary
from agent.learning.store.constants import _words
from agent.learning.store.memory_log import read_memory_entries
from agent.prompts.tasks import CURRICULUM_TASKS


def record_cycle_memory(
    workspace: Path,
    state_dir: Path,
    task: str,
    cycle: int,
    actions: list[dict[str, Any]],
    report: str,
    append_memory_fn: Callable[..., dict[str, Any]],
    load_notes_fn: Callable[[], str],
    rewrite_notes_fn: Callable[[], None],
    notes_cap: int,
    plugin: str = "core",
    body: str = "container",
) -> None:
    """Summarize one cycle into memory.jsonl, store detailed report, and refresh notes."""
    action_names = [str(action.get("name", "tool")) for action in actions]
    failures = [name for name, action in zip(action_names, actions) if not action.get("ok", False)]
    outcome = "completed" if not failures else f"completed with tool failures: {', '.join(failures)}"
    tried = f"Cycle {cycle}: {task or 'standing exploration goal'}; tools: {', '.join(action_names) or 'none'}"

    # Write full report to workspace/state/reports/
    reports_dir = state_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_filename = f"cycle_{cycle}_{report_ts}.txt"
    report_rel_path = f"state/reports/{report_filename}"
    (workspace / report_rel_path).write_text(report or "Cycle completed without a textual report.", encoding="utf-8")

    # Deterministic bounded summary for lesson field
    bounded_lesson = deterministic_summary(report)
    tags = list(_words(f"{task} {report} {' '.join(action_names)}"))[:30]
    append_memory_fn(
        what_was_tried=tried,
        outcome=outcome,
        lesson=bounded_lesson,
        tags=tags,
        plugin=plugin,
        body=body,
        report_path=report_rel_path,
    )
    if cycle % 3 == 0 or len(load_notes_fn()) >= notes_cap:
        rewrite_notes_fn()


def propose_curriculum_task(memory_path: Path, logger: EventLogger) -> str:
    """Choose a bounded practice task from recent successes."""
    entries = read_memory_entries(memory_path)
    successes = sum(1 for entry in entries[-12:] if str(entry.get("outcome", "")).startswith("completed"))
    difficulty = min(5, 1 + successes // 3)
    proposal = CURRICULUM_TASKS[difficulty - 1]
    logger.log("curriculum_proposed", difficulty=difficulty, task=proposal)
    return proposal
