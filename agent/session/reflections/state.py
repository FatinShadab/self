"""Durable state and thread log persistence for reflections."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_reflection_state(state_path: Path) -> dict[str, Any]:
    """Read reflection state JSON safely."""
    try:
        value = json.loads(state_path.read_text(encoding="utf-8"))
        if isinstance(value, dict):
            return value
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def save_reflection_state(state_path: Path, state: dict[str, Any], redactor: Any) -> None:
    """Atomically write redacted reflection state JSON."""
    state_path.parent.mkdir(parents=True, exist_ok=True)
    safe = redactor.value(state)
    temporary = state_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(safe, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, state_path)


def append_thread_record(path: Path, record: dict[str, Any], redactor: Any) -> None:
    """Append a redacted record to the JSONL reflection thread file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    safe = redactor.value(record)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(safe, ensure_ascii=False) + "\n")
