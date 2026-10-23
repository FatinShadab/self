"""Tested tool lifecycle; keyword ranking is replaceable through ToolSearch."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

from agent.infra.event_log import EventLogger, SECRET_NAME_MARKERS
from agent.infra.process_runner import run_process
from agent.prompts.critics import (
    CRITIC_PROMPT as _CRITIC_PROMPT,
    TOOL_CRITIC_RETRY_NUDGE as _TOOL_CRITIC_RETRY_NUDGE,
)
from agent.tools.custom import (
    CREATE_TOOL_DEFINITION,
    KeywordToolSearch,
    ToolSearch,
    create_custom_tool,
    digest,
    execute_custom_tool,
    load_tool_metadata,
    needs_name_alias,
    recent_failure_context as _recent_failure_context,
    save_tool_meta,
    schema_from_code,
    timestamp,
)

CRITIC_PROMPT = _CRITIC_PROMPT
TOOL_CRITIC_RETRY_NUDGE = _TOOL_CRITIC_RETRY_NUDGE

__all__ = [
    "CREATE_TOOL_DEFINITION",
    "CRITIC_PROMPT",
    "KeywordToolSearch",
    "TOOL_CRITIC_RETRY_NUDGE",
    "ToolRegistry",
    "ToolSearch",
    "digest",
    "run_process",
    "schema_from_code",
    "timestamp",
]


class ToolRegistry:
    """Load, search, create, and execute workspace tools."""

    def __init__(
        self,
        workspace: Path,
        logger: EventLogger,
        review_call: Callable[..., Any],
        reserved_names: set[str],
        *,
        test_timeout: float = 15,
        execution_timeout: float = 30,
        output_cap: int = 20000,
        search: ToolSearch | None = None,
    ) -> None:
        self.root = workspace / "tools"
        self.root.mkdir(parents=True, exist_ok=True)
        self.workspace = workspace
        self.logger = logger
        self.review_call = review_call
        self.model_decisions: Any = None
        self.reserved_names = reserved_names | {"create_tool", "select_model"}
        self.test_timeout = test_timeout
        self.execution_timeout = execution_timeout
        self.output_cap = output_cap
        self.search = search or KeywordToolSearch()
        self.tools: dict[str, dict[str, Any]] = {}
        self.attempt_counts: dict[str, int] = {}
        self._logged_rejections: set[str] = set()
        self.refresh()

    @staticmethod
    def _needs_name_alias(name: str, test_code: str) -> bool:
        """Keep older generated tests importable without changing registration."""
        return needs_name_alias(name, test_code)

    def _save_meta(self, folder: Path, meta: dict[str, Any]) -> None:
        save_tool_meta(folder, meta)

    def refresh(self) -> None:
        """Reload workspace tools and their metadata."""
        self.tools = load_tool_metadata(
            root=self.root,
            reserved_names=self.reserved_names,
            logger=self.logger,
            logged_rejections=self._logged_rejections,
            current_tools=self.tools,
        )

    def retrieve(self, query: str, top_k: int, active_plugins: Any = None) -> list[dict[str, Any]]:
        """Return relevant records for the current query."""
        self.refresh()
        candidates = list(self.tools.values())
        if active_plugins is not None:
            candidates = [
                t
                for t in candidates
                if t.get("plugin", "core") == "core" or t.get("plugin") in active_plugins
            ]
        selected = self.search.search(query, candidates, top_k)
        self.logger.log("tool_retrieval", query=query, top_k=top_k, selected=[t["name"] for t in selected])
        return [
            {
                "name": tool["name"],
                "description": tool["description"],
                "input_schema": tool["input_schema"],
            }
            for tool in selected
        ]

    def recent_failure_context(self, limit: int = 8) -> str:
        """Return compact diagnostics so the actor can repair instead of guessing."""
        return _recent_failure_context(self.workspace, limit=limit)

    def _child_env(self) -> dict[str, str]:
        # Test/runtime subprocesses don't need provider credentials. Shell policy
        # remains unrestricted; these children still run as container root.
        return {
            key: value
            for key, value in os.environ.items()
            if not any(marker in key.upper() for marker in SECRET_NAME_MARKERS)
        }

    def create_tool(self, name: str, description: str, code: str, test_code: str) -> dict[str, Any]:
        """Validate, test, and register a generated workspace tool."""
        return create_custom_tool(
            registry=self,
            name=name,
            description=description,
            code=code,
            test_code=test_code,
            run_process_fn=run_process,
        )

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute a registered tool through the isolated worker."""
        return execute_custom_tool(
            registry=self,
            name=name,
            arguments=arguments,
            run_process_fn=run_process,
        )
