"""Plugin draft scaffolding from template into workspace/plugin_dev/<name>/."""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from agent.infra.event_log import EventLogger
from agent.plugins.cli import _find_template_dir
from agent.plugins.manifest import VALID_KINDS


def scaffold_plugin_draft(
    dev_dir: Path,
    logger: EventLogger,
    name: str,
    kind: str = "skill",
    description: str = "",
) -> dict[str, Any]:
    """Scaffold a plugin draft in workspace/plugin_dev/<name>/ from template."""
    clean_name = str(name).strip()
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", clean_name):
        return {
            "ok": False,
            "error": f"Plugin name '{clean_name}' must be lowercase snake_case (letters, digits, underscore, max 64 chars).",
        }

    target_dir = dev_dir / clean_name
    if target_dir.exists():
        return {
            "ok": False,
            "error": f"Plugin draft directory '{target_dir}' already exists. Refusing to overwrite.",
        }

    tmpl = _find_template_dir()
    if tmpl is None or not tmpl.exists():
        return {"ok": False, "error": "Plugin template directory (_template) not found."}

    try:
        shutil.copytree(
            tmpl,
            target_dir,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", ".git*"),
        )
    except OSError as exc:
        return {"ok": False, "error": f"Failed to copy template to '{target_dir}': {exc}"}

    manifest_file = target_dir / "plugin.json"
    if manifest_file.exists():
        try:
            data = json.loads(manifest_file.read_text(encoding="utf-8"))
            data["name"] = clean_name
            data["kind"] = kind if kind in VALID_KINDS else "skill"
            data["description"] = description.strip() or f"{clean_name} plugin draft."
            data["embodiment"] = f"I have the {clean_name} specialization loaded."
            data["starting_goal_seeds"] = [f"Verify {clean_name} capabilities and record baseline observations."]
            manifest_file.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        except OSError as exc:
            return {"ok": False, "error": f"Failed to configure plugin.json: {exc}"}

    logger.log("plugin_scaffolded", name=clean_name, path=str(target_dir))
    return {
        "ok": True,
        "name": clean_name,
        "path": str(target_dir),
        "message": f"Plugin draft scaffolded at {target_dir}. Loader will never load from plugin_dev.",
    }
