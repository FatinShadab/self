from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class ProviderError(RuntimeError):
    pass


class ProviderUnavailable(ProviderError):
    pass


class ProviderRateLimited(ProviderError):
    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


@dataclass
class ProviderResponse:
    text: str
    usage: dict[str, int]
    model: str
    headers: dict[str, str]


class ProviderAdapter(Protocol):
    provider: str

    def is_configured(self) -> bool: ...

    def chat(self, messages: list[dict[str, Any]], model: str, max_tokens: int) -> ProviderResponse: ...
