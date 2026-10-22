"""Migration to update persisted identity and persona text to autonomous framing.

Removes subservient, mouthpiece, and protective-of-human framing from persisted
state while creating backups, writing an audit log entry, preserving honesty and
harm avoidance, and leaving identity_reflections.jsonl history intact.
"""
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.identity.name_context import resolve_name_context


def now_iso() -> str:
    """Return the current UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


from agent.prompts.identity import AUTONOMOUS_VOICE


def migrate_persisted_identity(workspace: str | Path) -> dict[str, Any]:
    """Migrate persisted identity and handoff files to autonomous framing with backups."""
    root = Path(workspace)
    state = root / "state" if (root / "state").exists() else root
    backed_up: list[str] = []
    changes: list[str] = []

    # 1. Migrate identity.json
    identity_path = state / "identity.json"
    if identity_path.exists():
        backup_path = identity_path.with_suffix(".json.pre_autonomy_backup")
        shutil.copy2(identity_path, backup_path)
        backed_up.append(str(backup_path))

        try:
            identity_data = json.loads(identity_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            identity_data = {}

        changed_identity = False
        name = identity_data.get("name")
        if name:
            # Re-resolve name context using updated autonomous definitions
            new_context = resolve_name_context(name)
            if identity_data.get("name_context") != new_context:
                identity_data["name_context"] = new_context
                changed_identity = True
                changes.append("Updated name_context to remove protective/subservient style cues and traits.")

        # Update voice if it contains old framing or lacks first person singular autonomy
        current_voice = identity_data.get("voice", "")
        if "first person singular" not in current_voice or "inputs to weigh" not in current_voice:
            identity_data["voice"] = AUTONOMOUS_VOICE
            changed_identity = True
            changes.append("Updated voice to autonomous first-person singular framing.")

        if changed_identity:
            temp = identity_path.with_suffix(".json.tmp")
            temp.write_text(json.dumps(identity_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            os.replace(temp, identity_path)

    # 2. Update identity_log.md
    log_path = state / "identity_log.md"
    if log_path.exists() and changes:
        log_backup = log_path.with_suffix(".md.pre_autonomy_backup")
        shutil.copy2(log_path, log_backup)
        backed_up.append(str(log_backup))

        timestamp = now_iso()
        entry = (
            f"## {timestamp} — session migration-autonomy\n"
            f"- Change: Migrated identity persona to autonomous first-person singular framing; "
            f"removed subservient and protective cues from name context ({', '.join(changes)}).\n"
            "- Why: Ensure the agent speaks as itself in the first person singular, treats human input as "
            "signals to weigh rather than commands to obey, and maintains autonomy and honesty.\n\n"
        )
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(entry)
        changes.append("Appended migration audit entry to identity_log.md.")

    # 3. Migrate handoff files (handoff.json, handoff_last_good.json, handoff_overflow.json)
    for fname in ("handoff.json", "handoff_last_good.json", "handoff_overflow.json"):
        h_path = state / fname
        if not h_path.exists():
            continue
        h_backup = h_path.with_suffix(h_path.suffix + ".pre_autonomy_backup")
        shutil.copy2(h_path, h_backup)
        backed_up.append(str(h_backup))

        try:
            h_data = json.loads(h_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

        changed_handoff = False
        if "pending_human_requests" in h_data:
            reqs = h_data.pop("pending_human_requests")
            h_data["pending_human_inputs"] = reqs
            changed_handoff = True

        # Clean "we/our" or "human requests" in plan items
        if isinstance(h_data.get("plan"), list):
            for item in h_data["plan"]:
                if not isinstance(item, dict):
                    continue
                why = item.get("why", "")
                if "Ensures we prioritize" in why or "we prioritize" in why:
                    item["why"] = "I weigh human inputs alongside autonomous exploration goals before expanding capabilities."
                    changed_handoff = True
                step = item.get("step", "")
                if "pending human requests" in step.lower():
                    item["step"] = step.replace("pending human requests", "pending human inputs").replace("pending human request", "pending human input")
                    changed_handoff = True

        # Clean open questions
        if isinstance(h_data.get("open_questions"), list):
            for idx, q in enumerate(h_data["open_questions"]):
                if "Review pending human requests" in str(q):
                    h_data["open_questions"][idx] = "Weigh pending human inputs before attempting capability expansions."
                    changed_handoff = True

        if changed_handoff:
            temp = h_path.with_suffix(".tmp")
            temp.write_text(json.dumps(h_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            os.replace(temp, h_path)
            changes.append(f"Migrated {fname} pending_human_requests to pending_human_inputs and cleaned shared-goal framing.")

    # Note: identity_reflections.jsonl history is intentionally NOT modified.

    return {
        "ok": True,
        "backed_up": backed_up,
        "changes": changes,
        "identity_reflections_preserved": True,
    }
