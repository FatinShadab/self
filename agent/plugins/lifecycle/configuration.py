"""Human-owned plugin configuration read/write and enablement operations."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.plugins.lifecycle.hashing import compute_plugin_hash
from agent.plugins.lifecycle.models import Plugin


def read_config(config_file: Path) -> dict[str, Any]:
    """Read plugins.json from human config directory."""
    if not config_file.exists():
        return {"plugins": {}}
    try:
        data = json.loads(config_file.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"plugins": {}}
    except (OSError, json.JSONDecodeError):
        return {"plugins": {}}


def write_config(config_dir: Path, config_file: Path, data: dict[str, Any]) -> None:
    """Write plugins.json to human config directory.

    Raises PermissionError if mounted read-only.
    """
    config_dir.mkdir(parents=True, exist_ok=True)
    tmp = config_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(config_file)


def enable_by_human(
    config_dir: Path,
    config_file: Path,
    name: str,
    plugin: Plugin | None,
) -> dict[str, Any]:
    """Enable a plugin on behalf of human operator, computing and recording hash."""
    if plugin is None:
        raise ValueError(f"Plugin '{name}' not found in shipped or workspace plugin directories.")

    plugin_hash = compute_plugin_hash(plugin.plugin_dir)
    cfg = read_config(config_file)
    plugins_cfg = cfg.setdefault("plugins", {})
    plugins_cfg[name] = {
        "enabled": True,
        "hash": plugin_hash,
        "enabled_at": datetime.now(timezone.utc).isoformat(),
    }
    write_config(config_dir, config_file, cfg)
    return {"name": name, "enabled": True, "hash": plugin_hash}


def disable_by_human(
    config_dir: Path,
    config_file: Path,
    name: str,
) -> dict[str, Any]:
    """Disable a plugin on behalf of human operator."""
    cfg = read_config(config_file)
    plugins_cfg = cfg.setdefault("plugins", {})
    if name in plugins_cfg:
        plugins_cfg[name]["enabled"] = False
        plugins_cfg[name]["disabled_at"] = datetime.now(timezone.utc).isoformat()
    else:
        plugins_cfg[name] = {"enabled": False}
    write_config(config_dir, config_file, cfg)
    return {"name": name, "enabled": False}
