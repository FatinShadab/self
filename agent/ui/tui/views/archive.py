"""Full-screen two-column session archive and achieved goals view controller."""
from __future__ import annotations

from typing import Any

from agent.ui.formatting.archive_view import build_archive_views
from agent.ui.formatting.rich_markup import escape_rich_markup
from agent.ui.tui.views.base import restore_main_scroll, save_main_scroll_positions


def open_archive(app: Any, coordinator: Any) -> None:
    """Open the archive two-column overlay view."""
    try:
        from textual.containers import Horizontal, VerticalScroll
        from textual.widgets import Input, Static
    except ImportError:
        return

    save_main_scroll_positions(app)
    if getattr(app, "_coverage_open", False):
        app._coverage_open = False
        app.query_one("#coverage", VerticalScroll).styles.display = "none"
    if getattr(app, "_conversation_history_open", False):
        app._conversation_history_open = False
        app.query_one("#conversation-history", VerticalScroll).styles.display = "none"

    app._archive_open = True
    app._archive_generation += 1
    generation = app._archive_generation
    app.query_one("#body", Horizontal).styles.display = "none"
    app.query_one("#archive", Horizontal).styles.display = "block"
    app.query_one("#archive-plans-content", Static).update("[b]Session Plans[/b]\nLoading recorded session plans...")
    app.query_one("#archive-goals-content", Static).update("[b]Achieved Goals[/b]\nLoading achieved goals...")
    app.query_one("#archive-plans-pane", VerticalScroll).scroll_home(animate=False)
    app.query_one("#archive-goals-pane", VerticalScroll).scroll_home(animate=False)
    app.query_one("#chat", Input).placeholder = "Archive: /back to main UI; /archive to refresh"
    app.run_worker(lambda: load_archive(app, coordinator, generation), thread=True, exclusive=False)


def load_archive(app: Any, coordinator: Any, generation: int) -> None:
    """Background worker to format session plans and achieved goals."""
    try:
        plans_text, goals_text = build_archive_views(coordinator.workspace, coordinator)
    except OSError as exc:
        app.call_from_thread(archive_error, app, generation, type(exc).__name__)
        return
    except Exception as exc:
        app.call_from_thread(archive_error, app, generation, str(exc))
        return
    app.call_from_thread(show_archive, app, generation, plans_text, goals_text)


def archive_error(app: Any, generation: int, error: str) -> None:
    """Display an error message in both archive panes."""
    try:
        from textual.widgets import Static
    except ImportError:
        return
    if getattr(app, "_archive_open", False) and generation == app._archive_generation:
        msg = "[b]Archive Error[/b]\nCould not load archive: " + escape_rich_markup(error)
        app.query_one("#archive-plans-content", Static).update(msg)
        app.query_one("#archive-goals-content", Static).update(msg)


def show_archive(app: Any, generation: int, plans_text: str, goals_text: str) -> None:
    """Render formatted archive content into the plans and goals panes."""
    try:
        from textual.widgets import Static
    except ImportError:
        return
    if not getattr(app, "_archive_open", False) or generation != app._archive_generation:
        return
    app.query_one("#archive-plans-content", Static).update(plans_text)
    app.query_one("#archive-goals-content", Static).update(goals_text)


def back_from_archive(app: Any) -> None:
    """Close the archive overlay view and restore main layout."""
    try:
        from textual.containers import Horizontal
        from textual.widgets import Input
    except ImportError:
        return
    app._archive_open = False
    app._archive_generation += 1
    app.query_one("#archive", Horizontal).styles.display = "none"
    app.query_one("#body", Horizontal).styles.display = "block"
    app.query_one("#chat", Input).placeholder = app._main_chat_placeholder
    positions = app._main_scroll_positions
    app._main_scroll_positions = None
    if positions is not None:
        app.call_after_refresh(lambda: restore_main_scroll(app, positions))


__all__ = [
    "open_archive",
    "load_archive",
    "archive_error",
    "show_archive",
    "back_from_archive",
]
