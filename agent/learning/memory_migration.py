"""Migrate old subservient/shared framing out of workspace/state/memory.jsonl."""
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def migrate_memory_store(workspace: str | Path = "workspace") -> dict[str, Any]:
    ws = Path(workspace)
    mem_path = ws / "state" / "memory.jsonl"
    if not mem_path.exists():
        raise FileNotFoundError(f"Missing memory file: {mem_path}")

    # Ensure timestamped backup
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_path = ws / "state" / f"memory.jsonl.{ts}.bak"
    shutil.copy2(mem_path, backup_path)

    with mem_path.open("r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    changes = []
    updated_lines = []

    for idx, line in enumerate(lines, 1):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            updated_lines.append(line)
            continue

        changed = False
        lesson = entry.get("lesson", "")
        old_lesson = lesson

        # Check line 457 or occurrences of 'ensures we have the source text'
        if "ensures we have the source text" in lesson.lower():
            lesson = lesson.replace(
                "ensures we have the source text",
                "ensures the agent retains the source text",
            )
            lesson = lesson.replace(
                "will let us confirm the service ordering",
                "will confirm the service ordering",
            )
            changed = True

        # Check line 501 or occurrences of 'This ensures we can continue mapping'
        if "this ensures we can continue mapping" in lesson.lower():
            lesson = lesson.replace(
                "This ensures we can continue mapping without waiting for a new tool.",
                "This ensures I can continue mapping without waiting for a new tool.",
            )
            lesson = lesson.replace(
                "this ensures we can continue mapping without waiting for a new tool.",
                "this ensures I can continue mapping without waiting for a new tool.",
            )
            changed = True

        tags = entry.get("tags", [])
        if "us" in tags:
            tags = [t for t in tags if t != "us"]
            entry["tags"] = tags
            changed = True

        if changed:
            entry["lesson"] = lesson
            new_line = json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n"
            updated_lines.append(new_line)
            changes.append({
                "line": idx,
                "timestamp": entry.get("timestamp"),
                "what_was_tried": entry.get("what_was_tried", "")[:80],
                "old_lesson_sample": old_lesson[:200],
                "new_lesson_sample": lesson[:200],
            })
        else:
            updated_lines.append(line)

    # Atomic write
    tmp_path = mem_path.with_suffix(".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        f.writelines(updated_lines)
    os.replace(tmp_path, mem_path)

    # Write audit log
    log_path = ws / "state" / "memory_framing_migration.log"
    with log_path.open("w", encoding="utf-8") as f:
        f.write(f"# Memory Framing Migration Log ({ts} UTC)\n\n")
        f.write(f"Backup saved to: {backup_path.name}\n")
        f.write(f"Total lines: {len(lines)}\n")
        f.write(f"Entries modified: {len(changes)}\n\n")
        for ch in changes:
            f.write(f"## Line {ch['line']} ({ch['timestamp']})\n")
            f.write(f"Tried: {ch['what_was_tried']}\n")
            f.write(f"Old snippet:\n{ch['old_lesson_sample']}\n\n")
            f.write(f"New snippet:\n{ch['new_lesson_sample']}\n\n")

    return {
        "ok": True,
        "backup": str(backup_path),
        "changes": changes,
        "total_lines": len(updated_lines),
    }
