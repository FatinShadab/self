"""Orientation, uptime detection, and environmental change tracking for Linux containers."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable


def get_container_uptime() -> float | None:
    """Read container uptime in seconds from /proc/uptime."""
    try:
        return float(Path("/proc/uptime").read_text(encoding="utf-8").split()[0])
    except (OSError, ValueError, IndexError):
        return None


def detect_orientation_changes(
    workspace: Path,
    snapshot_path: Path | None,
    get_uptime_fn: Callable[[], float | None],
) -> list[str]:
    """Detect filesystem, tool, credential presence, and uptime changes."""
    if snapshot_path is None:
        snapshot_path = workspace / "state" / "wake_snapshot.json"
    old: dict[str, Any] = {}
    if snapshot_path.exists():
        try:
            old = json.loads(snapshot_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            old = {}
    uptime = get_uptime_fn()
    tools_dir = workspace / "tools"
    tool_names: list[str] = []
    if tools_dir.exists():
        for meta in tools_dir.glob("*/meta.json"):
            try:
                data = json.loads(meta.read_text(encoding="utf-8"))
                if data.get("registered"):
                    tool_names.append(str(data.get("name", meta.parent.name)))
            except (OSError, ValueError):
                pass

    known_credential_env = (
        "OLLAMA_API_KEYS",
        "OLLAMA_API_KEY",
        "OLLAM_API_KEYS",
        "OLLAM_API_KEY",
        "ANTHROPIC_API_KEYS",
        "ANTHROPIC_API_KEY",
        "GOOGLE_API_KEY",
        "GROQ_API_KEY",
        "OPENROUTER_API_KEY",
        "MISTRAL_API_KEY",
        "CEREBRAS_API_KEY",
        "HF_TOKEN",
        "CLOUDFLARE_API_TOKEN",
    )
    current = {
        "workspace_entries": (
            sorted(path.name for path in workspace.iterdir() if path.name not in {"logs", "state"})
            if workspace.exists()
            else []
        ),
        "tools": sorted(tool_names),
        "credential_env_present": sorted(name for name in known_credential_env if os.getenv(name)),
        "uptime_seconds": uptime,
    }
    changes: list[str] = []
    for key in ("workspace_entries", "tools", "credential_env_present"):
        if key in old and old.get(key) != current[key]:
            changes.append(f"{key.replace('_', ' ')} changed")
    if (
        old
        and uptime is not None
        and old.get("uptime_seconds") is not None
        and uptime < float(old["uptime_seconds"])
    ):
        changes.append("container uptime reset")
    try:
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = snapshot_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, snapshot_path)
    except OSError:
        pass
    return changes or ["no tracked workspace, tool, credential-presence, or uptime change"]
