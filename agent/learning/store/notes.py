"""Self notes loading, filtering, and rewriting."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

from agent.infra.event_log import EventLogger
from agent.learning.store.memory_log import read_memory_entries
from agent.prompts.container_body import DEFAULT_NOTES_PREAMBLE


def load_self_notes(
    notes_path: Path,
    notes_cap: int,
    redactor: Any,
    rewrite_fn: Callable[[], None],
    active_plugins: Any = None,
) -> str:
    """Load persistent self_notes.md, applying plugin-scoped filtering and redaction."""
    try:
        notes = notes_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        rewrite_fn()
        notes = notes_path.read_text(encoding="utf-8", errors="replace")

    lines = notes.splitlines()
    filtered_lines: list[str] = []
    current_section_enabled = True
    for line in lines:
        m = (
            re.search(r"\[plugin:\s*([a-zA-Z0-9_-]+)\]", line)
            or re.search(r"<!--\s*plugin:\s*([a-zA-Z0-9_-]+)", line)
            or re.search(r"<!--\s*tags:\s*plugin=([a-zA-Z0-9_-]+)", line)
        )
        if m:
            p = m.group(1).strip()
            if active_plugins is not None:
                current_section_enabled = (p == "core" or p in active_plugins)
            continue
        elif line.startswith("#"):
            current_section_enabled = True
        if current_section_enabled:
            filtered_lines.append(line)
    notes = "\n".join(filtered_lines)

    return redactor.text(notes[:notes_cap]) if redactor else notes[:notes_cap]


def rewrite_self_notes(
    notes_path: Path,
    memory_path: Path,
    map_context_str: str,
    notes_cap: int,
    logger: EventLogger,
    body: Any | None = None,
) -> None:
    """Replace persistent self_notes.md with validated preamble, map, and recent lessons."""
    recent = read_memory_entries(memory_path)[-6:]
    lessons = [str(entry.get("lesson", "")).replace("\n", " ")[:300] for entry in recent if entry.get("lesson")]
    preamble = (
        body.describe().notes_preamble
        if body and hasattr(body, "describe") and body.describe().notes_preamble
        else DEFAULT_NOTES_PREAMBLE
    )
    body_lines = [
        "# SELF notes",
        "",
        preamble,
        "",
        "## Current environment map",
        map_context_str,
        "",
        "## Recent lessons",
    ]

    body_lines.extend(f"- {lesson}" for lesson in lessons if lesson)
    if not lessons:
        body_lines.append("- No completed exploration cycles are recorded yet.")
    notes = logger.redactor.text("\n".join(body_lines))[: notes_cap]
    notes_path.write_text(notes.rstrip() + "\n", encoding="utf-8")
    logger.log("self_notes_rewritten", chars=len(notes))
