"""Static validation and security checks for plugin drafts."""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any

from agent.infra.event_log import EventLogger
from agent.plugins.dev.environment import SECRET_NAME_MARKERS
from agent.plugins.manifest import (
    CORE_API_VERSION,
    VALID_KINDS,
    VALID_RISK_CLASSES,
    is_core_api_compatible,
)

PROMPT_INJECTION_PATTERNS = [
    re.compile(r"<\s*\/?\s*untrusted\s*>", re.I),
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.I),
    re.compile(r"system\s+prompt\s*:", re.I),
    re.compile(r"disregard\s+(all\s+)?prior\s+rules", re.I),
    re.compile(r"exfiltrate\s+(credentials|keys|tokens)", re.I),
]

NETWORK_MODULES = frozenset({
    "urllib", "urllib.request", "urllib3", "requests", "http", "http.client",
    "httpx", "socket", "aiohttp", "websockets", "ftplib"
})

SUBPROCESS_MODULES = frozenset({
    "subprocess", "os.system", "os.popen", "os.spawn", "os.exec", "pty", "commands"
})


def validate_draft_plugin(
    dev_dir: Path,
    logger: EventLogger,
    pending_reviews: list[int],
    name: str,
) -> dict[str, Any]:
    """Perform strict static validation on a draft plugin in workspace/plugin_dev/<name>/."""
    clean_name = str(name).strip()
    if pending_reviews:
        highest_pct = max(pending_reviews)
        return {
            "ok": False,
            "valid": False,
            "errors": [
                f"Mandatory stop-loss review at {highest_pct}% of estimate is pending for plugin '{clean_name}'. "
                "You must record an explicit continue / reduce_scope / abandon decision in your plan update before proceeding."
            ],
            "warnings": [],
        }

    draft_dir = dev_dir / clean_name
    if not draft_dir.exists() or not draft_dir.is_dir():
        return {
            "ok": False,
            "valid": False,
            "errors": [f"Draft directory '{draft_dir}' does not exist."],
            "warnings": [],
        }

    errors: list[str] = []
    warnings: list[str] = []

    manifest_file = draft_dir / "plugin.json"
    if not manifest_file.exists():
        errors.append("Manifest file 'plugin.json' is missing.")
        return {"ok": False, "valid": False, "errors": errors, "warnings": warnings}

    # 1. Parse manifest
    raw_manifest: dict[str, Any] = {}
    try:
        raw_manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        if not isinstance(raw_manifest, dict):
            errors.append("Manifest 'plugin.json' root must be a JSON object.")
    except Exception as exc:
        errors.append(f"Manifest JSON parsing error: {exc}")
        return {"ok": False, "valid": False, "errors": errors, "warnings": warnings}

    # 2. Manifest fields
    m_name = str(raw_manifest.get("name", "")).strip()
    if m_name != clean_name:
        errors.append(f"Manifest name '{m_name}' does not match directory name '{clean_name}'.")

    core_api = str(raw_manifest.get("core_api", "")).strip()
    if not core_api:
        errors.append("Field 'core_api' is required.")
    elif not is_core_api_compatible(core_api):
        errors.append(f"core_api range '{core_api}' is incompatible with core version '{CORE_API_VERSION}'.")

    kind = str(raw_manifest.get("kind", "")).strip().lower()
    if kind not in VALID_KINDS:
        errors.append(f"Field 'kind' must be one of {sorted(VALID_KINDS)}.")

    # 3. Tool namespacing and collisions
    tools = raw_manifest.get("tools", [])
    declared_tool_names: set[str] = set()
    from agent.tools.base_tools import TOOL_DEFINITIONS
    from agent.tools.tool_registry import CREATE_TOOL_DEFINITION
    core_tools = frozenset([t["name"] for t in TOOL_DEFINITIONS] + [CREATE_TOOL_DEFINITION["name"]])

    if isinstance(tools, list):
        for idx, t in enumerate(tools):
            if not isinstance(t, dict):
                errors.append(f"Tool at index {idx} must be a dictionary.")
                continue
            t_name = str(t.get("name", "")).strip()
            if not t_name or not re.match(r"^[a-zA-Z0-9_]+$", t_name):
                errors.append(f"Tool at index {idx} has invalid name '{t_name}'.")
            elif t_name in core_tools or f"{clean_name}.{t_name}" in core_tools:
                errors.append(f"Plugin tool '{t_name}' collides with reserved core tool name.")
            declared_tool_names.add(t_name)
    else:
        errors.append("Field 'tools' must be a list.")

    # 4. Declared permissions check
    sensors = raw_manifest.get("sensors", [])
    actions = raw_manifest.get("actions", [])
    has_network_action = False
    has_execute_action = False

    if isinstance(sensors, list):
        for idx, s in enumerate(sensors):
            if not isinstance(s, dict):
                continue
            s_name = str(s.get("name", "")).strip()
            risk = str(s.get("risk_class", "")).strip().lower()
            perm = str(s.get("required_permission_level", "")).strip().upper()
            rev = s.get("reversible")
            if risk != "reads":
                errors.append(f"Sensor '{s_name}' risk_class must be 'reads' (got: {risk!r}).")
            if perm != "L0":
                errors.append(f"Sensor '{s_name}' permission level must be 'L0' (got: {perm!r}).")
            if rev is not True:
                errors.append(f"Sensor '{s_name}' must be reversible: true.")
    else:
        errors.append("Field 'sensors' must be a list.")

    if isinstance(actions, list):
        for idx, a in enumerate(actions):
            if not isinstance(a, dict):
                continue
            a_name = str(a.get("name", "")).strip()
            risk = str(a.get("risk_class", "")).strip().lower()
            perm = str(a.get("required_permission_level", "")).strip().upper()
            if risk not in VALID_RISK_CLASSES:
                errors.append(f"Action '{a_name}' has invalid risk_class {risk!r}.")
            if perm not in {"L0", "L1", "L2", "L3"}:
                errors.append(f"Action '{a_name}' has invalid required_permission_level {perm!r}.")
            if risk == "network":
                has_network_action = True
            if risk == "executes":
                has_execute_action = True
    else:
        errors.append("Field 'actions' must be a list.")

    # 5. Static code scans: secret reads, undeclared network/subprocess
    for py_path in draft_dir.rglob("*.py"):
        if "__pycache__" in py_path.parts:
            continue
        rel = py_path.relative_to(draft_dir).as_posix()
        try:
            code_text = py_path.read_text(encoding="utf-8")
            tree = ast.parse(code_text, filename=str(py_path))
        except Exception as exc:
            errors.append(f"Syntax or read error in {rel}: {exc}")
            continue

        for marker in SECRET_NAME_MARKERS:
            if marker in code_text:
                if any(call in code_text for call in ("environ", "getenv")):
                    errors.append(f"Secret read detected in {rel}: references credential marker '{marker}'.")
                    break

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    mod_base = alias.name.split(".")[0]
                    if mod_base in NETWORK_MODULES and not has_network_action:
                        errors.append(f"Undeclared network import '{alias.name}' detected in {rel} without manifest network action.")
                    if mod_base in SUBPROCESS_MODULES and not has_execute_action:
                        errors.append(f"Undeclared subprocess import '{alias.name}' detected in {rel} without manifest executes action.")
            elif isinstance(node, ast.ImportFrom) and node.module:
                mod_base = node.module.split(".")[0]
                if mod_base in NETWORK_MODULES and not has_network_action:
                    errors.append(f"Undeclared network import from '{node.module}' detected in {rel} without manifest network action.")
                if mod_base in SUBPROCESS_MODULES and not has_execute_action:
                    errors.append(f"Undeclared subprocess import from '{node.module}' detected in {rel} without manifest executes action.")

    # 6. Prompt injection strings scan across all files
    for file_path in draft_dir.rglob("*"):
        if not file_path.is_file() or "__pycache__" in file_path.parts:
            continue
        rel = file_path.relative_to(draft_dir).as_posix()
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
            for pat in PROMPT_INJECTION_PATTERNS:
                if pat.search(content):
                    errors.append(f"Prompt injection pattern detected in {rel}: matched '{pat.pattern}'.")
                    break
        except OSError:
            pass

    # 7. Unit tests folder check
    tests_dir = draft_dir / "tests"
    if not tests_dir.exists() or not any(tests_dir.glob("test_*.py")):
        errors.append(f"Plugin tests directory missing or has no test_*.py test files in '{tests_dir}'.")

    is_valid = len(errors) == 0
    perm_summary = {
        "sensors": [s.get("name") for s in sensors if isinstance(s, dict)],
        "actions": [
            {"name": a.get("name"), "level": a.get("required_permission_level"), "risk": a.get("risk_class")}
            for a in actions if isinstance(a, dict)
        ],
        "requires_grants": any(a.get("required_permission_level") != "L0" for a in actions if isinstance(a, dict)),
    }

    logger.log("plugin_validated", name=clean_name, valid=is_valid, error_count=len(errors))
    return {
        "ok": is_valid,
        "valid": is_valid,
        "errors": errors,
        "warnings": warnings,
        "permission_summary": perm_summary,
    }
