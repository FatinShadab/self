"""Human-only plugin promotion from draft directory to installed plugins."""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any, Callable

from agent.infra.event_log import EventLogger
from agent.plugins.dev.environment import now_utc


def promote_draft_by_human(
    dev_dir: Path,
    plugins_dir: Path,
    workspace: Path,
    logger: EventLogger,
    validate_fn: Callable[[str], dict[str, Any]],
    name: str,
) -> dict[str, Any]:
    """Human-only promotion: copies validated draft to workspace/plugins/ as DISABLED."""
    clean_name = str(name).strip()
    draft_dir = dev_dir / clean_name
    target_dir = plugins_dir / clean_name

    if not draft_dir.exists():
        return {"ok": False, "error": f"Draft '{clean_name}' does not exist in workspace/plugin_dev/."}

    val_res = validate_fn(clean_name)
    if not val_res.get("valid"):
        return {
            "ok": False,
            "error": f"Cannot promote plugin '{clean_name}': validation failed:\n" + "\n".join(val_res.get("errors", [])),
        }

    if target_dir.exists():
        shutil.rmtree(target_dir)

    shutil.copytree(
        draft_dir,
        target_dir,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", ".git*"),
    )

    cfg_file = workspace / "config" / "plugins.json"
    if not cfg_file.exists():
        env_cfg = os.environ.get("SELF_CONFIG_DIR")
        if env_cfg:
            cfg_file = Path(env_cfg).resolve() / "plugins.json"
        elif Path("/config/plugins.json").exists():
            cfg_file = Path("/config/plugins.json")

    cfg_data: dict[str, Any] = {"plugins": {}}
    if cfg_file.exists():
        try:
            cfg_data = json.loads(cfg_file.read_text(encoding="utf-8"))
        except Exception:
            cfg_data = {"plugins": {}}

    plugins_entry = cfg_data.setdefault("plugins", {})
    plugins_entry[clean_name] = {
        "enabled": False,
        "promoted_at": now_utc(),
        "status": "DISABLED",
    }

    try:
        cfg_file.parent.mkdir(parents=True, exist_ok=True)
        cfg_file.write_text(json.dumps(cfg_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except OSError:
        pass

    diff_text = ""
    packet_file = draft_dir / "review_packet.json"
    if packet_file.exists():
        try:
            packet = json.loads(packet_file.read_text(encoding="utf-8"))
            diff_text = packet.get("diff", "")
        except Exception:
            pass

    logger.log("plugin_promoted", name=clean_name, target=str(target_dir))

    return {
        "ok": True,
        "name": clean_name,
        "target": str(target_dir),
        "status": "DISABLED",
        "diff": diff_text,
        "permission_summary": val_res.get("permission_summary"),
    }
