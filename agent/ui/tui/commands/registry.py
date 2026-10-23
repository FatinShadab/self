"""Command registry mapping slash command patterns to command handlers."""
from __future__ import annotations

from typing import Any

from agent.ui.tui.commands.base import CommandHandler
from agent.ui.tui.commands.handlers import (
    IdentityCommandHandler,
    LifecycleCommandHandler,
    PlanGoalsCommandHandler,
    PluginSlashCommandHandler,
    StateInfoCommandHandler,
    TypingCommandHandler,
    ViewCommandHandler,
    VoiceCommandHandler,
)


class CommandRegistry:
    """Registry of command handlers following the Open/Closed Principle."""

    def __init__(self) -> None:
        self.handlers: list[CommandHandler] = [
            ViewCommandHandler(),
            VoiceCommandHandler(),
            TypingCommandHandler(),
            LifecycleCommandHandler(),
            PlanGoalsCommandHandler(),
            IdentityCommandHandler(),
            StateInfoCommandHandler(),
            PluginSlashCommandHandler(),
        ]

    def register(self, handler: CommandHandler) -> None:
        """Register a new command handler at the front of the chain."""
        self.handlers.insert(0, handler)

    def dispatch(self, app: Any, coordinator: Any, text: str) -> bool:
        """Find the matching handler and execute it. Return True if handled."""
        for handler in self.handlers:
            if handler.matches(text):
                if handler.handle(app, coordinator, text):
                    return True
        return False


__all__ = [
    "CommandRegistry",
]
