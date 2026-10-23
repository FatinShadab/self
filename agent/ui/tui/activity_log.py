"""Activity log queuing and asynchronous draining for the TUI worklog."""
from __future__ import annotations

from typing import Any

from agent.ui.formatting.rich_markup import escape_rich_markup


def queue_activity(app: Any, message: str) -> None:
    """Queue an activity message and launch the background drain worker if idle."""
    app._pending_activity.append(message)
    if not app._draining_activity:
        app._draining_activity = True
        app.run_worker(drain_activity(app), exclusive=False)


async def drain_activity(app: Any) -> None:
    """Asynchronously drain queued activity entries into the worklog VerticalScroll."""
    try:
        from textual.containers import VerticalScroll
        from textual.widgets import Static
    except ImportError:
        return

    worklog = app.query_one("#worklog", VerticalScroll)
    try:
        while app._pending_activity:
            message = app._pending_activity.pop(0)
            follow = worklog.scroll_y >= worklog.max_scroll_y - 1
            # Textual 0.89 still parses a string Static as Rich markup
            # when rendering, even when markup=False was supplied.
            # Activity comes from LLM and tool output, so escape it at
            # the rendering boundary to keep every literal "[" safe.
            await worklog.mount(Static(escape_rich_markup(message), classes="activity-entry", markup=True))
            if follow:
                # Mounting changes the content height asynchronously. Scroll
                # after Textual lays out the new entry, otherwise max_scroll_y
                # still describes the previous bottom and follow mode drifts.
                app.call_after_refresh(lambda: worklog.scroll_end(animate=False))
    finally:
        app._draining_activity = False
        if app._pending_activity:
            app._draining_activity = True
            app.run_worker(drain_activity(app), exclusive=False)


__all__ = [
    "queue_activity",
    "drain_activity",
]
