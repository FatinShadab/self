"""Persistent, bounded learning state for SELF.

This module deliberately uses simple local files and keyword retrieval. The
interfaces keep retrieval separate so an embedding index can replace it later.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.infra.event_log import EventLogger
from agent.learning.store import (
    VALID_CONFIDENCE,
    WORD,
    _words,
    append_memory_entry,
    build_entry,
    format_map_context,
    initial_entries,
    initialize_map,
    load_map,
    load_self_notes,
    mark_facts_stale,
    propose_curriculum_task,
    read_memory_entries,
    record_cycle_memory,
    retrieve_memory_excerpt,
    rewrite_self_notes,
    update_environment_map,
    utc_now,
    write_map,
)


class LearningStore:
    """Owns state files below one workspace without storing credentials."""

    def __init__(
        self,
        workspace: str | Path,
        logger: EventLogger,
        notes_cap: int = 6_000,
        body: Any | None = None,
    ) -> None:
        self.workspace = Path(workspace)
        self.state_dir = self.workspace / "state"
        self.memory_path = self.state_dir / "memory.jsonl"
        self.map_path = self.state_dir / "map.json"
        self.notes_path = self.state_dir / "self_notes.md"
        self.notes_cap = max(1_000, notes_cap)
        self.logger = logger
        self.body = body

    def initialize(self) -> None:
        """Create any missing workspace state files with defaults."""
        self.state_dir.mkdir(parents=True, exist_ok=True)
        initialize_map(self.map_path, self.workspace, self.logger)
        if not self.notes_path.exists():
            self.rewrite_notes()

    def _initial_entries(self, now: str) -> dict[str, dict[str, Any]]:
        return initial_entries(self.workspace, now)

    @staticmethod
    def _entry(
        value: Any,
        confidence: str,
        verified: str,
        evidence: str,
        plugin: str = "core",
        body: str = "container",
    ) -> dict[str, Any]:
        return build_entry(value, confidence, verified, evidence, plugin=plugin, body=body)

    def _load_map(self) -> dict[str, Any]:
        return load_map(self.map_path)

    def _write_map(self, data: dict[str, Any]) -> None:
        write_map(self.map_path, data, self.logger.redactor)

    def mark_facts_stale_for_body(self, body_or_plugin: str) -> list[str]:
        """Mark map facts originating from a body or plugin as confidence='stale'."""
        return mark_facts_stale(self.map_path, body_or_plugin, self.logger)

    def update_map(
        self,
        entries: list[dict[str, Any]],
        source: str = "agent observation",
        plugin: str = "core",
        body: str = "container",
    ) -> dict[str, Any]:
        """Replace verified entries. Agent supplied timestamps are intentionally ignored."""
        return update_environment_map(
            self.map_path,
            entries,
            self.logger,
            source=source,
            plugin=plugin,
            body=body,
        )

    def update_runtime(self, tool_names: list[str], limits: dict[str, Any]) -> None:
        """Refresh verified tool and limit facts in the environment map."""
        self.update_map(
            [
                {"key": "available_tools", "value": sorted(set(tool_names)), "confidence": "high", "evidence": "harness registry refresh"},
                {"key": "discovered_limits", "value": limits, "confidence": "high", "evidence": "harness configuration"},
            ],
            source="harness",
        )

    def append_memory(
        self,
        what_was_tried: str,
        outcome: str,
        lesson: str,
        tags: list[str],
        plugin: str = "core",
        body: str = "container",
        report_path: str | None = None,
    ) -> dict[str, Any]:
        """Append one redacted learning record to persistent memory."""
        return append_memory_entry(
            self.state_dir,
            self.memory_path,
            self.logger,
            what_was_tried=what_was_tried,
            outcome=outcome,
            lesson=lesson,
            tags=tags,
            plugin=plugin,
            body=body,
            report_path=report_path,
        )

    def memory_entries(self) -> list[dict[str, Any]]:
        """Return persistent memory records."""
        return read_memory_entries(self.memory_path)

    def retrieve_memories(self, query: str, limit: int = 6, active_plugins: Any = None) -> str:
        """Rank persistent memories against a query and return a bounded excerpt."""
        return retrieve_memory_excerpt(
            self.memory_path,
            self.logger,
            query=query,
            limit=limit,
            active_plugins=active_plugins,
        )

    def map_context(self, active_plugins: Any = None) -> str:
        """Return verified environment-map context for a prompt."""
        return format_map_context(self.map_path, active_plugins=active_plugins)

    def load_notes(self, active_plugins: Any = None) -> str:
        """Load persistent self notes from the workspace."""
        return load_self_notes(
            self.notes_path,
            self.notes_cap,
            self.logger.redactor,
            rewrite_fn=self.rewrite_notes,
            active_plugins=active_plugins,
        )

    def rewrite_notes(self) -> None:
        """Replace the persistent self notes with validated content."""
        rewrite_self_notes(
            self.notes_path,
            self.memory_path,
            map_context_str=self.map_context(),
            notes_cap=self.notes_cap,
            logger=self.logger,
            body=self.body,
        )

    def record_cycle(
        self,
        task: str,
        cycle: int,
        actions: list[dict[str, Any]],
        report: str,
        plugin: str = "core",
        body: str = "container",
    ) -> None:
        """Summarize one cycle as a memory and refresh notes when needed."""
        record_cycle_memory(
            workspace=self.workspace,
            state_dir=self.state_dir,
            task=task,
            cycle=cycle,
            actions=actions,
            report=report,
            append_memory_fn=self.append_memory,
            load_notes_fn=self.load_notes,
            rewrite_notes_fn=self.rewrite_notes,
            notes_cap=self.notes_cap,
            plugin=plugin,
            body=body,
        )

    def propose_curriculum(self) -> str:
        """Choose a bounded practice task from recent successes."""
        return propose_curriculum_task(self.memory_path, self.logger)


__all__ = [
    "LearningStore",
    "VALID_CONFIDENCE",
    "WORD",
    "_words",
    "utc_now",
]
