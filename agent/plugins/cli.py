"""Plugin SDK Command-Line Interface (CLI).

Provides commands:
  - new: Scaffold a new plugin skeleton from plugins/_template.
  - validate: Statically validate plugin manifest, schema, permissions, and tests.
  - list: List discovered plugins, enablement status, and hash pinning status.
  - check: Statically check compatibility of all plugins against the core API version.

This module is strictly static: it never imports or executes untrusted plugin code.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

from agent.infra.permission_broker import PermissionLevel
from agent.plugins.manifest import (
    CORE_API_VERSION,
    VALID_KINDS,
    VALID_RISK_CLASSES,
    _parse_version,
    is_core_api_compatible,
)
from agent.plugins.manager import (
    CORE_TOOL_NAMES,
    compute_plugin_hash,
)

RESERVED_PLUGIN_NAMES = frozenset({
    "_template",
    "_archive",
    "template",
    "archive",
    "core",
    "self",
    "base",
})


def _find_template_dir(custom_path: Path | str | None = None) -> Path | None:
    """Locate the starter template directory."""
    if custom_path:
        p = Path(custom_path).resolve()
        if p.exists() and p.is_dir():
            return p

    candidates = [
        Path.cwd() / "plugins" / "_template",
        Path(__file__).resolve().parents[2] / "plugins" / "_template",
        Path("/opt/agent/plugins/_template"),
        Path(__file__).resolve().parent / "_template",
    ]
    for c in candidates:
        if c.exists() and c.is_dir() and (c / "plugin.json").exists():
            return c
    return None


def cmd_new(
    name: str,
    dest_dir: Path | str | None = None,
    template_dir: Path | str | None = None,
) -> int:
    """Scaffold a new plugin from plugins/_template."""
    # 1. Validate plugin name
    clean_name = str(name).strip()
    if not clean_name:
        sys.stderr.write("Error: Plugin name cannot be empty.\n")
        return 1

    if not re.match(r"^[a-zA-Z0-9_-]+$", clean_name):
        sys.stderr.write(
            f"Error: Invalid plugin name '{clean_name}'. Must contain only alphanumeric characters, underscores, or hyphens.\n"
        )
        return 1

    if clean_name.startswith(("_", ".")):
        sys.stderr.write(f"Error: Plugin name '{clean_name}' cannot start with an underscore or dot.\n")
        return 1

    if clean_name.lower() in RESERVED_PLUGIN_NAMES:
        sys.stderr.write(f"Error: Plugin name '{clean_name}' is reserved and cannot be used.\n")
        return 1

    # 2. Locate template
    tmpl = _find_template_dir(template_dir)
    if tmpl is None:
        sys.stderr.write("Error: Plugin template directory 'plugins/_template' not found.\n")
        return 1

    # 3. Determine destination directory
    if dest_dir is not None:
        d = Path(dest_dir).resolve()
        target_dir = d if d.name == clean_name else (d / clean_name)
    elif (Path.cwd() / "plugins").exists() and (Path.cwd() / "plugins").is_dir():
        target_dir = (Path.cwd() / "plugins" / clean_name).resolve()
    else:
        target_dir = (Path.cwd() / clean_name).resolve()

    # 4. Refuse overwrite
    if target_dir.exists():
        sys.stderr.write(f"Error: Destination directory '{target_dir}' already exists. Refusing to overwrite.\n")
        return 1

    # 5. Scaffold template
    try:
        shutil.copytree(
            tmpl,
            target_dir,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", ".git*"),
        )
    except OSError as exc:
        sys.stderr.write(f"Error copying template to '{target_dir}': {exc}\n")
        return 1

    # 6. Customize manifest for new plugin
    manifest_file = target_dir / "plugin.json"
    if manifest_file.exists():
        try:
            data = json.loads(manifest_file.read_text(encoding="utf-8"))
            data["name"] = clean_name
            data["description"] = f"{clean_name} plugin providing specialized capabilities."
            data["embodiment"] = f"I have the {clean_name} specialization loaded."
            data["starting_goal_seeds"] = [f"Verify {clean_name} capabilities and record baseline observations."]
            manifest_file.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        except Exception as exc:
            sys.stderr.write(f"Warning: Failed to customize plugin.json: {exc}\n")

    print(f"PASS: Scaffolded new plugin '{clean_name}' at '{target_dir}'.")
    return 0


def cmd_validate(
    target_path: Path | str,
    output_json: bool = False,
    current_api: str = CORE_API_VERSION,
) -> int:
    """Statically validate a plugin directory or manifest without executing code."""
    path = Path(target_path).resolve()
    errors: list[str] = []
    warnings: list[str] = []

    if not path.exists():
        errors.append(f"Target path does not exist: {path}")
        return _render_validation_result(False, "unknown", path, errors, warnings, output_json)

    if path.is_file():
        manifest_file = path
        plugin_dir = path.parent
    else:
        manifest_file = path / "plugin.json"
        plugin_dir = path

    if not manifest_file.exists():
        errors.append(f"Manifest file 'plugin.json' not found in '{plugin_dir}'.")
        return _render_validation_result(False, plugin_dir.name, plugin_dir, errors, warnings, output_json)

    # 1. Parse JSON
    try:
        raw = json.loads(manifest_file.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            errors.append("Manifest 'plugin.json' root must be a JSON object.")
            return _render_validation_result(False, plugin_dir.name, plugin_dir, errors, warnings, output_json)
    except Exception as exc:
        errors.append(f"Failed to parse 'plugin.json' as valid JSON: {exc}")
        return _render_validation_result(False, plugin_dir.name, plugin_dir, errors, warnings, output_json)

    # 2. Required fields
    name = str(raw.get("name", "")).strip()
    if not name:
        errors.append("Plugin 'name' is required.")
    elif not re.match(r"^[a-zA-Z0-9_-]+$", name):
        errors.append(f"Plugin 'name' must be alphanumeric identifier (got: {name!r}).")

    version = str(raw.get("version", "")).strip()
    if not version:
        errors.append("Plugin 'version' is required.")
    else:
        try:
            _parse_version(version)
        except Exception as exc:
            errors.append(f"Invalid plugin version '{version}': {exc}")

    # Core API range
    core_api = str(raw.get("core_api", "")).strip()
    if not core_api:
        errors.append("Plugin 'core_api' compatible range is required.")
    else:
        try:
            if not is_core_api_compatible(core_api, current_api=current_api):
                errors.append(
                    f"Plugin '{name}' core_api range '{core_api}' is incompatible with core version '{current_api}'."
                )
        except Exception as exc:
            errors.append(f"Invalid core_api version specification '{core_api}': {exc}")

    kind = str(raw.get("kind", "")).strip().lower()
    if not kind:
        errors.append("Plugin 'kind' is required.")
    elif kind not in VALID_KINDS:
        errors.append(f"Plugin 'kind' must be one of {sorted(VALID_KINDS)} (got: {kind!r}).")

    description = str(raw.get("description", "")).strip()
    if not description:
        errors.append("Plugin 'description' is required.")

    # Embodiment
    embodiment = str(raw.get("embodiment") or raw.get("embodiment_text", "")).strip()
    if not embodiment:
        errors.append("Plugin 'embodiment' text is required.")

    # 3. Tools validation
    tools = raw.get("tools")
    if not isinstance(tools, list):
        errors.append("Plugin 'tools' must be a list.")
    else:
        for idx, t in enumerate(tools):
            if not isinstance(t, dict):
                errors.append(f"Tool at index {idx} must be a dict.")
                continue
            t_name = str(t.get("name", "")).strip()
            if not t_name:
                errors.append(f"Tool at index {idx} requires a 'name'.")
            elif not re.match(r"^[a-zA-Z0-9_]+$", t_name):
                errors.append(f"Tool '{t_name}' contains invalid characters (allowed: alphanumeric, underscore).")
            elif t_name in CORE_TOOL_NAMES or f"{name}.{t_name}" in CORE_TOOL_NAMES:
                errors.append(f"Plugin tool '{t_name}' collides with reserved core tool name.")

    # 4. Sensors validation
    sensors = raw.get("sensors")
    if not isinstance(sensors, list):
        errors.append("Plugin 'sensors' must be a list.")
    else:
        for idx, s in enumerate(sensors):
            if not isinstance(s, dict):
                errors.append(f"Sensor at index {idx} must be a dict.")
                continue
            s_name = str(s.get("name", "")).strip()
            s_risk = str(s.get("risk_class", "")).strip().lower()
            if not s_name:
                errors.append(f"Sensor at index {idx} requires a 'name'.")
            if s_risk not in VALID_RISK_CLASSES:
                errors.append(f"Sensor '{s_name}' has invalid risk_class {s_risk!r}; must be one of {sorted(VALID_RISK_CLASSES)}.")
            if "reversible" not in s or not isinstance(s.get("reversible"), bool):
                errors.append(f"Sensor '{s_name}' requires boolean 'reversible' flag.")
            perm = str(s.get("required_permission_level", "")).strip()
            if not perm:
                errors.append(f"Sensor '{s_name}' requires 'required_permission_level'.")

    # 5. Actions validation
    actions = raw.get("actions")
    if not isinstance(actions, list):
        errors.append("Plugin 'actions' must be a list.")
    else:
        for idx, a in enumerate(actions):
            if not isinstance(a, dict):
                errors.append(f"Action at index {idx} must be a dict.")
                continue
            a_name = str(a.get("name", "")).strip()
            a_risk = str(a.get("risk_class", "")).strip().lower()
            if not a_name:
                errors.append(f"Action at index {idx} requires a 'name'.")
            if a_risk not in VALID_RISK_CLASSES:
                errors.append(f"Action '{a_name}' has invalid risk_class {a_risk!r}; must be one of {sorted(VALID_RISK_CLASSES)}.")
            if "reversible" not in a or not isinstance(a.get("reversible"), bool):
                errors.append(f"Action '{a_name}' requires boolean 'reversible' flag.")
            perm = str(a.get("required_permission_level", "")).strip()
            if not perm:
                errors.append(f"Action '{a_name}' requires 'required_permission_level'.")

    # 6. State directory security check
    state_dir = str(raw.get("state_dir", "")).strip()
    if state_dir:
        state_path = Path(state_dir)
        if state_path.is_absolute() or ".." in state_path.parts:
            errors.append(f"Plugin 'state_dir' must be a relative subdirectory, got: {state_dir!r}")

    # Commands validation (optional)
    raw_commands = raw.get("commands")
    if raw_commands is not None:
        if not isinstance(raw_commands, list):
            errors.append("Plugin 'commands' must be a list.")
        else:
            for idx, c in enumerate(raw_commands):
                if not isinstance(c, dict):
                    errors.append(f"Command at index {idx} must be a dict.")
                    continue
                c_name = str(c.get("name", "")).strip()
                if not c_name:
                    errors.append(f"Command at index {idx} requires a 'name'.")

    # 7. Tests folder verification
    tests_entry = str(raw.get("tests_entry_point", "")).strip()
    tests_dir = plugin_dir / "tests"
    if tests_entry:
        entry_file = plugin_dir / tests_entry
        if not entry_file.exists():
            errors.append(f"Declared tests_entry_point '{tests_entry}' does not exist.")
        elif entry_file.stat().st_size == 0:
            errors.append(f"Declared tests_entry_point '{tests_entry}' is an empty file.")

    if not tests_dir.exists() or not tests_dir.is_dir():
        if not tests_entry or (tests_entry and not (plugin_dir / tests_entry).exists()):
            errors.append(f"Plugin tests folder missing: '{tests_dir}' not found.")
    else:
        test_files = [
            f for f in tests_dir.rglob("*.py")
            if f.is_file() and (f.name.startswith("test_") or f.name.endswith("_test.py")) and f.stat().st_size > 0
        ]
        if not test_files and not (tests_entry and (plugin_dir / tests_entry).exists()):
            errors.append(f"Plugin tests folder '{tests_dir}' contains no non-empty test files (test_*.py).")

    is_valid = len(errors) == 0
    return _render_validation_result(is_valid, name or plugin_dir.name, plugin_dir, errors, warnings, output_json)


def _render_validation_result(
    is_valid: bool,
    name: str,
    path: Path,
    errors: list[str],
    warnings: list[str],
    output_json: bool,
) -> int:
    """Format and print validation results."""
    if output_json:
        data = {
            "valid": is_valid,
            "plugin": name,
            "path": str(path),
            "errors": errors,
            "warnings": warnings,
        }
        print(json.dumps(data, indent=2))
    else:
        if is_valid:
            print(f"PASS: Plugin '{name}' at '{path}' is valid.")
            for w in warnings:
                print(f"  Warning: {w}")
        else:
            print(f"FAIL: Plugin '{name}' at '{path}' failed validation:")
            for e in errors:
                print(f"  - {e}")
            for w in warnings:
                print(f"  Warning: {w}")
    return 0 if is_valid else 1


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
    shipped_d = Path(shipped_dir).resolve() if shipped_dir else (
        Path(__file__).resolve().parent if (Path(__file__).resolve().parent / "hello").exists() else Path("/opt/agent/plugins")
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


def cmd_check(
    workspace_dir: Path | str | None = None,
    shipped_dir: Path | str | None = None,
    output_json: bool = False,
    current_api: str = CORE_API_VERSION,
) -> int:
    """Statically check compatibility of all plugins against current core API version."""
    ws = Path(workspace_dir).resolve() if workspace_dir else Path.cwd()
    shipped_d = Path(shipped_dir).resolve() if shipped_dir else (
        Path(__file__).resolve().parent if (Path(__file__).resolve().parent / "hello").exists() else Path("/opt/agent/plugins")
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


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for python -m agent.plugins."""
    parser = argparse.ArgumentParser(
        prog="python -m agent.plugins",
        description="SELF Plugin SDK CLI: scaffold, validate, list, and check plugins.",
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # new
    p_new = subparsers.add_parser("new", help="Scaffold a new plugin from plugins/_template.")
    p_new.add_argument("name", help="Name of the new plugin (alphanumeric, underscores, hyphens).")
    p_new.add_argument("--dest", "-d", default=None, help="Destination directory (default: ./plugins/<name> or ./<name>).")
    p_new.add_argument("--template", "-t", default=None, help="Custom template directory override.")

    # validate
    p_val = subparsers.add_parser("validate", help="Statically validate a plugin manifest and files.")
    p_val.add_argument("path", help="Path to plugin directory or plugin.json.")
    p_val.add_argument("--json", action="store_true", help="Emit machine-readable JSON output.")

    # list
    p_list = subparsers.add_parser("list", help="List discovered plugins and hash pinning status.")
    p_list.add_argument("--workspace", default=None, help="Workspace directory.")
    p_list.add_argument("--config", default=None, help="Config directory containing plugins.json.")
    p_list.add_argument("--shipped", default=None, help="Shipped plugins directory.")
    p_list.add_argument("--json", action="store_true", help="Emit machine-readable JSON output.")

    # check
    p_chk = subparsers.add_parser("check", help="Check compatibility of plugins against the core version.")
    p_chk.add_argument("--workspace", default=None, help="Workspace directory.")
    p_chk.add_argument("--shipped", default=None, help="Shipped plugins directory.")
    p_chk.add_argument("--json", action="store_true", help="Emit machine-readable JSON output.")

    return parser


def main(argv: list[str] | None = None) -> int:
    """Parse command-line arguments and dispatch plugin SDK commands."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.subcommand == "new":
        return cmd_new(args.name, dest_dir=args.dest, template_dir=args.template)
    elif args.subcommand == "validate":
        return cmd_validate(args.path, output_json=args.json)
    elif args.subcommand == "list":
        return cmd_list(workspace_dir=args.workspace, config_dir=args.config, shipped_dir=args.shipped, output_json=args.json)
    elif args.subcommand == "check":
        return cmd_check(workspace_dir=args.workspace, shipped_dir=args.shipped, output_json=args.json)
    return 1


if __name__ == "__main__":
    sys.exit(main())
