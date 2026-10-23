"""Model decisions history logging, persistence, legacy migration, and tally summary."""
from __future__ import annotations

from collections import Counter, deque
import json
import os
from pathlib import Path
import sys
import uuid
from typing import Any

from agent.infra.event_log import EventLogger
from agent.infra.file_lock import locked_file


def append_decision_record(
    path: Path,
    lock_path: Path,
    logger: EventLogger,
    record: dict[str, Any],
) -> None:
    """Append a redacted decision record to the decisions JSONL file."""
    safe = logger.redactor.value(record)
    path.parent.mkdir(parents=True, exist_ok=True)
    with locked_file(lock_path):
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(safe, ensure_ascii=False) + "\n")


def migrate_legacy_records(path: Path, task_path: Path, lock_path: Path) -> None:
    """Preserve earlier observations while marking missing decision evidence."""
    if not path.exists():
        return
    with locked_file(lock_path):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        rows: list[dict[str, Any]] = []
        task_rows: list[dict[str, Any]] = []
        changed = False
        for line in lines:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            if row.get("source") == "task_observation":
                task_rows.append(row)
                changed = True
                continue
            if "origin" not in row:
                status = row.get("status")
                row["origin"] = (
                    "model_choice"
                    if status in {"selected", "completed"}
                    else "default_after_parse_failure"
                    if status == "malformed_default"
                    else "default_after_error"
                )
                row["legacy_missing_evidence"] = True
                changed = True
            for field, value in (
                ("call_id", uuid.uuid4().hex),
                ("session_id", "legacy_unknown"),
                ("source", "checkpoint:legacy"),
            ):
                if not row.get(field):
                    row[field] = value
                    changed = True
            for field, value in (
                ("options", None),
                ("registry_summary", None),
                ("raw_response", None),
                ("stop_reason", None),
            ):
                if field not in row:
                    row[field] = value
                    changed = True
            rows.append(row)
        if not changed:
            return
        if task_rows:
            existing_ids: set[str] = set()
            try:
                with task_path.open("r", encoding="utf-8") as handle:
                    for line in handle:
                        try:
                            existing_ids.add(str(json.loads(line).get("call_id", "")))
                        except (json.JSONDecodeError, AttributeError):
                            continue
            except OSError:
                pass
            with task_path.open("a", encoding="utf-8") as handle:
                for row in task_rows:
                    if str(row.get("call_id", "")) not in existing_ids:
                        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        temporary = path.with_name(f".model-decisions-{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def read_last_decisions(path: Path, limit: int | None = 10) -> list[dict[str, Any]]:
    """Return the most recent persisted model decisions."""
    rows: deque[dict[str, Any]] = deque(maxlen=limit)
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                    if isinstance(row, dict):
                        rows.append(row)
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return list(rows)


def print_decision_summary(workspace: str | Path, *, output: Any = None) -> None:
    """Print the minimal experiment-integrity tally, without outcome analysis."""
    path = Path(workspace) / "state" / "model_decisions.jsonl"
    by_source: Counter[str] = Counter()
    by_origin: Counter[str] = Counter()
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict):
                    by_source[str(row.get("source", "unknown"))] += 1
                    by_origin[str(row.get("origin", "legacy_unknown"))] += 1
    except OSError:
        pass
    total = sum(by_origin.values())
    forced = total - by_origin.get("model_choice", 0)
    stream = output or sys.stdout
    print("Decisions by source: " + json.dumps(dict(sorted(by_source.items()))), file=stream)
    print("Decisions by origin: " + json.dumps(dict(sorted(by_origin.items()))), file=stream)
    print(f"Decisions defaulted after cap: {by_origin.get('default_after_cap', 0)}", file=stream)
    print(
        f"Non-model-choice share: {forced}/{total} ({forced / total:.1%})"
        if total
        else "Non-model-choice share: 0/0 (0.0%)",
        file=stream,
    )


__all__ = [
    "append_decision_record",
    "migrate_legacy_records",
    "read_last_decisions",
    "print_decision_summary",
]
