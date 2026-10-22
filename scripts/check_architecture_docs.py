#!/usr/bin/env python3
"""check_architecture_docs.py - Fast static check to ensure system-map.json matches code."""

import argparse
import ast
import json
import re
import sys
from dataclasses import fields
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
MAP_FILE = REPO_ROOT / "docs" / "architecture" / "system-map.json"

def check():
    if not MAP_FILE.exists():
        print(f"FAIL: {MAP_FILE} does not exist.")
        return 1

    try:
        sys_map = json.loads(MAP_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"FAIL: {MAP_FILE} is not valid JSON: {exc}")
        return 1

    errors = []

    # 1. Check tools
    from agent.tools.base_tools import TOOL_DEFINITIONS
    from agent.tools.tool_registry import CREATE_TOOL_DEFINITION

    actual_tool_names = set(t["name"] for t in TOOL_DEFINITIONS) | {CREATE_TOOL_DEFINITION["name"]}
    map_tool_names = set(t["name"] for t in sys_map.get("tools", []))

    missing_tools = actual_tool_names - map_tool_names
    extra_tools = map_tool_names - actual_tool_names
    if missing_tools:
        errors.append(f"Tools in code but missing from system-map.json: {sorted(missing_tools)}")
    if extra_tools:
        errors.append(f"Tools in system-map.json but missing from code: {sorted(extra_tools)}")

    # 2. Check events
    actual_events = set()
    for p in REPO_ROOT.glob("agent/**/*.py"):
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        except Exception:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr in {"log", "_log_event"}:
                    if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                        actual_events.add(node.args[0].value)

    map_events = set(e["name"] for e in sys_map.get("events", []))
    missing_events = actual_events - map_events
    extra_events = map_events - actual_events
    if missing_events:
        errors.append(f"Events in code but missing from system-map.json: {sorted(missing_events)}")
    if extra_events:
        errors.append(f"Events in system-map.json but not found in code: {sorted(extra_events)}")

    # 3. Check env vars
    map_env_vars = set(v["name"] for v in sys_map.get("env_vars", []))
    for v in map_env_vars:
        if v.endswith("<MODEL>"):
            continue
        # verify it appears somewhere in the code
        found = False
        for p in REPO_ROOT.glob("agent/**/*.py"):
            if v in p.read_text(encoding="utf-8"):
                found = True
                break
        if not found:
            for p in [REPO_ROOT / "docker-compose.yml", REPO_ROOT / ".env.example"]:
                if p.exists() and v in p.read_text(encoding="utf-8"):
                    found = True
                    break
        if not found:
            errors.append(f"Env var {v} in system-map.json not found in agent code, docker-compose.yml, or .env.example")

    # 4. Check state files
    map_state_files = [f["path"] for f in sys_map.get("state_files", [])]
    for sf in map_state_files:
        name = Path(sf).name
        found = False
        for p in REPO_ROOT.glob("agent/**/*.py"):
            if name in p.read_text(encoding="utf-8"):
                found = True
                break
        if not found and not (REPO_ROOT / sf).exists():
            errors.append(f"State file {sf} not found in agent code or on disk")

    # 5. Check plugin manifest schema against docs/plugins/manifest-reference.md
    from agent.plugins.manifest import PluginManifest
    manifest_ref_file = REPO_ROOT / "docs" / "plugins" / "manifest-reference.md"
    manifest_fields = set()
    if not manifest_ref_file.exists():
        errors.append("docs/plugins/manifest-reference.md does not exist.")
    else:
        ref_text = manifest_ref_file.read_text(encoding="utf-8")
        manifest_fields = {f.name for f in fields(PluginManifest)}
        for mf in manifest_fields:
            if f"`{mf}`" not in ref_text:
                errors.append(f"PluginManifest field '{mf}' not documented in docs/plugins/manifest-reference.md")

    # 6. Check plugin CLI commands
    from agent.plugins.cli import build_parser
    parser = build_parser()
    expected_commands = {"new", "validate", "list", "check"}
    actual_commands = set()
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            actual_commands = set(action.choices.keys())
            break
    missing_cmds = expected_commands - actual_commands
    if missing_cmds:
        errors.append(f"Plugin CLI missing expected commands: {sorted(missing_cmds)}")

    if errors:
        print("FAIL: Architecture drift detected:")
        for err in errors:
            print(f"  - {err}")
        return 1

    print("PASS: docs/architecture/system-map.json is consistent with code.")
    print(f"  Tools verified: {len(map_tool_names)}")
    print(f"  Events verified: {len(map_events)}")
    print(f"  Env vars verified: {len(map_env_vars)}")
    print(f"  State files verified: {len(map_state_files)}")
    print(f"  Plugin manifest fields verified: {len(manifest_fields)}")
    print(f"  Plugin CLI commands verified: {len(actual_commands)}")
    return 0

if __name__ == "__main__":
    sys.exit(check())
