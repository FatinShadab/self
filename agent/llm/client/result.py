"""Model response dataclass and truncation detection."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class LLMResult:
    """Model response content and measured token usage."""

    content: list[dict[str, Any]]
    input_tokens: int
    output_tokens: int
    stop_reason: str | None
    model: str
    max_output_tokens: int | None = None

    @property
    def total_tokens(self) -> int:
        """Return the combined input and output token count."""
        return self.input_tokens + self.output_tokens


def response_truncated(result: LLMResult, requested_cap: int) -> bool:
    """Detect provider length stops, including hidden thinking token use."""
    reason = str(result.stop_reason or "").casefold()
    cap = result.max_output_tokens or requested_cap
    return (
        reason in {"max_tokens", "max_output_tokens", "length", "token_limit"}
        or reason.startswith("max_tokens")
        or result.output_tokens >= cap
    )
