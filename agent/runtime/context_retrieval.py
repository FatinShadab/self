"""Workspace keyword context retrieval across memory files."""
from __future__ import annotations

import re
from pathlib import Path

from agent.infra.event_log import EventLogger

TEXT_EXTENSIONS = {".md", ".txt", ".json", ".jsonl", ".py", ".sh", ".yaml", ".yml", ".toml"}
WORD = re.compile(r"[a-zA-Z0-9_.-]{2,}")


def retrieve_context(workspace: Path, query: str, logger: EventLogger, limit: int = 8) -> str:
    """Retrieve relevant workspace context for a task."""
    roots = [workspace / "memory"]
    query_terms = {term.lower() for term in WORD.findall(query)}
    candidates: list[tuple[int, str, str]] = []
    scanned = 0

    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if scanned >= 300:
                break
            if not path.is_file() or path.suffix.lower() not in TEXT_EXTENSIONS:
                continue
            scanned += 1
            try:
                text = path.read_text(encoding="utf-8", errors="replace")[:16_000]
                text = logger.redactor.text(text)
            except OSError:
                continue
            searchable = f"{path.name}\n{text}".lower()
            score = sum(searchable.count(term) for term in query_terms)
            if "memory" in path.parts:
                score += 1
            candidates.append((score, str(path), text[:3_000]))

    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    selected = candidates[:limit]
    logger.log(
        "context_retrieval",
        query=query,
        files_scanned=scanned,
        files_selected=[path for _, path, _ in selected],
    )
    if not selected:
        return "No custom tools or durable memories exist yet. Create them as useful discoveries emerge."
    return "\n\n".join(f"### {path}\n{text}" for _, path, text in selected)
