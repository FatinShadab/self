"""Data structures for action requests, verdicts, and rate limits."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent.infra.permissions.level import PermissionLevel


@dataclass
class ActionRequest:
    """Action request submitted to the permission broker."""
    action: str = ""
    source: str = "core"
    level: PermissionLevel = PermissionLevel.L0
    params: dict[str, Any] = field(default_factory=dict)
    dry_run: bool = False
    reversible: bool = False
    undo_hint: str = ""
    action_id: str = ""
    actor: str = ""
    action_type: str = ""
    target: str = ""

    def __post_init__(self) -> None:
        if self.actor and (self.source == "core" or not self.source):
            self.source = self.actor
        if self.action_type and not self.action:
            self.action = self.action_type
        if self.target and "target" not in self.params:
            self.params["target"] = self.target


@dataclass
class ActionVerdict:
    """Decision returned by the permission broker."""
    allowed: bool
    reason: str
    request: ActionRequest
    dry_run: bool = False


@dataclass
class RateLimitConfig:
    """Rate limit per action class (actions per time window, NOT tokens)."""
    action_class: str
    max_actions: int
    window_seconds: float
