"""Archive log management for completed and dropped plan items."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def append_archive_records(
    archive_path: Path,
    state_dir: Path,
    redactor: Any,
    records: list[dict[str, Any]],
) -> None:
    """Append archived goals to state/plan_archive.jsonl with redaction."""
    if not records:
        return
    state_dir.mkdir(parents=True, exist_ok=True)
    with archive_path.open("a", encoding="utf-8") as f:
        for rec in records:
            safe_rec = redactor.value(rec) if hasattr(redactor, "value") else rec
            f.write(json.dumps(safe_rec, ensure_ascii=False) + "\n")


def read_archived_items(archive_path: Path, limit: int | None = None) -> list[dict[str, Any]]:
    """Return historical completed/dropped plan goals from plan_archive.jsonl."""
    if not archive_path.exists():
        return []
    items: list[dict[str, Any]] = []
    try:
        for line in archive_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    items.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    if limit is not None and limit > 0:
        return items[-limit:]
    return items
