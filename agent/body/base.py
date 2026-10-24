"""The Body interface for SELF embodiment and hardware/OS interactions."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class BodyDescription:
    """Embodiment narrative, default interests, and initial orientation task."""

    embodiment_text: str = ""
    embodiment_clause: str = ""
    default_interests: list[str] = field(default_factory=list)
    initial_orientation_task: str = ""
    conversation_context: str = ""
    identity_context: str = ""
    identity_harness_context: str = ""
    identity_orientation_context: str = ""
    identity_operating_environment: str = ""
    notes_preamble: str = ""
    body_rules: list[str] = field(default_factory=list)
    pre_capability_rules: list[str] = field(default_factory=list)
    post_capability_rules: list[str] = field(default_factory=list)
    extra_tool_descriptions: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Capability:
    """A single capability exposed by a body."""

    name: str
    schema: dict[str, Any]
    risk_class: str  # e.g. "executes", "reads", "writes", "network"
    reversible: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "schema": self.schema,
            "risk_class": self.risk_class,
            "reversible": self.reversible,
        }


class Body(ABC):
    """Abstract interface defining the agent's physical/environmental embodiment."""

    broker: Any | None = None

    @abstractmethod
    def describe(self) -> BodyDescription:
        """Return narrative describing the embodiment, default interests, and initial orientation task."""

    @abstractmethod
    def capabilities(self) -> list[Capability]:
        """Return list of capabilities provided by this body."""

    @abstractmethod
    def sense(self) -> dict[str, Any]:
        """Gather telemetry/metrics, uptime, and environmental changes."""

    @abstractmethod
    def act(self, action: str, **kwargs: Any) -> dict[str, Any]:
        """Perform an action (execute, read, write, list, fetch, probe)."""

    @abstractmethod
    def health(self) -> dict[str, Any]:
        """Return body health status."""

    @abstractmethod
    def emergency_stop(self) -> None:
        """Halt running actions immediately."""

    def initial_orientation_task(self) -> str:
        """Convenience accessor for the body's initial orientation task."""
        return self.describe().initial_orientation_task
