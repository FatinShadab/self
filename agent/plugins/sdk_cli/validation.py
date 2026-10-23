"""Static validation of plugin manifests and directory structure."""
from __future__ import annotations

import json
import re
from pathlib import Path

from agent.plugins.manifest import (
    CORE_API_VERSION,
    VALID_KINDS,
    VALID_RISK_CLASSES,
    _parse_version,
    is_core_api_compatible,
)
from agent.plugins.manager import CORE_TOOL_NAMES


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
