"""Tool metadata loading, atomic saving, and failure context retrieval."""
from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any

from agent.infra.event_log import EventLogger
from agent.tools.custom.constants import digest


def save_tool_meta(folder: Path, meta: dict[str, Any]) -> None:
    """Atomically save tool metadata JSON."""
    meta.setdefault("plugin", "core")
    meta.setdefault("body", "container")
    temporary = folder / f".meta-{uuid.uuid4().hex}.tmp"
    temporary.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(folder / "meta.json")


def load_tool_metadata(
    root: Path,
    reserved_names: set[str],
    logger: EventLogger,
    logged_rejections: set[str],
    current_tools: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Reload workspace tools and their metadata, logging rejections and new loads."""
    loaded = {}
    for folder in root.iterdir():
        if not folder.is_dir() or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", folder.name):
            continue
        try:
            meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
            if not meta.get("registered") or meta["name"] != folder.name or folder.name in reserved_names:
                continue
            for file, key in (("tool.py", "code_sha256"), ("test_tool.py", "test_sha256")):
                if digest((folder / file).read_text(encoding="utf-8")) != meta[key]:
                    raise ValueError(f"{file} changed outside create_tool; re-test and review it")
            meta.setdefault("plugin", "core")
            meta.setdefault("body", "container")
            loaded[folder.name] = meta
            logged_rejections.discard(folder.name)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            if folder.name not in logged_rejections:
                logged_rejections.add(folder.name)
                logger.log(
                    "tool_load_rejected",
                    name=folder.name,
                    error=str(exc),
                    how_to_clear="Re-test and re-register through create_tool to clear this rejection.",
                )
    changed = {name for name, meta in loaded.items() if current_tools.get(name) != meta}
    for name in sorted(changed):
        logger.log("tool_loaded", name=name, version=loaded[name]["version"])
    return loaded


def recent_failure_context(workspace: Path, limit: int = 8) -> str:
    """Return compact diagnostics so the actor can repair instead of guessing."""
    path = workspace / "logs" / "actions.jsonl"
    failures: list[str] = []
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[-300:]:
            record = json.loads(line)
            if record.get("event") != "tool_creation_failed":
                continue
            traceback_text = str(record.get("traceback", ""))
            useful = [
                item.strip()
                for item in traceback_text.splitlines()
                if any(
                    marker in item
                    for marker in (
                        "ValueError:",
                        "ImportError:",
                        "ModuleNotFoundError:",
                        "AssertionError:",
                    )
                )
            ]
            failures.append(
                f"{record.get('name', 'unknown')} attempt {record.get('attempt', '?')}: "
                + (useful[-1] if useful else "see attempt diagnostics")
            )
    except (OSError, json.JSONDecodeError):
        return "No prior tool-creation diagnostics are available."
    return "\n".join(failures[-limit:]) or "No prior tool-creation diagnostics are available."
