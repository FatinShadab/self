"""Goals panel formatting and plan pane height clamping for TUI."""
from __future__ import annotations

from typing import Any

from agent.learning.plan_statuses import COMPLETED_PLAN_STATUSES
from agent.ui.formatting.rich_markup import escape_rich_markup


PLAN_MIN_HEIGHT = 5
WORKLOG_MIN_HEIGHT = 5
PLAN_RESIZER_HEIGHT = 1


def clamped_plan_height(requested: int, work_pane_height: int) -> int:
    """Keep both panes usable while the plan divider is dragged."""
    maximum = max(
        PLAN_MIN_HEIGHT,
        work_pane_height - WORKLOG_MIN_HEIGHT - PLAN_RESIZER_HEIGHT,
    )
    return max(PLAN_MIN_HEIGHT, min(maximum, requested))


def format_goals_panel(
    goals: list[dict[str, Any]],
    current_activity: str = "",
    current_cycle: int = 1,
) -> str:
    """Format unfinished goals ordered with in-progress first, then priority."""
    unfinished: list[dict[str, Any]] = []

    for item in goals:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status", "todo")).strip().lower()
        if status not in COMPLETED_PLAN_STATUSES and status not in {"dropped", "canceled", "cancelled"}:
            unfinished.append(item)

    def _unfinished_sort_key(it: dict[str, Any]) -> tuple[int, int, int]:
        st = str(it.get("status", "todo")).strip().lower()
        is_prog = 0 if st in {"in_progress", "in-progress", "working"} else 1
        try:
            prio = int(it.get("priority", 2))
        except (ValueError, TypeError):
            prio = 2
        try:
            created = int(it.get("created_cycle", 0))
        except (ValueError, TypeError):
            created = 0
        return (is_prog, prio, created)

    unfinished.sort(key=_unfinished_sort_key)

    lines: list[str] = []

    if unfinished:
        for item in unfinished:
            desc = escape_rich_markup(item.get("goal") or item.get("step", ""))
            status = str(item.get("status", "todo")).strip().lower()
            created = item.get("created_cycle")
            if status in {"in_progress", "in-progress", "working"}:
                cycle_tag = f" [dim](c{created})[/dim]" if created else ""
                lines.append(f"[cyan]▶ (in progress)[/cyan] {desc}{cycle_tag}")
            elif created and created >= current_cycle:
                lines.append(f"[yellow]+ (added c{created})[/yellow] {desc}")
            else:
                prio = item.get("priority", 2)
                prio_tag = f"[red]! (p{prio})[/red] " if prio == 1 else ""
                cycle_tag = f" [dim](c{created})[/dim]" if created else ""
                lines.append(f"[white]• (todo)[/white] {prio_tag}{desc}{cycle_tag}")
    elif not goals:
        lines.append("[dim]No goals recorded yet[/dim]")
    else:
        lines.append("[dim]All recorded goals achieved[/dim]")

    return "[b]Goals[/b]\n" + "\n".join(lines)


__all__ = [
    "PLAN_MIN_HEIGHT",
    "WORKLOG_MIN_HEIGHT",
    "PLAN_RESIZER_HEIGHT",
    "clamped_plan_height",
    "format_goals_panel",
]
