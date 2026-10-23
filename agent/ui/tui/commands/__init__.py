"""Command-pattern registry and handlers for human TUI commands."""
from agent.ui.tui.commands.base import CommandHandler
from agent.ui.tui.commands.registry import CommandRegistry

__all__ = [
    "CommandHandler",
    "CommandRegistry",
]
