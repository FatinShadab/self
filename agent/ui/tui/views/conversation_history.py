"""Full-screen paginated conversation history view controller."""
from __future__ import annotations

from typing import Any

from agent.ui.formatting.conversation_view import format_conversation_history_view
from agent.ui.tui.views.base import restore_main_scroll, save_main_scroll_positions


def open_conversation_history(app: Any, coordinator: Any, page: int = 0) -> None:
    """Open the paginated conversation history overlay view."""
    try:
        from textual.containers import Horizontal, VerticalScroll
        from textual.widgets import Input
    except ImportError:
        return

    save_main_scroll_positions(app)
    if getattr(app, "_coverage_open", False):
        app._coverage_open = False
        app.query_one("#coverage", VerticalScroll).styles.display = "none"
    if getattr(app, "_archive_open", False):
        app._archive_open = False
        app.query_one("#archive", Horizontal).styles.display = "none"

    app._conversation_history_open = True
    total = len(app._all_chat_messages)
    max_pages = max(1, (total + 19) // 20)
    app._conversation_page = max(0, min(page, max_pages - 1))
    app.query_one("#body", Horizontal).styles.display = "none"
    app.query_one("#conversation-history", VerticalScroll).styles.display = "block"
    app.query_one("#chat", Input).placeholder = (
        "Conversation: /previous for older messages; /back to return; /conversation to refresh"
    )
    update_conversation_history_content(app, coordinator)


def update_conversation_history_content(app: Any, coordinator: Any) -> None:
    """Render the current page of conversation messages."""
    try:
        from textual.containers import VerticalScroll
        from textual.widgets import Static
    except ImportError:
        return

    text = format_conversation_history_view(
        app._all_chat_messages,
        page=app._conversation_page,
        page_size=20,
        entity_name=coordinator.identity.display_name(),
    )
    app.query_one("#conversation-history-content", Static).update(text)
    app.query_one("#conversation-history", VerticalScroll).scroll_home(animate=False)


def back_from_conversation_history(app: Any) -> None:
    """Close the conversation history overlay view and restore main layout."""
    try:
        from textual.containers import Horizontal, VerticalScroll
        from textual.widgets import Input
    except ImportError:
        return
    app._conversation_history_open = False
    app.query_one("#conversation-history", VerticalScroll).styles.display = "none"
    app.query_one("#body", Horizontal).styles.display = "block"
    app.query_one("#chat", Input).placeholder = app._main_chat_placeholder
    positions = app._main_scroll_positions
    app._main_scroll_positions = None
    if positions is not None:
        app.call_after_refresh(lambda: restore_main_scroll(app, positions))


__all__ = [
    "open_conversation_history",
    "update_conversation_history_content",
    "back_from_conversation_history",
]
