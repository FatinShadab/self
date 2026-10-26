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
) -> str:
    """Render a human-facing report for a stalled task."""
    clean_goal = str(goal).strip() or "Unnamed Task"
    clean_tool = str(tool_name).strip() or "Tool Action"
    clean_err = str(error_details).strip() or "Action repeatedly failed or encountered barrier"
    clean_why = str(why_explanation).strip() or (
        "The agent encountered repeated errors, compilation failures, or permission "
        "barriers while attempting actions or generating workspace files for this goal."
    )
    sug_list = suggestions or [
        "Review the error diagnostic above and any partially generated workspace files.",
        "If a permission limit was reached, review config/permissions.json.",
        "To reactivate or retry this goal, send a message in the TUI or run /goal <task>.",
    ]
    suggestions_rendered = "\n".join(f"{i+1}. {s}" for i, s in enumerate(sug_list))

    lines = [
        f"# Stalled Task Report — {now_utc()}",
        "",
        "### Task Overview",
        f"- **Goal**: {clean_goal}",
        "- **Status**: Demoted to `blocked` (Priority 3).",
        f"- **Failed Tool / Action**: `{clean_tool}`",
        f"- **Error Diagnostic**: `{clean_err}`",
        "",
        "### Why This Happened",
        clean_why,
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
        record = {
            "timestamp": now_utc(),
            "text": (
                f"Task stalled: '{goal}' failed during {tool_name} ({error_details[:150]}). "
                f"Demoted to blocked in plan and logged report_human.md. Continuing work on: {next_goal or 'next goal'}."
            ),
            "kind": "decision",
        }
        with inbox_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass

    if logger and hasattr(logger, "narrate"):
        logger.narrate(
            f"Task '{goal[:60]}' stalled after tool '{tool_name}' failed. "
            "Deprioritized to blocked, logged report_human.md, and continuing to next goal."
        )

    return report_file
