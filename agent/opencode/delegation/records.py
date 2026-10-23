"""Delegations state file persistence and locked JSON management."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from agent.infra.file_lock import locked_file


def tail_text(text: str, max_chars: int = 2000) -> str:
    """Return the trailing portion of text up to max_chars."""
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    return f"... [truncated {len(text) - max_chars} chars] ...\n" + text[-max_chars:]


def read_delegations(delegations_path: Path) -> dict[str, Any]:
    """Read delegations dictionary from disk."""
    try:
        if delegations_path.exists():
            data = json.loads(delegations_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def write_delegations_atomic(delegations_path: Path, data: dict[str, Any]) -> None:
    """Atomically persist delegations dictionary to disk."""
    delegations_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = delegations_path.with_suffix(f".tmp.{os.getpid()}")
    try:
        tmp_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp_path, delegations_path)
    except BaseException:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def ensure_delegations_file(delegations_path: Path) -> None:
    """Create empty delegations state file if absent."""
    if not delegations_path.exists():
        write_delegations_atomic(delegations_path, {})


def get_delegation_record(
    delegations_path: Path,
    delegations_lock: Path,
    delegation_id: str,
) -> dict[str, Any] | None:
    """Look up a recorded delegation by ID under lock."""
    with locked_file(delegations_lock):
        delegations = read_delegations(delegations_path)
        return delegations.get(delegation_id)


def save_delegation_record(
    delegations_path: Path,
    delegations_lock: Path,
    record: dict[str, Any],
) -> None:
    """Save or update a delegation record under lock."""
    with locked_file(delegations_lock):
        delegations = read_delegations(delegations_path)
        delegations[record["delegation_id"]] = record
        write_delegations_atomic(delegations_path, delegations)
