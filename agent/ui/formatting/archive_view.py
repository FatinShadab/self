"""Two-column archive view builder showing session plans and achieved goals."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from agent.learning.plan_statuses import COMPLETED_PLAN_STATUSES
from agent.ui.formatting.rich_markup import escape_rich_markup


def build_archive_views(workspace: str | Path, coordinator: Any) -> tuple[str, str]:
    """Build (session_plans_markup, achieved_goals_markup) for the two-column /archive view."""
    root = Path(workspace)

    # ==========================================
    # Column 1: Session Plans (Running & Completed)
    # ==========================================
    plan_lines: list[str] = [
        "[b]Session Plans[/b]",
        "Completed and currently running session plans organized by Session ID.",
        "Type [bold]/back[/bold] to return to main UI or [bold]/archive[/bold] to refresh.",
        "",
    ]

    # Current running session
    running_id = getattr(getattr(coordinator, "status", None), "session_id", "") or "running"
    running_iter = getattr(getattr(coordinator, "status", None), "iteration", 0)

    lock = getattr(coordinator, "lock", None)
    if lock:
        with lock:
            starting_plan = list(getattr(coordinator, "starting_plan", []) or getattr(coordinator, "plan", []))
    else:
        starting_plan = list(getattr(coordinator, "starting_plan", []) or getattr(coordinator, "plan", []))

    plan_lines.append(
        f"[bold cyan]● Current Session: {escape_rich_markup(running_id)}[/bold cyan] [dim](running · cycle {running_iter})[/dim]"
    )
    if starting_plan:
        plan_lines.append("[dim]Starting plan established at session boot:[/dim]")
        for idx, item in enumerate(starting_plan, 1):
            if not isinstance(item, dict):
                continue
            step = escape_rich_markup(item.get("goal") or item.get("step", ""))
            status = escape_rich_markup(str(item.get("status", "todo")).strip().lower())
            prio = item.get("priority", 2)
            plan_lines.append(f"  {idx}. [cyan]({status})[/cyan] [dim][p{prio}][/dim] {step}")
            why = item.get("why")
            if why:
                plan_lines.append(f"     [dim]Why: {escape_rich_markup(why)}[/dim]")
    else:
        plan_lines.append("  [dim]No starting plan recorded for current session.[/dim]")
    plan_lines.append("")

    # Completed sessions from journal and sessions.jsonl
    plan_lines.append("[bold green]● Completed Sessions[/bold green]")

    journal_by_session: dict[str, dict[str, Any]] = {}
    journal_path = root / "state" / "journal.md"
    if journal_path.exists():
        try:
            journal_content = journal_path.read_text(encoding="utf-8", errors="replace")
            sections = re.split(r"(?m)^## ", journal_content)
            for sec in sections:
                if not sec.strip():
                    continue
                first_line = sec.splitlines()[0]
                match = re.search(r"session\s+([a-zA-Z0-9_-]+)", first_line)
                if match:
                    sess_id = match.group(1).strip()
                    plans: list[str] = []
                    summary: str = ""
                    in_plan = False
                    for line in sec.splitlines()[1:]:
                        if line.startswith("### Next plan"):
                            in_plan = True
                            continue
                        elif line.startswith("###") or line.startswith("End reason:"):
                            in_plan = False
                        if in_plan and line.strip().startswith("- "):
                            plans.append(line.strip()[2:])
                    paragraphs = [
                        p.strip()
                        for p in sec.split("\n\n")
                        if p.strip() and not p.startswith("###") and not p.startswith("End reason") and p != first_line
                    ]
                    if paragraphs:
                        summary = paragraphs[0]
                    journal_by_session[sess_id] = {
                        "plans": plans,
                        "summary": summary,
                        "raw_header": first_line,
                    }
        except OSError:
            pass

    sessions_list: list[dict[str, Any]] = []
    sessions_path = root / "state" / "sessions.jsonl"
    if sessions_path.exists():
        try:
            for line in sessions_path.read_text(encoding="utf-8", errors="replace").splitlines():
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    if isinstance(data, dict):
                        sessions_list.append(data)
                except json.JSONDecodeError:
                    continue
        except OSError:
            pass

    seen_sessions = set()
    completed_entries: list[tuple[str, dict[str, Any]]] = []

    for s in reversed(sessions_list):
        sid = str(s.get("session_id", ""))
        if not sid or sid in seen_sessions or sid == running_id:
            continue
        seen_sessions.add(sid)
        completed_entries.append((sid, s))

    for sid, jdata in journal_by_session.items():
        if sid not in seen_sessions and sid != running_id:
            seen_sessions.add(sid)
            completed_entries.append((sid, {"session_id": sid}))

    if not completed_entries:
        plan_lines.append("  [dim]No completed sessions recorded yet.[/dim]")
    else:
        for idx, (sid, sinfo) in enumerate(completed_entries, 1):
            end_reason = sinfo.get("end_reason", "completed")
            iters = sinfo.get("iteration_count", "?")
            tokens = sinfo.get("token_spend", "?")
            plan_lines.append(
                f"[bold white]Session {escape_rich_markup(sid)}[/bold white] [dim]({escape_rich_markup(end_reason)} · {iters} cycles · {tokens} tokens)[/dim]"
            )
            j = journal_by_session.get(sid, {})
            plans = j.get("plans", [])
            if plans:
                plan_lines.append("  [dim]Session plan:[/dim]")
                for p in plans:
                    plan_lines.append(f"  • {escape_rich_markup(p)}")
            elif sinfo.get("probable_cause"):
                plan_lines.append(f"  [red]Crash cause: {escape_rich_markup(sinfo['probable_cause'])}[/red]")
            else:
                plan_lines.append("  [dim](No plan items recorded)[/dim]")
            if j.get("summary"):
                plan_lines.append(f"  [dim]Summary: {escape_rich_markup(j['summary'][:200])}[/dim]")
            plan_lines.append("")

    # ==========================================
    # Column 2: Achieved Goals
    # ==========================================
    goals_lines: list[str] = [
        "[b]Achieved Goals[/b]",
        "All goals completed and achieved across cycles and sessions.",
        "Type [bold]/back[/bold] to return to main UI or [bold]/archive[/bold] to refresh.",
        "",
    ]

    items: list[dict[str, Any]] = []
    plan_store = getattr(coordinator, "plan_store", None)
    if plan_store is not None:
        try:
            plan_store.load()
            items = list(plan_store.items)
        except Exception:
            items = []
    if not items and hasattr(coordinator, "plan"):
        items = list(coordinator.plan)

    achieved_goals: list[dict[str, Any]] = []
    seen_goal_keys: set[str] = set()

    for it in items:
        if not isinstance(it, dict):
            continue
        status = str(it.get("status", "")).strip().lower()
        if status in COMPLETED_PLAN_STATUSES and status not in {"dropped", "canceled", "cancelled"}:
            key = str(it.get("id") or it.get("goal") or it.get("step", ""))
            if key not in seen_goal_keys:
                seen_goal_keys.add(key)
                achieved_goals.append(it)

    goals_lines.append(f"[bold green]Total Achieved: {len(achieved_goals)}[/bold green]")
    goals_lines.append("")

    if not achieved_goals:
        goals_lines.append("[dim]No achieved goals recorded yet.[/dim]")
    else:
        for idx, it in enumerate(achieved_goals, 1):
            desc = escape_rich_markup(it.get("goal") or it.get("step", ""))
            gid = escape_rich_markup(str(it.get("id", f"goal-{idx}")))
            cycle = it.get("updated_cycle") or it.get("created_cycle")
            cycle_tag = f" [dim](cycle {cycle})[/dim]" if cycle else ""
            prio = it.get("priority", 2)
            goals_lines.append(f"[bold green]✓[/bold green] [bold white]{desc}[/bold white]{cycle_tag}")
            goals_lines.append(f"  [dim]ID: {gid}  |  Priority: p{prio}  |  Status: done[/dim]")
            why = it.get("why")
            if why:
                goals_lines.append(f"  [dim]Why: {escape_rich_markup(why)}[/dim]")
            evidence = it.get("evidence")
            if evidence:
                goals_lines.append(f"  [dim]Evidence: {escape_rich_markup(evidence)}[/dim]")
            goals_lines.append("")

    return "\n".join(plan_lines), "\n".join(goals_lines)


__all__ = [
    "build_archive_views",
]
