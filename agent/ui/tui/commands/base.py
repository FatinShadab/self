"""Base command handler interface for the Command pattern registry."""
from __future__ import annotations

from typing import Any, Protocol


class CommandHandler(Protocol):
    """Protocol for human CLI slash command handlers."""

    def matches(self, text: str) -> bool:
        """Return True if this handler handles the command string."""
        ...

    def handle(self, app: Any, coordinator: Any, text: str) -> bool:
        """Execute the command and return True if handled."""
        ...


__all__ = [
    "CommandHandler",
]
