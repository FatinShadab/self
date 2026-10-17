"""SELF's wake-up coordinator and optional Textual terminal interface."""
from __future__ import annotations

import argparse
import asyncio
from collections import deque
import json
import os
import platform
import re
import shutil
import signal
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from agent.tools.base_tools import TOOL_DEFINITIONS, ToolRunner
from agent.session.conversation import ConversationManager
from agent.learning.exploration_coverage import CoverageSummary, build_coverage
from agent.infra.event_log import EventLogger
from agent.infra.hardening import DailyTokenLedger
from agent.identity.identity import IdentityStore
from agent.learning.learning import LearningStore
from agent.llm.llm import BudgetedLLM, LLMClient, response_truncated
from agent.helper_models.model_decisions import ModelDecisions
from agent.infra.file_lock import locked_file
from agent.runtime.loop import AgentConfig, AgentLoop, STANDING_GOAL
from agent.learning.plan import PlanStore
from agent.ui.version_check import verify_startup_code_version
from agent.session.reflection import ReflectionManager
from agent.session.session import HumanInbox, SessionStore, default_plan


KNOWN_CREDENTIAL_ENV = (
    "OLLAMA_API_KEYS", "OLLAMA_API_KEY", "OLLAM_API_KEYS", "OLLAM_API_KEY",
    "ANTHROPIC_API_KEYS", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "GROQ_API_KEY",
    "OPENROUTER_API_KEY", "MISTRAL_API_KEY", "CEREBRAS_API_KEY", "HF_TOKEN",
    "CLOUDFLARE_API_TOKEN",
)

COMPLETED_PLAN_STATUSES = frozenset({
    "done", "complete", "completed", "achieved", "finished", "closed",
    "cancelled", "canceled", "dropped",
})

PLAN_MIN_HEIGHT = 5
WORKLOG_MIN_HEIGHT = 5
PLAN_RESIZER_HEIGHT = 1
CARDIAC_MONITOR_WIDTH = 6
CARDIAC_MONITOR_BEAT_INTERVAL = 13


@dataclass(frozen=True)
class CardiacMonitorIntensity:
    """Visual tempo and amplitude for one agent-presence state."""

    name: str
    beat_interval: int
    pulse_height: int
    tick_divisor: int
    tick_stride: int


MONITOR_STOPPED = CardiacMonitorIntensity("stopped", 1, 0, 1, 0)
MONITOR_THINKING = CardiacMonitorIntensity("thinking", 21, 2, 3, 1)
MONITOR_WORKING = CardiacMonitorIntensity("working", 9, 3, 1, 2)
MONITOR_IDLE = CardiacMonitorIntensity("idle", 17, 2, 4, 1)


def cardiac_monitor_intensity(state: str, *, stopped: bool = False) -> CardiacMonitorIntensity:
    """Choose a monitor profile from the coordinator's live state."""
    if stopped:
        return MONITOR_STOPPED
    state = state.strip().upper()
    if "THINK" in state:
        return MONITOR_THINKING
    if state in {"WORKING", "USING TOOL"}:
        return MONITOR_WORKING
    return MONITOR_IDLE


def cardiac_monitor_frame(
    frame: int,
    width: int = CARDIAC_MONITOR_WIDTH,
    *,
    beat_interval: int = CARDIAC_MONITOR_BEAT_INTERVAL,
    pulse_height: int = 3,
) -> str:
    """Render a full-width ECG trace at the requested intensity."""
    width = max(6, width)
    rows = [[" "] * width for _ in range(3)]
    rows[2] = ["_"] * width
    if pulse_height <= 0:
        return "\n".join("".join(row) for row in rows)

    # Thinking has a short, quiet peak. Work has a taller and more frequent
    # spike. Both sweep across the full available header width.
    pulse = ((0, 2, "/"), (1, 1, "/"), (2, 1, "\\"), (3, 2, "\\")) if pulse_height < 3 else (
        (0, 2, "/"), (1, 1, "/"), (2, 0, "|"), (3, 1, "\\"), (4, 2, "\\")
    )
    phase = frame % max(5, beat_interval)
    for pulse_x in range(width - phase, -len(pulse), -max(5, beat_interval)):
        for offset, row, character in pulse:
            column = pulse_x + offset
            if 0 <= column < width:
                rows[row][column] = character
    return "\n".join("".join(row) for row in rows)


def visible_plan_items(plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return only active plan items for the live panel."""
    return [
        item for item in plan
        if isinstance(item, dict)
        and str(item.get("status", "todo")).strip().lower() not in COMPLETED_PLAN_STATUSES
    ]


def normalized_plan(plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only actionable plan entries in durable state.

    Completed/cancelled entries are useful in logs, but retaining them in the
    handoff invites the next reflection to resurrect stale work.
    """
    active = visible_plan_items(plan)
    for it in active:
        g = str(it.get("goal") or it.get("step", "")).strip()
        it["goal"] = g
        it["step"] = g
    return active if active else default_plan()


def clamped_plan_height(requested: int, work_pane_height: int) -> int:
    """Keep both panes usable while the plan divider is dragged."""
    maximum = max(
        PLAN_MIN_HEIGHT,
        work_pane_height - WORKLOG_MIN_HEIGHT - PLAN_RESIZER_HEIGHT,
    )
    return max(PLAN_MIN_HEIGHT, min(maximum, requested))


def escape_rich_markup(value: Any) -> str:
    """Return untrusted text that is safe to interpolate into Rich markup.

    The TUI uses a few Rich tags for its own headings. Plan entries, identity
    fields, provider labels, and telemetry, however, can originate with an LLM
    or command output. Escape every literal ``[`` (rather than just known tag
    shapes) so arbitrary bracketed text cannot become Rich markup and make the
    entire Textual screen fail to reflow.
    """
    return str(value).replace("\\", "\\\\").replace("[", "\\[")


def format_goals_panel(
    goals: list[dict[str, Any]],
    current_activity: str = "",
    current_cycle: int = 1,
) -> str:
    """Format goals panel showing max 5 unfinished goals ordered with in-progress first, then priority."""
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
        for item in unfinished[:5]:
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
        if len(unfinished) > 5:
            lines.append(f"[dim]  (+{len(unfinished) - 5} more pending)[/dim]")
    elif not goals:
        lines.append("[dim]No goals recorded yet[/dim]")
    else:
        lines.append("[dim]All recorded goals achieved[/dim]")

    return "[b]Goals[/b]\n" + "\n".join(lines)


def format_starting_plan(starting_plan: list[dict[str, Any]], session_id: str = "") -> str:
    """Render the session starting plan as clean markdown for the chat view."""
    if not starting_plan:
        return "No starting plan recorded for this session yet."

    session_label = f" (Session `{session_id[:12]}`)" if session_id else ""
    lines = [
        f"**Starting Plan / Targets{session_label}**",
        "",
        "*This was the plan when this session started:*",
        "",
    ]
    for idx, item in enumerate(starting_plan, 1):
        if not isinstance(item, dict):
            continue
        step = str(item.get("goal") or item.get("step", "")).strip()
        status = str(item.get("status", "todo")).strip().lower()
        lines.append(f"{idx}. ({status}) {step}")
        why = str(item.get("why", "")).strip()
        if why:
            lines.append(f"   *Why:* {why}")
    return "\n".join(lines)


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

    plan_lines.append(f"[bold cyan]● Current Session: {escape_rich_markup(running_id)}[/bold cyan] [dim](running · cycle {running_iter})[/dim]")
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
                        p.strip() for p in sec.split("\n\n")
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
            plan_lines.append(f"[bold white]Session {escape_rich_markup(sid)}[/bold white] [dim]({escape_rich_markup(end_reason)} · {iters} cycles · {tokens} tokens)[/dim]")
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


def format_conversation_history_view(
    messages: list[dict[str, Any]],
    page: int = 0,
    page_size: int = 20,
    entity_name: str = "SELF",
) -> str:
    """Format a paginated view of conversation history for the /conversation screen."""
    if not messages:
        return (
            "[b]Conversation History[/b]\n"
            "No recorded conversation messages yet.\n\n"
            "Type [bold]/back[/bold] to return to the main view."
        )

    total = len(messages)
    max_pages = max(1, (total + page_size - 1) // page_size)
    clamped_page = max(0, min(page, max_pages - 1))

    end_idx = max(0, total - clamped_page * page_size)
    start_idx = max(0, end_idx - page_size)
    page_messages = messages[start_idx:end_idx]

    lines = [
        "[b]Conversation History[/b]",
        f"Showing messages {start_idx + 1}–{end_idx} of {total}  (Page {clamped_page + 1} of {max_pages})",
        "Type [bold]/previous[/bold] for older messages, [bold]/back[/bold] to return, [bold]/conversation[/bold] for latest.",
        "",
    ]

    if clamped_page > 0 and start_idx == 0:
        lines.append("[dim]── Oldest recorded messages (beginning of history) ──[/dim]")
        lines.append("")

    for item in page_messages:
        role = str(item.get("role", "agent")).strip().lower()
        kind = str(item.get("kind", "chat")).strip().lower()
        text = escape_rich_markup(item.get("message", ""))
        ts = str(item.get("timestamp", "")).strip()
        ts_label = f" [dim]({ts[:19].replace('T', ' ')})[/dim]" if ts else ""

        if role == "human":
            badge = "[bold white on dark_orange] YOU [/bold white on dark_orange]"
            header = f"{badge} [bold #ffbd7a]Human[/bold #ffbd7a]{ts_label}"
        else:
            badge = f"[bold white on dark_blue] {escape_rich_markup(entity_name)} [/bold white on dark_blue]"
            header = f"{badge} [bold #8ed8ff]{escape_rich_markup(kind.title())}[/bold #8ed8ff]{ts_label}"

        lines.append(header)
        lines.append(text)
        lines.append("[dim]─" * 48 + "[/dim]")
        lines.append("")

    if clamped_page < max_pages - 1:
        lines.append("[dim]Type [bold]/previous[/bold] to view older messages.[/dim]")

    return "\n".join(lines)


def format_models_snapshot(snapshot: dict[str, Any]) -> str:
    """Readable /models view of registry evidence and recent decisions."""
    registry = snapshot.get("registry") or {}
    models = registry.get("models", []) if isinstance(registry, dict) else []
    lines = ["Model registry:"]
    if not models:
        lines.append("No model data yet.")
    for entry in models:
        stats = entry.get("measured_stats") or {}
        lines.append(f"- {entry.get('name', 'unknown')} ({entry.get('role', '?')}): "
                     f"status={entry.get('status', 'unknown')}; "
                     f"calls={stats.get('calls', 0)} failures={stats.get('failures', 0)}; "
                     f"assessment={entry.get('agent_assessment') or 'none'}; "
                     f"ratings={json.dumps(entry.get('ratings'), ensure_ascii=False, sort_keys=True)}; "
                     f"measured_stats={json.dumps(stats, ensure_ascii=False, sort_keys=True)}")
    lines.append("Last ten decisions:")
    decisions = snapshot.get("last_ten_decisions") or []
    if not decisions:
        lines.append("No decisions yet.")
    for row in decisions[-10:]:
        lines.append(f"- {row.get('source', '?')} → {row.get('model', '?')} "
                     f"origin={row.get('origin', 'unknown')} task={row.get('task_type', '?')}")
    return "\n".join(lines)


from agent.session.coordinator import (
    WakeCoordinator as _SessionWakeCoordinator,
    WakeStatus,
    RuntimeTelemetry,
    run_headless,
    _requests_text,
    now_utc,
)
from agent.body.container import ContainerMetrics



class WakeCoordinator(_SessionWakeCoordinator):
    """Textual UI compatible WakeCoordinator front-end."""
    pass


def run_tui(coordinator: WakeCoordinator) -> int:
    """Run a wake session with the terminal UI."""
    try:
        from textual import events
        from textual.app import App, ComposeResult
        from textual.css.query import NoMatches
        from textual.containers import Horizontal, Vertical, VerticalScroll
        from textual.widgets import Footer, Header, Input, Static
        from rich.console import Group
        from rich.markdown import Markdown
        from rich.text import Text
        from agent.ui.voice import VoiceController
    except ImportError:
        coordinator.logger.narrate("Textual is unavailable; falling back to --headless mode.")
        return run_headless(coordinator)

    class PlanResizeHandle(Static):
        """One-line divider that gives the plan a draggable vertical size."""

        def __init__(self, on_drag: Callable[[int], None]) -> None:
            super().__init__("─ drag to resize goals ─", id="plan-resizer", markup=False)
            self._on_drag = on_drag
            self._dragging = False

        def _drag_to(self, event: events.MouseEvent) -> None:
            screen_y = getattr(event, "screen_y", self.region.y + event.y)
            self._on_drag(int(screen_y))

        def on_mouse_down(self, event: events.MouseDown) -> None:
            self._dragging = True
            self.capture_mouse()
            self._drag_to(event)
            event.stop()

        def on_mouse_move(self, event: events.MouseMove) -> None:
            if self._dragging:
                self._drag_to(event)
                event.stop()

        def on_mouse_up(self, event: events.MouseUp) -> None:
            if self._dragging:
                self._drag_to(event)
                self._dragging = False
                self.release_mouse()
                event.stop()

    class SelfApp(App[None]):
        CSS = """
        #body { height: 1fr; }
        #coverage { height: 1fr; border: solid $primary; padding: 0 1; scrollbar-gutter: stable; display: none; }
        #coverage-content { width: 100%; }
        #archive { height: 1fr; display: none; }
        #archive-plans-pane { width: 1fr; height: 100%; border: solid $primary; padding: 1; scrollbar-gutter: stable; }
        #archive-goals-pane { width: 1fr; height: 100%; border: solid $secondary; padding: 1; scrollbar-gutter: stable; }
        #archive-plans-content { width: 100%; }
        #archive-goals-content { width: 100%; }
        #conversation-history { height: 1fr; border: solid $primary; padding: 0 1; scrollbar-gutter: stable; display: none; }
        #conversation-history-content { width: 100%; }
        #conversation-pane { width: 2fr; border: solid $primary; }
        #work-pane { width: 1.5fr; border: solid $secondary; }
        #conversation-top { height: 6; }
        #entity-art { width: 7; height: 6; color: $accent; content-align: center middle; text-style: dim; }
        #entity-monitor { width: 1fr; height: 6; color: $text-muted; content-align: left middle; text-style: dim; }
        #entity-monitor.monitor-thinking { color: $accent; }
        #entity-monitor.monitor-working { color: $accent; text-style: bold; }
        #conversation { height: 1fr; padding: 0 1; scrollbar-gutter: stable; }
        #plan { height: 10; min-height: 5; padding: 1; }
        #plan-resizer { height: 1; min-height: 1; max-height: 1; content-align: center middle; color: $text-muted; background: $panel; text-style: dim; }
        #plan-resizer:hover { color: $accent; background: $boost; text-style: bold; }
        #worklog { height: 1fr; min-height: 5; padding: 0 1; scrollbar-gutter: stable; }
        .activity-entry { width: 100%; margin: 0 0 1 0; padding: 0 1; }
        .message { width: 100%; margin: 0 0 1 0; padding: 1; }
        .agent-message { border-left: thick $primary; background: $panel; }
        .reflection-message { border-left: thick $success; background: $boost; }
        .human-message { border-left: thick $accent; background: $boost; }
        .typing-message { border-left: thick $secondary; background: $panel; color: $text-muted; }
        #side { width: 1fr; }
        #identity, #activity, #session, #usage, #container { border: solid $secondary; padding: 1; }
        #identity { height: 0.85fr; }
        #activity { height: 0.85fr; }
        #session { height: 1.25fr; }
        #usage { height: 1.35fr; }
        #container { height: 1.45fr; }
        #chat { dock: bottom; }
        """

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self.voice = VoiceController()
            self.typing_enabled = True
            self.typing_delay = max(0.001, min(float(os.getenv("SELF_TUI_TYPING_DELAY", "0.018")), 0.2))
            self._pending_chat: list[tuple[str, str, str]] = []
            self._pending_activity: list[str] = []
            self._all_chat_messages: list[dict[str, Any]] = []
            self._draining_chat = False
            self._draining_activity = False
            self._agent_running = False
            self._monitor_tick = 0
            self._container_metrics = ContainerMetrics()
            self._coverage_open = False
            self._coverage_generation = 0
            self._archive_open = False
            self._archive_generation = 0
            self._conversation_history_open = False
            self._conversation_page = 0
            self._last_plan_mtime = 0.0
            self._main_scroll_positions: tuple[float, float] | None = None
            self._main_chat_placeholder = "Talk to SELF; /targets /conversation /archive /coverage /restart; /stop pauses safely"

        def compose(self) -> ComposeResult:
            yield Header(show_clock=True)
            with Horizontal(id="body"):
                with Vertical(id="conversation-pane"):
                    with Horizontal(id="conversation-top"):
                        yield Static(" .-.\n(o o)\n /|\\", id="entity-art", markup=False)
                        yield Static(cardiac_monitor_frame(0), id="entity-monitor", markup=False)
                    yield VerticalScroll(id="conversation")
                with Vertical(id="work-pane"):
                    yield Static("Goals loading...", id="plan", markup=True)
                    yield PlanResizeHandle(self._resize_plan)
                    yield VerticalScroll(id="worklog")
                with Vertical(id="side"):
                    yield Static("Identity loading...", id="identity", markup=True)
                    yield Static("Activity loading...", id="activity", markup=True)
                    yield Static("Session loading...", id="session", markup=True)
                    yield Static("Usage loading...", id="usage", markup=True)
                    yield Static("Container loading...", id="container", markup=True)
            with VerticalScroll(id="coverage"):
                yield Static("", id="coverage-content", markup=True)
            with Horizontal(id="archive"):
                with VerticalScroll(id="archive-plans-pane"):
                    yield Static("", id="archive-plans-content", markup=True)
                with VerticalScroll(id="archive-goals-pane"):
                    yield Static("", id="archive-goals-content", markup=True)
            with VerticalScroll(id="conversation-history"):
                yield Static("", id="conversation-history-content", markup=True)
            yield Input(placeholder=self._main_chat_placeholder, id="chat")
            yield Footer()

        def on_mount(self) -> None:
            self.title = f"SELF — {coordinator.identity.display_name()}"
            self._load_conversation_history()
            coordinator.on_activity = lambda message: self.call_from_thread(self._queue_activity, message)
            coordinator.on_chat = lambda message, kind: self.call_from_thread(self._queue_chat, "agent", message, kind)
            self.set_interval(0.5, self._refresh)
            self.set_interval(0.16, self._animate_activity)
            # on_mount can run before descendants have finished attaching.
            # Starting the worker after the first refresh prevents narration
            # from trying to mount conversation bubbles into an unattached
            # VerticalScroll.
            self.call_after_refresh(self._populate_initial_chat)
            self.call_after_refresh(self._start_agent)

        def _start_agent(self) -> bool:
            """Start one wake session, including after a clean session end."""
            if self._agent_running:
                return False
            self._agent_running = True
            self.run_worker(self._run_agent, thread=True)
            return True

        def _resize_plan(self, pointer_screen_y: int) -> None:
            """Resize Plan, leaving the remaining middle-column space to worklog."""
            plan = self.query_one("#plan", Static)
            work_pane = self.query_one("#work-pane", Vertical)
            requested = pointer_screen_y - plan.region.y + PLAN_RESIZER_HEIGHT
            plan.styles.height = clamped_plan_height(requested, work_pane.size.height)

        def _animate_activity(self) -> None:
            self._monitor_tick += 1
            try:
                monitor = self.query_one("#entity-monitor", Static)
            except NoMatches:
                # A timer can tick while Textual is mounting or dismantling the view.
                return
            stopped = coordinator.stop_requested or coordinator.paused.is_set() or (coordinator.workspace / "STOP").exists()
            state = str(coordinator.runtime_snapshot()["state"])
            intensity = cardiac_monitor_intensity(state, stopped=stopped)
            for mode in ("stopped", "thinking", "working", "idle"):
                monitor.set_class(mode == intensity.name, f"monitor-{mode}")
            frame = (self._monitor_tick // intensity.tick_divisor) * intensity.tick_stride
            monitor.update(cardiac_monitor_frame(
                frame,
                monitor.size.width,
                beat_interval=intensity.beat_interval,
                pulse_height=intensity.pulse_height,
            ))
            active = self._agent_running or self._draining_activity or self._draining_chat
            if not active:
                return
            frames = ("[>   ]", "[>>  ]", "[>>> ]", "[ >>>]", "[  >>]", "[   >]")
            self.title = f"SELF — {coordinator.identity.display_name()} {frames[self._monitor_tick % len(frames)]} {state.lower()}"

        def _queue_chat(self, role: str, message: str, kind: str) -> None:
            # A worker can finish concurrently with /stop. Do not enqueue
            # late autonomous output once the stop boundary has been set.
            if role == "agent" and (coordinator.stop_requested or (coordinator.workspace / "STOP").exists()):
                return
            self._pending_chat.append((role, message, kind))
            if not self._draining_chat:
                self._draining_chat = True
                self.run_worker(self._drain_chat(), exclusive=False)

        def _queue_activity(self, message: str) -> None:
            self._pending_activity.append(message)
            if not self._draining_activity:
                self._draining_activity = True
                self.run_worker(self._drain_activity(), exclusive=False)

        def _render_message(self, role: str, message: str, kind: str, *, typing: bool = False) -> Group:
            if role == "human":
                badge, badge_style, label_style = " YOU ", "bold white on dark_orange", "bold #ffbd7a"
            else:
                badge, badge_style, label_style = f" {coordinator.identity.display_name()} ", "bold white on dark_blue", "bold #8ed8ff"
            header = Text()
            header.append(badge, style=badge_style)
            header.append("  " + ("typing..." if typing else kind.title()), style=label_style)
            return Group(header, Markdown(message))

        async def _drain_chat(self) -> None:
            conversation = self.query_one("#conversation", VerticalScroll)
            try:
                while self._pending_chat:
                    role, message, kind = self._pending_chat.pop(0)
                    if role == "agent" and (coordinator.stop_requested or (coordinator.workspace / "STOP").exists()):
                        continue
                    self._record_chat_message(role, message, kind)
                    follow = conversation.scroll_y >= conversation.max_scroll_y - 1
                    message_class = "human" if role == "human" else "reflection" if kind == "reflection" else "agent"
                    bubble = Static(self._render_message(role, "" if role == "agent" and self.typing_enabled else message, kind, typing=role == "agent" and self.typing_enabled), classes=f"message {message_class}-message")
                    await conversation.mount(bubble)
                    while len(conversation.children) > 20:
                        await conversation.children[0].remove()
                    if self._conversation_history_open and self._conversation_page == 0:
                        self._update_conversation_history_content()
                    if follow:
                        conversation.scroll_end(animate=False)
                    if role == "agent" and self.typing_enabled:
                        step = max(1, len(message) // 90)
                        for index in range(step, len(message) + step, step):
                            if coordinator.stop_requested or (coordinator.workspace / "STOP").exists():
                                break
                            visible = message[:index]
                            if len(visible) >= len(message):
                                visible = message
                            bubble.update(self._render_message(role, visible, kind))
                            if follow:
                                conversation.scroll_end(animate=False)
                            if len(visible) < len(message):
                                await asyncio.sleep(self.typing_delay)
                    if role == "agent" and kind in {"conversation", "cycle", "session"}:
                        self.voice.speak(message)
            finally:
                self._draining_chat = False
                if self._pending_chat:
                    self._draining_chat = True
                    self.run_worker(self._drain_chat(), exclusive=False)

        def _record_chat_message(self, role: str, message: str, kind: str) -> None:
            record = {
                "timestamp": now_utc(),
                "role": role,
                "message": message,
                "kind": kind,
            }
            self._all_chat_messages.append(record)
            history_file = coordinator.workspace / "state" / "conversation_history.jsonl"
            try:
                history_file.parent.mkdir(parents=True, exist_ok=True)
                with history_file.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
            except OSError:
                pass

        def _load_conversation_history(self) -> None:
            self._all_chat_messages = []
            history_file = coordinator.workspace / "state" / "conversation_history.jsonl"
            if history_file.exists():
                try:
                    for line in history_file.read_text(encoding="utf-8", errors="replace").splitlines():
                        if not line.strip():
                            continue
                        try:
                            item = json.loads(line)
                            if isinstance(item, dict):
                                self._all_chat_messages.append(item)
                        except json.JSONDecodeError:
                            continue
                except OSError:
                    pass
            if not self._all_chat_messages:
                threads_file = coordinator.workspace / "state" / "conversation_threads.jsonl"
                if threads_file.exists():
                    try:
                        for line in threads_file.read_text(encoding="utf-8", errors="replace").splitlines():
                            if not line.strip():
                                continue
                            try:
                                item = json.loads(line)
                                if isinstance(item, dict):
                                    self._all_chat_messages.append({
                                        "timestamp": item.get("timestamp", ""),
                                        "role": item.get("role", "human"),
                                        "message": item.get("text", ""),
                                        "kind": "chat",
                                    })
                            except json.JSONDecodeError:
                                continue
                    except OSError:
                        pass

        def _populate_initial_chat(self) -> None:
            try:
                conversation = self.query_one("#conversation", VerticalScroll)
            except NoMatches:
                return
            recent = self._all_chat_messages[-20:]
            for item in recent:
                role = str(item.get("role", "agent"))
                msg = str(item.get("message", ""))
                kind = str(item.get("kind", "chat"))
                message_class = "human" if role == "human" else "reflection" if kind == "reflection" else "agent"
                bubble = Static(self._render_message(role, msg, kind, typing=False), classes=f"message {message_class}-message")
                conversation.mount(bubble)
            if recent:
                self.call_after_refresh(lambda: conversation.scroll_end(animate=False))

        async def _drain_activity(self) -> None:
            worklog = self.query_one("#worklog", VerticalScroll)
            try:
                while self._pending_activity:
                    message = self._pending_activity.pop(0)
                    follow = worklog.scroll_y >= worklog.max_scroll_y - 1
                    # Textual 0.89 still parses a string Static as Rich markup
                    # when rendering, even when ``markup=False`` was supplied.
                    # Activity comes from LLM and tool output, so escape it at
                    # the rendering boundary to keep every literal "[" safe.
                    await worklog.mount(Static(escape_rich_markup(message), classes="activity-entry", markup=True))
                    if follow:
                        # Mounting changes the content height asynchronously. Scroll
                        # after Textual lays out the new entry, otherwise max_scroll_y
                        # still describes the previous bottom and follow mode drifts.
                        self.call_after_refresh(lambda: worklog.scroll_end(animate=False))
            finally:
                self._draining_activity = False
                if self._pending_activity:
                    self._draining_activity = True
                    self.run_worker(self._drain_activity(), exclusive=False)

        def _write_command(self, message: str) -> None:
            self._queue_activity(f"human command: {message}")

        def _open_coverage(self) -> None:
            if not self._coverage_open and not self._archive_open and not self._conversation_history_open:
                self._main_scroll_positions = (
                    self.query_one("#conversation", VerticalScroll).scroll_y,
                    self.query_one("#worklog", VerticalScroll).scroll_y,
                )
            if self._archive_open:
                self._archive_open = False
                self.query_one("#archive", Horizontal).styles.display = "none"
            if self._conversation_history_open:
                self._conversation_history_open = False
                self.query_one("#conversation-history", VerticalScroll).styles.display = "none"
            self._coverage_open = True
            self._coverage_generation += 1
            generation = self._coverage_generation
            self.query_one("#body", Horizontal).styles.display = "none"
            self.query_one("#coverage", VerticalScroll).styles.display = "block"
            self.query_one("#coverage-content", Static).update("[b]Exploration coverage[/b]\nLoading recorded activity...")
            self.query_one("#coverage", VerticalScroll).scroll_home(animate=False)
            self.query_one("#chat", Input).placeholder = "Coverage: /back to main UI; /coverage to refresh"
            self.run_worker(lambda: self._load_coverage(generation), thread=True, exclusive=False)

        def _load_coverage(self, generation: int) -> None:
            try:
                summary = build_coverage(coordinator.workspace, {definition["name"] for definition in TOOL_DEFINITIONS})
            except OSError as exc:
                self.call_from_thread(self._coverage_error, generation, type(exc).__name__)
                return
            self.call_from_thread(self._show_coverage, generation, summary)

        def _coverage_error(self, generation: int, error: str) -> None:
            if self._coverage_open and generation == self._coverage_generation:
                self.query_one("#coverage-content", Static).update(
                    "[b]Exploration coverage[/b]\nCould not read coverage: " + escape_rich_markup(error)
                )

        def _show_coverage(self, generation: int, summary: CoverageSummary) -> None:
            if not self._coverage_open or generation != self._coverage_generation:
                return
            lines = [
                "[b]Exploration coverage[/b]",
                f"Directories explored: {len(summary.directories)}  |  Visits: {summary.total_visits}  |  Created tools: {len(summary.tools)}",
                "Visits count successful directory listings and file reads in that directory across all sessions.",
                "Shell commands are excluded. Type /back to return or /coverage to refresh.",
                "",
                "[b]Directories[/b]",
            ]
            lines.extend(
                f"{count:>5}  {escape_rich_markup(path)}"
                for path, count in summary.directories
            )
            if not summary.directories:
                lines.append("No recorded directory visits yet.")
            lines.extend(("", "[b]Created tools[/b]"))
            lines.extend(
                f"[b]{escape_rich_markup(name)}[/b] — "
                f"{escape_rich_markup(description[:180] + ('…' if len(description) > 180 else ''))}"
                for name, description in summary.tools
            )
            if not summary.tools:
                lines.append("No registered custom tools yet.")
            self.query_one("#coverage-content", Static).update("\n".join(lines))

        def _back_from_coverage(self) -> None:
            self._coverage_open = False
            self._coverage_generation += 1
            self.query_one("#coverage", VerticalScroll).styles.display = "none"
            self.query_one("#body", Horizontal).styles.display = "block"
            self.query_one("#chat", Input).placeholder = self._main_chat_placeholder
            positions = self._main_scroll_positions
            self._main_scroll_positions = None
            if positions is not None:
                self.call_after_refresh(lambda: self._restore_main_scroll(positions))

        def _open_archive(self) -> None:
            if not self._coverage_open and not self._archive_open and not self._conversation_history_open:
                self._main_scroll_positions = (
                    self.query_one("#conversation", VerticalScroll).scroll_y,
                    self.query_one("#worklog", VerticalScroll).scroll_y,
                )
            if self._coverage_open:
                self._coverage_open = False
                self.query_one("#coverage", VerticalScroll).styles.display = "none"
            if self._conversation_history_open:
                self._conversation_history_open = False
                self.query_one("#conversation-history", VerticalScroll).styles.display = "none"
            self._archive_open = True
            self._archive_generation += 1
            generation = self._archive_generation
            self.query_one("#body", Horizontal).styles.display = "none"
            self.query_one("#archive", Horizontal).styles.display = "block"
            self.query_one("#archive-plans-content", Static).update("[b]Session Plans[/b]\nLoading recorded session plans...")
            self.query_one("#archive-goals-content", Static).update("[b]Achieved Goals[/b]\nLoading achieved goals...")
            self.query_one("#archive-plans-pane", VerticalScroll).scroll_home(animate=False)
            self.query_one("#archive-goals-pane", VerticalScroll).scroll_home(animate=False)
            self.query_one("#chat", Input).placeholder = "Archive: /back to main UI; /archive to refresh"
            self.run_worker(lambda: self._load_archive(generation), thread=True, exclusive=False)

        def _load_archive(self, generation: int) -> None:
            try:
                plans_text, goals_text = build_archive_views(coordinator.workspace, coordinator)
            except OSError as exc:
                self.call_from_thread(self._archive_error, generation, type(exc).__name__)
                return
            except Exception as exc:
                self.call_from_thread(self._archive_error, generation, str(exc))
                return
            self.call_from_thread(self._show_archive, generation, plans_text, goals_text)

        def _archive_error(self, generation: int, error: str) -> None:
            if self._archive_open and generation == self._archive_generation:
                msg = "[b]Archive Error[/b]\nCould not load archive: " + escape_rich_markup(error)
                self.query_one("#archive-plans-content", Static).update(msg)
                self.query_one("#archive-goals-content", Static).update(msg)

        def _show_archive(self, generation: int, plans_text: str, goals_text: str) -> None:
            if not self._archive_open or generation != self._archive_generation:
                return
            self.query_one("#archive-plans-content", Static).update(plans_text)
            self.query_one("#archive-goals-content", Static).update(goals_text)

        def _back_from_archive(self) -> None:
            self._archive_open = False
            self._archive_generation += 1
            self.query_one("#archive", Horizontal).styles.display = "none"
            self.query_one("#body", Horizontal).styles.display = "block"
            self.query_one("#chat", Input).placeholder = self._main_chat_placeholder
            positions = self._main_scroll_positions
            self._main_scroll_positions = None
            if positions is not None:
                self.call_after_refresh(lambda: self._restore_main_scroll(positions))

        def _open_conversation_history(self, page: int = 0) -> None:
            if not self._coverage_open and not self._archive_open and not self._conversation_history_open:
                self._main_scroll_positions = (
                    self.query_one("#conversation", VerticalScroll).scroll_y,
                    self.query_one("#worklog", VerticalScroll).scroll_y,
                )
            if self._coverage_open:
                self._coverage_open = False
                self.query_one("#coverage", VerticalScroll).styles.display = "none"
            if self._archive_open:
                self._archive_open = False
                self.query_one("#archive", Horizontal).styles.display = "none"
            self._conversation_history_open = True
            total = len(self._all_chat_messages)
            max_pages = max(1, (total + 19) // 20)
            self._conversation_page = max(0, min(page, max_pages - 1))
            self.query_one("#body", Horizontal).styles.display = "none"
            self.query_one("#conversation-history", VerticalScroll).styles.display = "block"
            self.query_one("#chat", Input).placeholder = "Conversation: /previous for older messages; /back to return; /conversation to refresh"
            self._update_conversation_history_content()

        def _update_conversation_history_content(self) -> None:
            text = format_conversation_history_view(
                self._all_chat_messages,
                page=self._conversation_page,
                page_size=20,
                entity_name=coordinator.identity.display_name(),
            )
            self.query_one("#conversation-history-content", Static).update(text)
            self.query_one("#conversation-history", VerticalScroll).scroll_home(animate=False)

        def _back_from_conversation_history(self) -> None:
            self._conversation_history_open = False
            self.query_one("#conversation-history", VerticalScroll).styles.display = "none"
            self.query_one("#body", Horizontal).styles.display = "block"
            self.query_one("#chat", Input).placeholder = self._main_chat_placeholder
            positions = self._main_scroll_positions
            self._main_scroll_positions = None
            if positions is not None:
                self.call_after_refresh(lambda: self._restore_main_scroll(positions))

        def _restore_main_scroll(self, positions: tuple[float, float]) -> None:
            self.query_one("#conversation", VerticalScroll).scroll_to(y=positions[0], animate=False)
            self.query_one("#worklog", VerticalScroll).scroll_to(y=positions[1], animate=False)

        def _voice_status(self, message: str | None = None) -> None:
            self._queue_activity(message or self.voice.status_text())

        def _command_response(self, message: str, kind: str = "info") -> None:
            self._queue_activity(f"[{kind}] {message}")

        def _conversation_result(self, thread_id: str, message: str, kind: str) -> None:
            if coordinator.stop_requested or (coordinator.workspace / "STOP").exists():
                return
            self.call_from_thread(self._queue_chat, "agent", message, "conversation" if kind == "assistant" else "error")

        def _ordinary_human_message(self, text: str) -> None:
            """Route the next ordinary response to an open reflection first."""
            self._queue_chat("human", text, "human")
            reply = coordinator.accept_reflection_reply(text)
            if reply is not None:
                self._command_response("Reflection reply saved; I will use it at the next safe work step.", "request")
                return
            coordinator.receive_human_input(f"Human said: {text}", kind="chat")
            self._command_response("Conversation thread started; autonomous work continues separately.")
            coordinator.start_conversation(text, self._conversation_result)

        def _watch_human_request(self) -> None:
            if (coordinator.workspace / "STOP").exists():
                return
            if (coordinator.workspace / "HUMAN_REQUEST.md").exists():
                self.set_timer(2.0, self._watch_human_request)
            else:
                self._start_agent()

        def _finish_agent_turn(self, final_message: str | None, restart_delay: float | None) -> None:
            if final_message:
                self._command_response(final_message, "request" if any(word in final_message.lower() for word in ("paused", "waiting", "human action")) else "session")
            if (coordinator.workspace / "STOP").exists():
                return
            if (coordinator.workspace / "HUMAN_REQUEST.md").exists():
                self.set_timer(2.0, self._watch_human_request)
            else:
                self.set_timer(restart_delay if restart_delay is not None else 0.8, self._start_agent)

        def _run_agent(self) -> None:
            final_message: str | None = None
            restart_delay: float | None = None
            try:
                result = coordinator.run()
                if not (result is None and (coordinator.workspace / "STOP").exists()):
                    if (coordinator.workspace / "STOP").exists():
                        final_message = "I am paused because STOP was requested. Remove workspace/STOP or use /restart when you want me to continue."
                    elif (coordinator.workspace / "HUMAN_REQUEST.md").exists():
                        final_message = "I am waiting for your decision in HUMAN_REQUEST.md. Resolve it and remove the file; I will wake automatically."
                    else:
                        final_message = "This session ended; I will start the next session automatically."
                        restart_delay = 0.8 if result is None or getattr(result, "reason", "") != "provider_error" else 3.0
            except Exception as exc:
                coordinator.logger.narrate(f"Wake coordinator failed: {type(exc).__name__}")
                final_message = f"This session failed with {type(exc).__name__}; I will retry automatically unless you stop me."
                restart_delay = 3.0
            finally:
                self._agent_running = False
                self.call_from_thread(self._finish_agent_turn, final_message, restart_delay)

        def _refresh(self) -> None:
            telemetry = coordinator.runtime_snapshot()
            active_client = coordinator._llm
            active_provider = getattr(active_client, "provider", coordinator.status.active_provider)
            active_model = getattr(active_client, "model", coordinator.status.active_model)
            ai_counts = telemetry["calls_by_ai"]
            calls = "\n".join(
                f"{escape_rich_markup(name)}: {escape_rich_markup(count)}"
                for name, count in sorted(ai_counts.items())
            ) or "No AI calls yet"
            registered_models = coordinator.models_snapshot().get("registry", {}).get("models", [])
            model_calls = "\n".join(
                f"{escape_rich_markup(entry.get('name', 'unknown'))}: "
                f"{escape_rich_markup((entry.get('measured_stats') or {}).get('calls', 0))}"
                for entry in registered_models
            ) or "No model data yet"
            try:
                plan_file = coordinator.workspace / "state" / "plan.json"
                if plan_file.exists():
                    mtime = plan_file.stat().st_mtime
                    if mtime != self._last_plan_mtime:
                        self._last_plan_mtime = mtime
                        coordinator.plan_store.load()
                        with coordinator.lock:
                            coordinator.plan = list(coordinator.plan_store.items)
            except OSError:
                pass

            goals_list = coordinator.plan_store.items or coordinator.plan
            current_activity = " ".join(str(telemetry.get("current_activity", "")).split())[:220]
            current_cycle = coordinator.status.iteration or 1
            plan_panel = format_goals_panel(goals_list, current_activity=current_activity, current_cycle=current_cycle)
            uptime = int(time.monotonic() - coordinator.status.started_monotonic)
            since_human = int(time.monotonic() - coordinator.status.last_human_input)
            run_tokens = telemetry["run_tokens_used"] or coordinator.status.tokens_used
            run_budget = telemetry["run_budget"] or coordinator.daily_ledger.cap
            budget_label = "daily-only" if coordinator.token_budget is None else str(run_budget)
            daily_remaining = max(0, telemetry["daily_cap"] - telemetry["daily_used"] - telemetry["daily_reserved"]) if telemetry["daily_cap"] else "unknown"
            identity = coordinator.identity.load()
            identity_panel = (
                "[b]Identity[/b]\n"
                f"Agent: {escape_rich_markup(identity.get('name') or 'unnamed')}\n"
                f"Human: {escape_rich_markup(identity.get('human_name') or 'not yet known')}"
            )
            activity_panel = (
                "[b]Activity[/b]\n"
                f"Presence: {escape_rich_markup(telemetry['state'])}\n"
                f"AI: {escape_rich_markup(telemetry['current_ai'])}"
            )
            session_panel = (
                "[b]Session[/b]\n"
                f"ID: {escape_rich_markup(coordinator.status.session_id[:12] or 'starting')}\n"
                f"Iteration: {escape_rich_markup(coordinator.status.iteration)}\n"
                f"Model: {escape_rich_markup(active_provider)}/{escape_rich_markup(active_model)}\n"
                f"Tools: {len(coordinator._tool_list())}\n"
                f"Uptime: {uptime}s\n"
                f"Since human input: {since_human}s"
            )
            usage_panel = (
                "[b]Usage[/b]\n"
                f"Tokens: {run_tokens} ({budget_label})\n"
                f"Calls: {telemetry['total_calls']} total | {telemetry['completed_calls']} completed | {telemetry['failed_calls']} failed\n"
                f"Daily tokens: {telemetry['daily_used']}/{telemetry['daily_cap'] or '?'} (remaining {daily_remaining})\n"
                f"AI call counts this session:\n{calls}\n"
                f"Per-model calls recorded:\n{model_calls}"
            )
            if telemetry["daily_blocked"]:
                usage_panel += "\n\nACTION NEEDED: daily limit reached; see HUMAN_REQUEST.md"
            metrics = self._container_metrics.snapshot()
            container_panel = (
                "[b]Container[/b]\n"
                f"CPU: {escape_rich_markup(metrics['cpu'])}\n"
                f"RAM: {escape_rich_markup(metrics['ram'])}\n"
                f"Network: {escape_rich_markup(metrics['network'])}\n"
                f"Disk read: {escape_rich_markup(metrics['disk_read'])}"
            )
            self.query_one("#identity", Static).update(identity_panel)
            self.query_one("#activity", Static).update(activity_panel)
            self.query_one("#plan", Static).update(plan_panel)
            self.query_one("#session", Static).update(session_panel)
            self.query_one("#usage", Static).update(usage_panel)
            self.query_one("#container", Static).update(container_panel)

        def on_input_submitted(self, event: Input.Submitted) -> None:
            text = event.value.strip()
            event.input.value = ""
            if not text:
                return
            if text == "/coverage":
                self._write_command(text)
                self._open_coverage()
                return
            if text == "/archive":
                self._write_command(text)
                self._open_archive()
                return
            if text == "/conversation":
                self._write_command(text)
                self._open_conversation_history(page=0)
                return
            if text == "/previous":
                self._write_command(text)
                if self._conversation_history_open:
                    total = len(self._all_chat_messages)
                    max_pages = max(1, (total + 19) // 20)
                    if self._conversation_page + 1 < max_pages:
                        self._conversation_page += 1
                        self._update_conversation_history_content()
                        self._command_response(f"Showing older messages (Page {self._conversation_page + 1} of {max_pages}).", "conversation")
                    else:
                        self._command_response("Already at the oldest recorded messages.", "conversation")
                else:
                    self._open_conversation_history(page=1 if len(self._all_chat_messages) > 20 else 0)
                return
            if text == "/next":
                self._write_command(text)
                if self._conversation_history_open:
                    if self._conversation_page > 0:
                        self._conversation_page -= 1
                        self._update_conversation_history_content()
                        total = len(self._all_chat_messages)
                        max_pages = max(1, (total + 19) // 20)
                        self._command_response(f"Showing newer messages (Page {self._conversation_page + 1} of {max_pages}).", "conversation")
                    else:
                        self._command_response("Already showing the newest messages.", "conversation")
                return
            if text == "/back" and (self._coverage_open or self._archive_open or self._conversation_history_open):
                self._write_command(text)
                if self._coverage_open:
                    self._back_from_coverage()
                if self._archive_open:
                    self._back_from_archive()
                if self._conversation_history_open:
                    self._back_from_conversation_history()
                return
            if text == "/voice":
                self._write_command(text); self._voice_status(); return
            if text in {"/voice on", "/voice off"}:
                self._write_command(text); self._voice_status(self.voice.set_enabled(text.endswith(" on"))); return
            if text == "/typing":
                self._write_command(text); self._command_response(f"Typing effect {'enabled' if self.typing_enabled else 'disabled'}."); return
            if text in {"/typing on", "/typing off"}:
                self._write_command(text); self.typing_enabled = text.endswith(" on"); self._command_response(f"Typing effect {'enabled' if self.typing_enabled else 'disabled'}."); return
            if text == "/listen":
                self._write_command(text)
                self._command_response("Listening for one microphone phrase...", "request")
                self.run_worker(self._listen_for_human, thread=True)
                return
            if text == "/restart":
                self._write_command(text)
                if self._agent_running:
                    self._command_response("I am already running; use /stop first if you want a fresh session.")
                    return
                stop_path = coordinator.workspace / "STOP"
                try:
                    if stop_path.exists():
                        stop_path.unlink()
                    request_path = coordinator.workspace / "HUMAN_REQUEST.md"
                    if request_path.exists():
                        request_text = request_path.read_text(encoding="utf-8", errors="replace").lower()
                        if "daily token-budget decision" in request_text:
                            request_path.unlink()
                            self._command_response("I cleared the previous token-budget request; the new daily limit will be used for this run.")
                except OSError as exc:
                    self._command_response(f"I could not remove STOP: {type(exc).__name__}.", "error")
                    return
                coordinator.stop_requested = False
                coordinator.resume()
                self._command_response("I removed the previous stop request and am waking now.", "request")
                self._start_agent()
                return
            if text == "/pause":
                self._write_command(text)
                coordinator.pause(); self._command_response("Paused. I will stop at the next safe boundary."); return
            if text == "/resume":
                self._write_command(text)
                coordinator.resume(); self._command_response("Resuming."); return
            if text == "/stop":
                self._write_command(text)
                # Drop agent messages queued before the stop command. The
                # currently rendered bubble is also interrupted by the
                # stop-aware typing loop above.
                self._pending_chat.clear()
                coordinator.request_stop("ui_stop"); self._command_response("Stop requested; finishing the current safe action.", "request"); return
            if text in {"/targets", "/plan"}:
                self._write_command(text)
                rendered = coordinator.render_starting_plan()
                self._queue_chat("agent", rendered, "targets")
                self._command_response("Starting targets displayed in conversation.", "targets")
                return
            if text == "/goals":
                self._write_command(text)
                coordinator.plan_store.load()
                current_goals = coordinator.plan_store.items or coordinator.plan
                self._command_response(json.dumps(current_goals, ensure_ascii=False, indent=2)); return
            if text == "/models":
                self._write_command(text)
                self._command_response(format_models_snapshot(coordinator.models_snapshot())); return
            if text == "/identity":
                self._write_command(text)
                self._command_response(json.dumps(coordinator.identity.load(), ensure_ascii=False, indent=2)); return
            if text.startswith("/rename "):
                self._write_command(text)
                try:
                    identity = coordinator.identity.set_name(text[8:].strip(), coordinator.status.session_id, named_by="human")
                    self.title = f"SELF — {identity.get('name')}"
                    context = identity.get("name_context") or {}
                    context_label = context.get("meaning", "no verified meaning found")
                    if context.get("kind") == "fictional_character":
                        context_label = (
                            f"{context.get('character', identity.get('name'))} from "
                            f"{context.get('franchise', 'a fictional story')} — {context.get('role', context_label)}"
                        )
                    self._command_response(
                        f"Name saved as {identity.get('name')}. "
                        f"Context: {context_label}. "
                        f"Style cue: {context.get('style_cue', 'use observed behavior and the stored voice.')}"
                    )
                except ValueError as exc:
                    self._command_response(f"Could not rename: {exc}", "error")
                return
            if text == "/name":
                self._write_command(text)
                current = coordinator.identity.human_name()
                self._command_response(f"I currently know your name as {current}." if current else "I do not know your name yet. Use `/name <your name>`.")
                return
            if text.startswith("/name "):
                self._write_command(text)
                try:
                    saved = coordinator.identity.set_human_name(text[6:].strip(), coordinator.status.session_id)
                    self._command_response(f"Thank you, {saved}. I saved your name for future conversations.")
                except ValueError as exc:
                    self._command_response(f"Could not save your name: {exc}", "error")
                return
            if text == "/self":
                self._write_command(text)
                try:
                    content = (coordinator.workspace / "state" / "self_inquiry.md").read_text(encoding="utf-8", errors="replace")
                except OSError:
                    content = "No self inquiry exists yet; it is written during first awakening."
                self._command_response(content[-6_000:]); return
            if text == "/patches":
                self._write_command(text)
                patches = coordinator.identity.proposed_patches()
                message = "\n".join(str(path) for path in patches[:20]) if patches else "No proposed core patches are waiting for review."
                self._command_response(message, "request"); return
            if text.startswith("/about me delete "):
                self._write_command(text)
                try:
                    line_number = int(text.removeprefix("/about me delete ").strip())
                    self._command_response(coordinator.identity.delete_human_line(line_number, coordinator.status.session_id))
                except (ValueError, FileNotFoundError) as exc:
                    self._command_response(f"Could not delete stored line: {exc}", "error")
                return
            if text == "/about me":
                self._write_command(text)
                content = coordinator.identity.about_human_text()
                numbered = "\n".join(f"{index}: {line}" for index, line in enumerate(content.splitlines(), start=1))
                self._command_response(numbered or "No volunteered information is stored about you."); return
            if text == "/journal":
                self._write_command(text)
                try: self._command_response((coordinator.workspace / "state" / "journal.md").read_text(encoding="utf-8")[-3_000:])
                except OSError: self._command_response("No journal entry exists yet.")
                return
            if text == "/tools": self._write_command(text); self._command_response(", ".join(coordinator._tool_list()) or "No custom tools registered."); return
            if text.startswith("/plugins"):
                self._write_command(text)
                self._command_response(coordinator.handle_plugins_command(text), "input")
                return
            if text in {"/requests", "/inputs"}: self._write_command(text); self._command_response(_requests_text(coordinator.workspace), "input"); return
            if text.startswith("/memory "):
                self._write_command(text)
                self._command_response(coordinator.learning.retrieve_memories(text[8:])); return
            if text == "/budget":
                self._write_command(text)
                self._command_response(json.dumps(coordinator.daily_ledger._read())); return
            if text in {"/decisions", "/decisions "}:
                self._write_command(text)
                self._command_response(coordinator.recent_decisions(), "input")
                return
            if text.startswith("/goal "):
                self._write_command(text)
                coordinator.receive_human_input("Human input to consider: " + text[6:], kind="goal")
                self._command_response("Human input queued to consider for the next cycle.", "input")
                if not self._agent_running:
                    self._command_response("The previous session had ended, so I am waking to work on it now.", "input")
                    self._start_agent()
                return
            # An open reflection receives the next ordinary human message;
            # otherwise ordinary chat remains separate from autonomous input.
            self._ordinary_human_message(text)

        def _listen_for_human(self) -> None:
            text, error = self.voice.listen()
            if error:
                self.call_from_thread(self._command_response, error, "error")
                return
            if text:
                self.call_from_thread(self._ordinary_human_message, text)

    SelfApp().run()
    return 0


def main() -> int:
    """Parse command-line arguments and run this module's entry point."""
    parser = argparse.ArgumentParser(description="Wake SELF with a persistent session and optional terminal UI.")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--workspace", default="/home/entity")
    parser.add_argument("--max-iterations", type=int)
    parser.add_argument("--token-budget", type=int)
    parser.add_argument("--max-wall-clock-seconds", type=int)
    args = parser.parse_args()
    coordinator = WakeCoordinator(args.workspace, max_iterations=args.max_iterations, token_budget=args.token_budget, max_wall_clock_seconds=args.max_wall_clock_seconds)
    def stop_signal(*_: Any) -> None:
        coordinator.stop_requested = True
        (coordinator.workspace / "STOP").touch()
    signal.signal(signal.SIGTERM, stop_signal)
    signal.signal(signal.SIGINT, stop_signal)
    return run_headless(coordinator) if args.headless else run_tui(coordinator)


if __name__ == "__main__":
    raise SystemExit(main())
