"""Plugin discovery and listing CLI command."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent.plugins.manager import compute_plugin_hash


def _read_config_static(config_dir: Path) -> dict[str, Any]:
    cfg_file = config_dir / "plugins.json"
    if not cfg_file.exists():
        return {"plugins": {}}
    try:
        data = json.loads(cfg_file.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"plugins": {}}
    except Exception:
        return {"plugins": {}}


def cmd_list(
    workspace_dir: Path | str | None = None,
    config_dir: Path | str | None = None,
    shipped_dir: Path | str | None = None,
    output_json: bool = False,
) -> int:
    """List discovered plugins, versions, core API ranges, and hash status."""
    ws = Path(workspace_dir).resolve() if workspace_dir else Path.cwd()
    cfg_d = Path(config_dir).resolve() if config_dir else (ws / "config" if (ws / "config").exists() else ws.parent / "config")
    plugins_pkg_dir = Path(__file__).resolve().parents[1]
    shipped_d = Path(shipped_dir).resolve() if shipped_dir else (
        plugins_pkg_dir if (plugins_pkg_dir / "hello").exists() else Path("/opt/agent/plugins")
    )

    cfg = _read_config_static(cfg_d)
    plugins_cfg = cfg.get("plugins", {})

    discovered: dict[str, dict[str, Any]] = {}

    def scan_dir(base: Path, source_kind: str) -> None:
        if not base.exists() or not base.is_dir():
            return
        for entry in sorted(base.iterdir()):
            if entry.name in {"_archive", "_template", "examples"} or entry.name.startswith(("_", ".")):
                continue
            manifest_file = entry / "plugin.json"
            if entry.is_dir() and manifest_file.exists():
                try:
                    data = json.loads(manifest_file.read_text(encoding="utf-8"))
                    name = str(data.get("name", entry.name))
                    version = str(data.get("version", "unknown"))
                    core_api = str(data.get("core_api", "unknown"))
                    current_hash = compute_plugin_hash(entry)

                    cfg_entry = plugins_cfg.get(name, {})
                    enabled = bool(cfg_entry.get("enabled", False))
                    pinned_hash = str(cfg_entry.get("hash", ""))

                    if not enabled:
                        hash_status = "disabled"
                    elif not pinned_hash:
                        hash_status = "not_pinned"
                    elif pinned_hash == current_hash:
                        hash_status = "pinned_match"
                    else:
                        hash_status = "mismatch"

                    discovered[name] = {
                        "name": name,
                        "version": version,
                        "core_api": core_api,
                        "source": source_kind,
                        "path": str(entry),
                        "enabled": enabled,
                        "hash_status": hash_status,
                        "current_hash": current_hash,
                        "pinned_hash": pinned_hash,
                    }
                except Exception as exc:
                    discovered[entry.name] = {
                        "name": entry.name,
                        "version": "error",
                        "core_api": "error",
                        "source": source_kind,
                        "path": str(entry),
                        "enabled": False,
                        "hash_status": "error",
                        "error": str(exc),
                    }

    # Scan shipped and workspace
    scan_dir(shipped_d, "shipped")
    if (shipped_d / "examples").exists() and (shipped_d / "examples").is_dir():
        scan_dir(shipped_d / "examples", "shipped")
    scan_dir(ws / "plugins", "workspace")
    if (ws / "plugins" / "examples").exists() and (ws / "plugins" / "examples").is_dir():
        scan_dir(ws / "plugins" / "examples", "workspace")

    if output_json:
        print(json.dumps(list(discovered.values()), indent=2))
    else:
        if not discovered:
            print("No plugins discovered.")
            return 0
        print(f"{'NAME':<20} {'VERSION':<10} {'CORE_API':<18} {'STATUS':<10} {'HASH_STATUS':<14} {'SOURCE':<10}")
        print("-" * 86)
        for p in discovered.values():
            status_str = "enabled" if p.get("enabled") else "disabled"
            print(
                f"{p['name']:<20} {p['version']:<10} {p['core_api']:<18} "
                f"{status_str:<10} {p['hash_status']:<14} {p['source']:<10}"
            )
    return 0
