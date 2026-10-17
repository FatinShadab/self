"""Hello plugin lifecycle hooks and tool handlers."""
from __future__ import annotations

from typing import Any

_ENABLED_STATE = {"enabled": False}


def on_enable(context: dict[str, Any]) -> None:
    """Invoked when hello plugin is enabled."""
    _ENABLED_STATE["enabled"] = True


def on_disable(context: dict[str, Any]) -> None:
    """Invoked when hello plugin is disabled."""
    _ENABLED_STATE["enabled"] = False


def greet(greeting: str = "Hello") -> dict[str, Any]:
    """Return friendly greeting from hello plugin."""
    return {"ok": True, "message": f"{greeting}, from hello plugin!"}
