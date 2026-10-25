"""Runtime configuration, protocols, and run summary dataclasses for the agent loop."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from agent.infra.hardening import DailyTokenLedger
from agent.llm.llm import LLMResult


class LLMProtocol(Protocol):
    """Interface required by the autonomous loop for model calls."""

    def call(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int,
    ) -> LLMResult:
        """Send a bounded model request and return its response."""
        ...


@dataclass
class AgentConfig:
    """Runtime limits and model settings for one agent loop."""

    workspace: Path = Path("/home/entity")
    max_iterations: int | None = None
    token_budget: int | None = None
    max_tokens_per_call: int | None = None
    top_k_tools: int = 5
    task: str = ""
    base_tool_names: tuple[str, ...] | None = None
    retrieve_memories: bool = True
    curriculum: bool = False
    max_wall_clock_seconds: int | None = None
    input_provider: Callable[[], list[str]] | None = None
    initial_context: str = ""
    resume_checkpoint_task: bool = True
    pause_provider: Callable[[], bool] | None = None
    on_cycle: Callable[[int, str, int], None] | None = None
    identity_context_provider: Callable[[], str] | None = None
    daily_ledger: DailyTokenLedger | None = None
    session_id: str = ""
    body: Any | None = None
    plugins: Any | None = None
    broker: Any | None = None
    audit_trail: Any | None = None
    stop_watcher: Any | None = None
    min_orientation_facts: int = 5


@dataclass
class RunSummary:
    """Usage and stop reason returned by an agent loop."""

    iterations: int
    tokens_used: int
    reason: str
