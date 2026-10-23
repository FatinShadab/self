"""Textual widgets for the wake TUI layout."""
from __future__ import annotations

from typing import Any, Callable

try:
    from textual import events
    from textual.widgets import Static
except ImportError:
    events = None  # type: ignore[assignment]
    Static = object  # type: ignore[assignment, misc]


class PlanResizeHandle(Static):
    """One-line divider that gives the plan a draggable vertical size."""

    def __init__(self, on_drag: Callable[[int], None]) -> None:
        super().__init__("─ drag to resize goals ─", id="plan-resizer", markup=False)
        self._on_drag = on_drag
        self._dragging = False

    def _drag_to(self, event: Any) -> None:
        screen_y = getattr(event, "screen_y", self.region.y + event.y)
        self._on_drag(int(screen_y))

    def on_mouse_down(self, event: Any) -> None:
        self._dragging = True
        self.capture_mouse()
        self._drag_to(event)
        event.stop()

    def on_mouse_move(self, event: Any) -> None:
        if self._dragging:
            self._drag_to(event)
            event.stop()

    def on_mouse_up(self, event: Any) -> None:
        if self._dragging:
            self._drag_to(event)
            self._dragging = False
            self.release_mouse()
            event.stop()


__all__ = [
    "PlanResizeHandle",
]
