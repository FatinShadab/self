"""Full-screen exploration coverage view controller."""
from __future__ import annotations

from typing import Any

from agent.learning.exploration_coverage import CoverageSummary, build_coverage
from agent.tools.base_tools import TOOL_DEFINITIONS
from agent.ui.formatting.rich_markup import escape_rich_markup
from agent.ui.tui.views.base import restore_main_scroll, save_main_scroll_positions


def open_coverage(app: Any, coordinator: Any) -> None:
    """Open the exploration coverage overlay view."""
    try:
        from textual.containers import Horizontal, VerticalScroll
        from textual.widgets import Input, Static
    except ImportError:
        return

    save_main_scroll_positions(app)
    if getattr(app, "_archive_open", False):
        app._archive_open = False
        app.query_one("#archive", Horizontal).styles.display = "none"
    if getattr(app, "_conversation_history_open", False):
        app._conversation_history_open = False
        app.query_one("#conversation-history", VerticalScroll).styles.display = "none"

    app._coverage_open = True
    app._coverage_generation += 1
    generation = app._coverage_generation
    app.query_one("#body", Horizontal).styles.display = "none"
    app.query_one("#coverage", VerticalScroll).styles.display = "block"
    app.query_one("#coverage-content", Static).update("[b]Exploration coverage[/b]\nLoading recorded activity...")
    app.query_one("#coverage", VerticalScroll).scroll_home(animate=False)
    app.query_one("#chat", Input).placeholder = "Coverage: /back to main UI; /coverage to refresh"
    app.run_worker(lambda: load_coverage(app, coordinator, generation), thread=True, exclusive=False)


def load_coverage(app: Any, coordinator: Any, generation: int) -> None:
    """Background worker to compute exploration coverage metrics."""
    try:
        summary = build_coverage(coordinator.workspace, {definition["name"] for definition in TOOL_DEFINITIONS})
    except OSError as exc:
        app.call_from_thread(coverage_error, app, generation, type(exc).__name__)
        return
    app.call_from_thread(show_coverage, app, generation, summary)


def coverage_error(app: Any, generation: int, error: str) -> None:
    """Display an error in the coverage content pane."""
    try:
        from textual.widgets import Static
    except ImportError:
        return
    if getattr(app, "_coverage_open", False) and generation == app._coverage_generation:
        app.query_one("#coverage-content", Static).update(
            "[b]Exploration coverage[/b]\nCould not read coverage: " + escape_rich_markup(error)
        )


def show_coverage(app: Any, generation: int, summary: CoverageSummary) -> None:
    """Render formatted coverage statistics in the coverage content pane."""
    try:
        from textual.widgets import Static
    except ImportError:
        return
    if not getattr(app, "_coverage_open", False) or generation != app._coverage_generation:
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
    app.query_one("#coverage-content", Static).update("\n".join(lines))


def back_from_coverage(app: Any) -> None:
    """Close the coverage overlay view and restore main layout."""
    try:
        from textual.containers import Horizontal, VerticalScroll
        from textual.widgets import Input
    except ImportError:
        return
    app._coverage_open = False
    app._coverage_generation += 1
    app.query_one("#coverage", VerticalScroll).styles.display = "none"
    app.query_one("#body", Horizontal).styles.display = "block"
    app.query_one("#chat", Input).placeholder = app._main_chat_placeholder
    positions = app._main_scroll_positions
    app._main_scroll_positions = None
    if positions is not None:
        app.call_after_refresh(lambda: restore_main_scroll(app, positions))


__all__ = [
    "open_coverage",
    "load_coverage",
    "coverage_error",
    "show_coverage",
    "back_from_coverage",
]
