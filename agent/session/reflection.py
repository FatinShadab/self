"""Read-only background reflections initiated by SELF after meaningful work."""
from __future__ import annotations

from agent.session.reflections import (
    ReflectionManager as _ReflectionManager,
    _now as _now_fn,
)

ReflectionManager = _ReflectionManager
_now = _now_fn

__all__ = [
    "ReflectionManager",
    "_now",
]
