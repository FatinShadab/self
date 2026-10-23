"""Environment map state persistence, fact verification, and context formatting."""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
from pathlib import Path
from typing import Any

from agent.infra.event_log import EventLogger
from agent.learning.store.constants import VALID_CONFIDENCE, utc_now


def build_entry(
    value: Any,
    confidence: str,
    verified: str,
    evidence: str,
    plugin: str = "core",
    body: str = "container",
) -> dict[str, Any]:
    """Create a standardized environment map entry dictionary."""
    return {
        "value": value,
        "confidence": confidence,
        "last_verified": verified,
        "evidence": evidence,
        "plugin": plugin,
        "body": body,
    }


def initial_entries(workspace: Path, now: str) -> dict[str, dict[str, Any]]:
    """Generate default bootstrap entries for the host/container environment."""
    ram: str | int = "not yet measured"
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemTotal:"):
                ram = int(line.split()[1]) * 1024
                break
    except OSError:
        pass
    try:
        disk = shutil.disk_usage(workspace)
        disk_value: Any = {"total_bytes": disk.total, "used_bytes": disk.used, "free_bytes": disk.free}
    except OSError:
        disk_value = "not yet measured"
    return {
        "os": build_entry({"system": platform.system(), "release": platform.release(), "python": platform.python_version()}, "high", now, "local bootstrap"),
        "packages": build_entry("not yet inventoried", "unknown", now, "awaiting package inspection"),
        "cpu": build_entry({"logical_cpus": os.cpu_count() or 0}, "high", now, "local bootstrap"),
        "ram": build_entry(ram, "high" if isinstance(ram, int) else "unknown", now, "local bootstrap"),
        "disk": build_entry(disk_value, "high" if isinstance(disk_value, dict) else "unknown", now, "local bootstrap"),
        "network_reachability": build_entry("not yet checked", "unknown", now, "awaiting HTTP or network observation"),
        "discovered_limits": build_entry({}, "unknown", now, "awaiting harness observations"),
        "available_tools": build_entry([], "unknown", now, "awaiting registry refresh"),
    }


def load_map(map_path: Path) -> dict[str, Any]:
    """Load map.json, setting default plugin and body tags if absent."""
    try:
        data = json.loads(map_path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("entries", {}), dict):
            for ent in data.get("entries", {}).values():
                if isinstance(ent, dict):
                    ent.setdefault("plugin", "core")
                    ent.setdefault("body", "container")
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {"schema_version": 1, "entries": {}}


def write_map(map_path: Path, data: dict[str, Any], redactor: Any) -> None:
    """Atomically write redacted map dictionary to map_path."""
    redacted = redactor.value(data) if redactor else data
    temp = map_path.with_suffix(".tmp")
    temp.write_text(json.dumps(redacted, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, map_path)


def initialize_map(map_path: Path, workspace: Path, logger: EventLogger) -> None:
    """Create missing map entries and migrate legacy aliases."""
    data = load_map(map_path)
    entries = data.setdefault("entries", {})
    now = utc_now()
    defaults = initial_entries(workspace, now)
    changed = False

    legacy_packages = entries.get("python_packages")
    canonical_packages = entries.get("packages")
    if isinstance(legacy_packages, dict) and isinstance(legacy_packages.get("value"), list):
        canonical_value = canonical_packages.get("value") if isinstance(canonical_packages, dict) else None
        if not isinstance(canonical_packages, dict) or canonical_value is None or canonical_value == "not yet inventoried":
            entries["packages"] = {
                **legacy_packages,
                "evidence": f"migrated from python_packages; {legacy_packages.get('evidence', 'previous environment observation')}",
            }
            changed = True
        if "python_packages" in entries:
            del entries["python_packages"]
            changed = True
    for key, entry in defaults.items():
        if key not in entries:
            entries[key] = entry
            changed = True
    if changed or not map_path.exists():
        data["schema_version"] = 1
        data["updated_at"] = now
        write_map(map_path, data, logger.redactor)
        logger.log("environment_map_initialized", entries=sorted(defaults))


def mark_facts_stale(map_path: Path, body_or_plugin: str, logger: EventLogger) -> list[str]:
    """Mark map facts originating from a body or plugin as confidence='stale'."""
    data = load_map(map_path)
    stored = data.setdefault("entries", {})
    marked: list[str] = []
    for key, entry in stored.items():
        if not isinstance(entry, dict):
            continue
        p = entry.get("plugin", "core")
        b = entry.get("body", "container")
        if p == body_or_plugin or b == body_or_plugin:
            entry["confidence"] = "stale"
            marked.append(key)
    if marked:
        data["updated_at"] = utc_now()
        write_map(map_path, data, logger.redactor)
        logger.log("environment_facts_staled", body_or_plugin=body_or_plugin, keys=marked)
    return marked


def update_environment_map(
    map_path: Path,
    entries: list[dict[str, Any]],
    logger: EventLogger,
    source: str = "agent observation",
    plugin: str = "core",
    body: str = "container",
) -> dict[str, Any]:
    """Replace verified entries with timestamping and redaction."""
    if not isinstance(entries, list) or not entries:
        raise ValueError("entries must be a non-empty list")
    data = load_map(map_path)
    stored = data.setdefault("entries", {})
    updated: list[str] = []
    now = utc_now()
    for item in entries:
        if not isinstance(item, dict):
            raise ValueError("each environment entry must be an object")
        key = str(item.get("key", ""))
        if key == "python_packages":
            key = "packages"
        confidence = str(item.get("confidence", ""))
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", key):
            raise ValueError("environment entry key must use lowercase letters, digits, and underscores")
        if confidence not in VALID_CONFIDENCE:
            raise ValueError("confidence must be unknown, low, medium, high, or stale")
        if "value" not in item:
            raise ValueError("environment entries require a value")
        evidence = logger.redactor.text(item.get("evidence", source))[:2_000]
        item_plugin = str(item.get("plugin") or plugin).strip() or "core"
        item_body = str(item.get("body") or body).strip() or "container"
        stored[key] = build_entry(
            logger.redactor.value(item["value"]),
            confidence,
            now,
            evidence,
            plugin=item_plugin,
            body=item_body,
        )
        updated.append(key)
    data["schema_version"] = 2
    data["updated_at"] = now
    write_map(map_path, data, logger.redactor)
    logger.log("environment_map_updated", keys=updated, source=source)
    return {"ok": True, "updated": updated, "map_path": str(map_path)}


def format_map_context(map_path: Path, active_plugins: Any = None) -> str:
    """Return verified environment-map context formatted for prompt inclusion."""
    entries = load_map(map_path).get("entries", {})
    if not entries:
        return "Environment map is empty."
    lines = []
    for key in sorted(entries):
        entry = entries[key]
        p = entry.get("plugin", "core")
        if active_plugins is not None and p != "core" and p not in active_plugins:
            continue
        value = json.dumps(entry.get("value"), ensure_ascii=False)[:800]
        lines.append(f"- {key}: {value} (confidence={entry.get('confidence')}, verified={entry.get('last_verified')})")
    return "\n".join(lines) if lines else "Environment map is empty."
