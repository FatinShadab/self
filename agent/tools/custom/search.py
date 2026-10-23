"""Tool ranking and keyword search implementations."""
from __future__ import annotations

import re
from typing import Any, Protocol


class ToolSearch(Protocol):
    """Interface for ranking registered tools against a query."""

    def search(self, query: str, tools: list[dict[str, Any]], top_k: int) -> list[dict[str, Any]]:
        """Rank candidate tools for a query and return the best matches."""
        ...


class KeywordToolSearch:
    """Rank tools using words in their names and descriptions."""

    def search(self, query: str, tools: list[dict[str, Any]], top_k: int) -> list[dict[str, Any]]:
        """Rank candidate tools for a query and return the best matches."""
        terms = set(re.findall(r"[a-z0-9]+", query.lower()))
        ranked = []
        for tool in tools:
            words = set(re.findall(r"[a-z0-9]+", (tool["name"] + " " + tool["description"]).lower()))
            score = len(terms & words)
            if score:
                ranked.append((score, tool["name"], tool))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        return [item[2] for item in ranked[:max(0, top_k)]]
