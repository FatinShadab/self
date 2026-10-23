"""Base interface and scroll helpers for full-screen TUI views."""
from __future__ import annotations

from typing import Any, Protocol


def save_main_scroll_positions(app: Any) -> None:
    """Save main conversation and worklog scroll positions before opening a full-screen view."""
    try:
        from textual.containers import VerticalScroll
    except ImportError:
        return
    if (
        not getattr(app, "_coverage_open", False)
        and not getattr(app, "_archive_open", False)
        and not getattr(app, "_conversation_history_open", False)
    ):
        app._main_scroll_positions = (
            app.query_one("#conversation", VerticalScroll).scroll_y,
            app.query_one("#worklog", VerticalScroll).scroll_y,
        )


def restore_main_scroll(app: Any, positions: tuple[float, float]) -> None:
    """Restore main conversation and worklog scroll positions after closing a full-screen view."""
    try:
        from textual.containers import VerticalScroll
    except ImportError:
        return
    app.query_one("#conversation", VerticalScroll).scroll_to(y=positions[0], animate=False)
    app.query_one("#worklog", VerticalScroll).scroll_to(y=positions[1], animate=False)


class FullScreenView(Protocol):
    """Protocol for full-screen overlay views (Coverage, Archive, Conversation History)."""

    def is_open(self, app: Any) -> bool: ...
    def open(self, app: Any) -> None: ...
    def back(self, app: Any) -> None: ...


__all__ = [
    "save_main_scroll_positions",
    "restore_main_scroll",
    "FullScreenView",
]
