"""SELF base module."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class ProviderError(RuntimeError):
    """Base error for provider request failures."""

    pass


class ProviderUnavailable(ProviderError):
    """Signal that a configured provider cannot be used."""

    pass


class ProviderRateLimited(ProviderError):
    """Signal a provider rate-limit response."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


@dataclass
class ProviderResponse:
    """Normalized text, usage, model, and headers from a provider."""

    text: str
    usage: dict[str, int]
    model: str
    headers: dict[str, str]


class ProviderAdapter(Protocol):
    """Interface implemented by provider-specific chat adapters."""

    provider: str

    def is_configured(self) -> bool:
        """Return whether this provider has the required configuration."""
        ...

    def chat(self, messages: list[dict[str, Any]], model: str, max_tokens: int) -> ProviderResponse:
        """Send chat messages and return a normalized provider response."""
        ...
