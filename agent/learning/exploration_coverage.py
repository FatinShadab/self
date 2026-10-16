"""Read-only exploration coverage built from durable action and tool records."""
from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
import hashlib
import json
import posixpath
import re
from pathlib import Path
from typing import Any

@dataclass(frozen=True)
class CoverageSummary:
    """Summarize visits to exploration areas."""

    directories: tuple[tuple[str, int], ...]
    tools: tuple[tuple[str, str], ...]

    @property
    def total_visits(self) -> int:
        """Return the number of recorded exploration visits."""
        return sum(count for _, count in self.directories)


def _directory_for(tool: str, path: Any) -> str | None:
    if not isinstance(path, str) or not path or "\x00" in path:
        return None
    absolute = path if posixpath.isabs(path) else posixpath.join("/home/entity", path)
    normalized = posixpath.normpath(absolute)
    return normalized if tool == "list_dir" else posixpath.dirname(normalized)


def directory_visits(log_path: Path) -> tuple[tuple[str, int], ...]:
    """Pair historical tool calls with results and count only successful reads."""
    visits: Counter[str] = Counter()
    pending: dict[str, deque[Any]] = {"list_dir": deque(), "read_file": deque()}
    try:
        with log_path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, dict):
                    continue
                tool = record.get("tool")
                if tool not in pending:
                    continue
                if record.get("event") == "tool_call":
                    arguments = record.get("arguments")
                    pending[tool].append(arguments.get("path") if isinstance(arguments, dict) else None)
                elif record.get("event") == "tool_result" and pending[tool]:
                    path = pending[tool].popleft()
                    if record.get("ok") is True:
                        directory = _directory_for(tool, path)
                        if directory is not None:
                            visits[directory] += 1
    except FileNotFoundError:
        pass
    return tuple(sorted(visits.items(), key=lambda item: (-item[1], item[0])))


def registered_tools(tools_root: Path, reserved_names: set[str] | None = None) -> tuple[tuple[str, str], ...]:
    """Apply the runtime registry's metadata and source integrity rules."""
    found: list[tuple[str, str]] = []
    reserved = (reserved_names or set()) | {"create_tool"}
    try:
        folders = list(tools_root.iterdir())
    except FileNotFoundError:
        return ()
    for folder in folders:
        if not folder.is_dir() or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", folder.name) or folder.name in reserved:
            continue
        try:
            meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
            if not isinstance(meta, dict) or meta.get("registered") is not True or meta.get("name") != folder.name:
                continue
            for filename, key in (("tool.py", "code_sha256"), ("test_tool.py", "test_sha256")):
                digest = hashlib.sha256((folder / filename).read_text(encoding="utf-8").encode("utf-8")).hexdigest()
                if digest != meta[key]:
                    raise ValueError("Tool source no longer matches registered metadata")
            description = meta.get("description")
            if not isinstance(description, str):
                continue
            found.append((folder.name, " ".join(description.split())))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return tuple(sorted(found))


def build_coverage(workspace: Path, reserved_names: set[str] | None = None) -> CoverageSummary:
    """Build an exploration summary from recorded activity."""
    return CoverageSummary(
        directories=directory_visits(workspace / "logs" / "actions.jsonl"),
        tools=registered_tools(workspace / "tools", reserved_names),
    )
