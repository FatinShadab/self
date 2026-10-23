"""Plugin compatibility check CLI command."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent.plugins.manifest import (
    CORE_API_VERSION,
    is_core_api_compatible,
)


def cmd_check(
    workspace_dir: Path | str | None = None,
    shipped_dir: Path | str | None = None,
    output_json: bool = False,
    current_api: str = CORE_API_VERSION,
) -> int:
    """Statically check compatibility of all plugins against current core API version."""
    ws = Path(workspace_dir).resolve() if workspace_dir else Path.cwd()
    plugins_pkg_dir = Path(__file__).resolve().parents[1]
    shipped_d = Path(shipped_dir).resolve() if shipped_dir else (
        plugins_pkg_dir if (plugins_pkg_dir / "hello").exists() else Path("/opt/agent/plugins")
    )

    results: list[dict[str, Any]] = []
    all_compatible = True

    def scan_dir(base: Path, source_kind: str) -> None:
        nonlocal all_compatible
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
                    core_api = str(data.get("core_api", "")).strip()

                    if not core_api:
                        compatible = False
                        reason = "Missing 'core_api' specification in manifest"
                    else:
                        compatible = is_core_api_compatible(core_api, current_api=current_api)
                        reason = "Compatible" if compatible else f"Range '{core_api}' excludes current core {current_api}"

                    if not compatible:
                        all_compatible = False

                    results.append({
                        "name": name,
                        "version": version,
                        "core_api": core_api,
                        "core_version": current_api,
                        "compatible": compatible,
                        "reason": reason,
                        "source": source_kind,
                        "path": str(entry),
                    })
                except Exception as exc:
                    all_compatible = False
                    results.append({
                        "name": entry.name,
                        "version": "error",
                        "core_api": "error",
                        "core_version": current_api,
                        "compatible": False,
                        "reason": f"Manifest read error: {exc}",
                        "source": source_kind,
                        "path": str(entry),
                    })

    scan_dir(shipped_d, "shipped")
    if (shipped_d / "examples").exists() and (shipped_d / "examples").is_dir():
        scan_dir(shipped_d / "examples", "shipped")
    scan_dir(ws / "plugins", "workspace")
    if (ws / "plugins" / "examples").exists() and (ws / "plugins" / "examples").is_dir():
        scan_dir(ws / "plugins" / "examples", "workspace")

    if output_json:
        print(json.dumps({"current_core_api": current_api, "all_compatible": all_compatible, "plugins": results}, indent=2))
    else:
        print(f"Core API Version: {current_api}\n")
        if not results:
            print("No plugins found to check.")
            return 0
        print(f"{'PLUGIN':<20} {'VERSION':<10} {'DECLARED RANGE':<18} {'COMPATIBLE':<12} {'NOTE'}")
        print("-" * 80)
        for r in results:
            compat_str = "YES" if r["compatible"] else "NO"
            print(f"{r['name']:<20} {r['version']:<10} {r['core_api']:<18} {compat_str:<12} {r['reason']}")

    return 0 if all_compatible else 1
