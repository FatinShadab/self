"""Body interface and implementations for SELF embodiment."""
from __future__ import annotations

from agent.body.base import Body, BodyDescription, Capability
from agent.body.container import ContainerBody, ContainerMetrics

__all__ = [
    "Body",
    "BodyDescription",
    "Capability",
    "ContainerBody",
    "ContainerMetrics",
]
