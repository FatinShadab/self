"""Plugin scaffolding and template resolution."""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

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
        Path(__file__).resolve().parents[3] / "plugins" / "_template",
        Path("/opt/agent/plugins/_template"),
        Path(__file__).resolve().parent.parent / "_template",
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

    tmpl = _find_template_dir(template_dir)
    if tmpl is None:
        sys.stderr.write("Error: Plugin template directory 'plugins/_template' not found.\n")
        return 1

    if dest_dir is not None:
        d = Path(dest_dir).resolve()
        target_dir = d if d.name == clean_name else (d / clean_name)
    elif (Path.cwd() / "plugins").exists() and (Path.cwd() / "plugins").is_dir():
        target_dir = (Path.cwd() / "plugins" / clean_name).resolve()
    else:
        target_dir = (Path.cwd() / clean_name).resolve()

    if target_dir.exists():
        sys.stderr.write(f"Error: Destination directory '{target_dir}' already exists. Refusing to overwrite.\n")
        return 1

    try:
        shutil.copytree(
            tmpl,
            target_dir,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", ".git*"),
        )
    except OSError as exc:
        sys.stderr.write(f"Error copying template to '{target_dir}': {exc}\n")
        return 1

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
