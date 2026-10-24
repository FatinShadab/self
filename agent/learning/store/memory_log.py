"""Append-only memory logging and keyword/tag retrieval."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from agent.infra.event_log import EventLogger
from agent.learning.store.constants import _words, utc_now


def append_memory_entry(
    state_dir: Path,
    memory_path: Path,
    logger: EventLogger,
    what_was_tried: str,
    outcome: str,
    lesson: str,
    tags: list[str],
    plugin: str = "core",
    body: str = "container",
    report_path: str | None = None,
) -> dict[str, Any]:
    """Append one redacted learning record to persistent memory.jsonl."""
    state_dir.mkdir(parents=True, exist_ok=True)
    rec: dict[str, Any] = {
        "timestamp": utc_now(),
        "what_was_tried": what_was_tried[:4_000],
        "outcome": outcome[:1_000],
        "lesson": lesson[:4_000],
        "tags": sorted({tag.lower() for tag in tags if tag})[:30],
        "plugin": plugin,
        "body": body,
    }
    if report_path:
        rec["report_path"] = report_path
    record = logger.redactor.value(rec)
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
    fd = os.open(memory_path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        os.write(fd, line.encode("utf-8"))
    finally:
        os.close(fd)
    logger.log("memory_recorded", tags=record["tags"], outcome=record["outcome"][:300])
    return record


def read_memory_entries(memory_path: Path) -> list[dict[str, Any]]:
    """Return all persistent memory records from memory.jsonl."""
    records: list[dict[str, Any]] = []
    try:
        with memory_path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict):
                    record.setdefault("plugin", "core")
                    record.setdefault("body", "container")
                    records.append(record)
    except OSError:
        pass
    return records


def retrieve_memory_excerpt(
    memory_path: Path,
    logger: EventLogger,
    query: str,
    limit: int = 6,
    active_plugins: Any = None,
) -> str:
    """Rank persistent memories against query keywords and tags; return bounded excerpt."""
    terms = _words(query)
    ranked: list[tuple[int, int, dict[str, Any]]] = []
    entries = read_memory_entries(memory_path)
    for index, entry in enumerate(entries):
        p = entry.get("plugin", "core")
        if active_plugins is not None and p != "core" and p not in active_plugins:
            continue
        tags = {str(tag).lower() for tag in entry.get("tags", [])}
        body = " ".join(str(entry.get(key, "")) for key in ("what_was_tried", "outcome", "lesson"))
        score = len(terms & tags) * 4 + len(terms & _words(body))
        if score:
            ranked.append((score, index, entry))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    selected: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for _, _, entry in ranked:
        if len(selected) >= max(0, limit):
            break
        key = tuple(str(entry.get(field, "")) for field in ("what_was_tried", "outcome", "lesson"))
        if key in seen:
            continue
        seen.add(key)
        selected.append(entry)
    logger.log("memory_retrieval", query=query[:500], selected=len(selected), total=len(entries))
    if not selected:
        return "No closely related persistent memories yet."

    def _fmt_entry(entry: dict[str, Any]) -> str:
        lines = [
            f"- Tried: {entry.get('what_was_tried', '')}",
            f"  Outcome: {entry.get('outcome', '')}",
            f"  Lesson: {entry.get('lesson', '')}",
            f"  Tags: {', '.join(entry.get('tags', []))}",
        ]
        rp = entry.get("report_path")
        if rp:
            lines.append(f"  Report: {rp}")
        return "\n".join(lines)

    return "\n".join(_fmt_entry(e) for e in selected)[:12_000]
