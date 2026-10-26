"""Stalled task detection, human reporting, and autonomous de-escalation."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now_utc() -> str:
    """Return current UTC ISO-formatted timestamp."""
    return datetime.now(timezone.utc).isoformat()


def format_human_report(
    goal: str,
    tool_name: str,
    error_details: str,
    why_explanation: str = "",
    suggestions: list[str] | None = None,
    next_goal: str = "",
    task_id: str = "",
) -> str:
    """Render a human-facing report for a stalled task."""
    clean_goal = str(goal).strip() or "Unnamed Task"
    clean_tool = str(tool_name).strip() or "Tool Action"
    clean_err = str(error_details).strip() or "Action repeatedly failed or encountered barrier"
    clean_id = str(task_id).strip() or "task-1"
    clean_why = str(why_explanation).strip() or (
        "The agent encountered repeated errors, compilation failures, or permission "
        "barriers while attempting actions or generating workspace files for this goal."
    )
    sug_list = suggestions or [
        "Review the error diagnostic above and any partially generated workspace files.",
        "If a permission limit was reached, review config/permissions.json.",
        f"To approve and reactivate this goal, run /approve {clean_id} in the TUI chat box.",
    ]
    suggestions_rendered = "\n".join(f"{i+1}. {s}" for i, s in enumerate(sug_list))

    lines = [
        f"# Stalled Task Report — {now_utc()}",
        "",
        f"### Task ID: {clean_id}",
        f"- **Task ID**: `{clean_id}`",
        f"- **Goal**: {clean_goal}",
        "- **Status**: Demoted to `blocked` (Priority 3).",
        f"- **Failed Tool / Action**: `{clean_tool}`",
        f"- **Error Diagnostic**: `{clean_err}`",
        "",
        "### Why This Happened",
        clean_why,
        "",
        "### How to Approve or Re-activate",
        "1. Address any underlying issues (e.g. host configuration, dependencies, or config/permissions.json).",
        f"2. In the TUI chat box, approve and re-activate this task by typing:",
        f"   `/approve {clean_id}`",
        "   SELF will promote this goal back to priority 1 and work on it after its current cycle.",
        f"3. Or to permanently decline this goal:",
        f"   `/decline {clean_id}`",
        "",
        "### Actionable Steps for the Human",
        suggestions_rendered,
        "",
        "### Autonomous Work Status",
        (
            f"SELF has demoted this goal to avoid blocking autonomous progress. SELF is now working on: **{next_goal}**."
            if next_goal
            else "SELF has demoted this goal to avoid blocking autonomous progress and continues autonomous exploration in the meantime."
        ),
        "",
    ]
    return "\n".join(lines)


def write_human_report(
    workspace: Path | str,
    goal: str,
    tool_name: str,
    error_details: str,
    why_explanation: str = "",
    suggestions: list[str] | None = None,
    next_goal: str = "",
    task_id: str = "",
    logger: Any = None,
) -> Path:
    """Write or prepend to workspace/report_human.md and notify human inbox."""
    ws = Path(workspace).resolve()
    report_file = ws / "report_human.md"
    content = format_human_report(
        goal=goal,
        tool_name=tool_name,
        error_details=error_details,
        why_explanation=why_explanation,
        suggestions=suggestions,
        next_goal=next_goal,
        task_id=task_id,
    )

    try:
        if report_file.exists():
            existing = report_file.read_text(encoding="utf-8", errors="replace")
            full_content = content + "\n---\n\n" + existing
        else:
            full_content = content
        report_file.write_text(full_content, encoding="utf-8")
    except OSError:
        pass

    try:
        inbox_path = ws / "state" / "human_input.jsonl"
        inbox_path.parent.mkdir(parents=True, exist_ok=True)
        clean_id = str(task_id).strip() or "task-1"
        record = {
            "timestamp": now_utc(),
            "task_id": clean_id,
            "text": (
                f"Task [{clean_id}] stalled: '{goal}' failed during {tool_name} ({error_details[:150]}). "
                f"Demoted to blocked in plan and logged report_human.md. Continuing work on: {next_goal or 'next goal'}."
            ),
            "kind": "decision",
        }
        with inbox_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass

    if logger and hasattr(logger, "narrate"):
        clean_id = str(task_id).strip() or "task-1"
        logger.narrate(
            f"Task [{clean_id}] '{goal[:60]}' stalled after tool '{tool_name}' failed. "
            "Deprioritized to blocked, logged report_human.md, and continuing to next goal."
        )

    return report_file
