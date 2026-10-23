"""Prompt 14 tagged state and bounded memory migration execution."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent.infra.state_migration.backup import create_backup
from agent.infra.state_migration.summary import deterministic_summary


def run_migration_p14(workspace: str | Path, backup_dir: str | Path | None = None) -> dict[str, Any]:
    """Execute a single-pass migration to tag state and bound memory lessons.

    Never modifies append-only logs (audit_trail.jsonl, actions.jsonl).
    Creates a timestamped backup with an exact manifest for byte-for-byte restore.
    """
    ws = Path(workspace).resolve()
    state_dir = ws / "state"
    tools_dir = ws / "tools"
    state_dir.mkdir(parents=True, exist_ok=True)

    backup_path, ts, manifest, backed_up = create_backup(ws, backup_dir)

    stats: dict[str, Any] = {
        "timestamp": ts,
        "backup_path": str(backup_path),
        "files_backed_up": len(backed_up),
        "memory_migrated": 0,
        "memory_bytes_before": 0,
        "memory_bytes_after": 0,
        "map_entries_tagged": 0,
        "plan_items_tagged": 0,
        "identity_interests_tagged": 0,
        "tools_meta_tagged": 0,
        "entries_with_report": 0,
        "entries_left_alone": 0,
        "entries_already_4000": 0,
    }

    # 1. Migrate memory.jsonl: bounded summary + report pointer + tags
    mem_path = state_dir / "memory.jsonl"
    reports_dir = state_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    if mem_path.exists():
        stats["memory_bytes_before"] = mem_path.stat().st_size
        raw_lines = mem_path.read_text(encoding="utf-8", errors="replace").splitlines()
        new_lines: list[str] = []

        for idx, line in enumerate(raw_lines):
            line_str = line.strip()
            if not line_str:
                continue
            try:
                rec = json.loads(line_str)
            except json.JSONDecodeError:
                new_lines.append(line_str)
                continue

            if isinstance(rec, dict):
                rec.setdefault("plugin", "core")
                rec.setdefault("body", "container")

                orig_lesson = rec.get("lesson", "")
                if "report_path" in rec:
                    # Already migrated - leave lesson and report_path unchanged (idempotent)
                    pass
                elif orig_lesson and len(orig_lesson) > 280:
                    report_file = f"report_migrated_{idx:05d}.txt"
                    report_rel = f"state/reports/{report_file}"
                    report_abs = ws / report_rel
                    if not report_abs.exists():
                        report_abs.write_text(orig_lesson, encoding="utf-8", newline="\n")
                    rec["report_path"] = report_rel
                    rec["lesson"] = deterministic_summary(orig_lesson)
                    stats["entries_with_report"] += 1
                    if len(orig_lesson) == 4000:
                        stats["entries_already_4000"] += 1
                elif orig_lesson:
                    stats["entries_left_alone"] += 1
                    if len(orig_lesson) == 4000:
                        stats["entries_already_4000"] += 1

                stats["memory_migrated"] += 1
                new_lines.append(json.dumps(rec, ensure_ascii=False, separators=(",", ":")))
            else:
                new_lines.append(line_str)

        tmp_mem = mem_path.with_suffix(".tmp")
        tmp_mem.write_text("\n".join(new_lines) + ("\n" if new_lines else ""), encoding="utf-8", newline="\n")
        tmp_mem.replace(mem_path)
        stats["memory_bytes_after"] = mem_path.stat().st_size

    # 2. Migrate map.json: tags + schema_version
    map_path = state_dir / "map.json"
    if map_path.exists():
        try:
            map_data = json.loads(map_path.read_text(encoding="utf-8"))
            if isinstance(map_data, dict):
                map_data["schema_version"] = 2
                entries = map_data.setdefault("entries", {})
                for ent in entries.values():
                    if isinstance(ent, dict):
                        ent.setdefault("plugin", "core")
                        ent.setdefault("body", "container")
                        stats["map_entries_tagged"] += 1
                tmp_map = map_path.with_suffix(".tmp")
                tmp_map.write_text(json.dumps(map_data, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
                tmp_map.replace(map_path)
        except (OSError, json.JSONDecodeError):
            pass

    # 3. Migrate plan.json: tags + schema_version
    plan_path = state_dir / "plan.json"
    if plan_path.exists():
        try:
            plan_data = json.loads(plan_path.read_text(encoding="utf-8"))
            if isinstance(plan_data, dict):
                plan_data["schema_version"] = 2
                items = plan_data.setdefault("items", [])
                for it in items:
                    if isinstance(it, dict):
                        it.setdefault("plugin", "core")
                        it.setdefault("body", "container")
                        stats["plan_items_tagged"] += 1
                tmp_plan = plan_path.with_suffix(".tmp")
                tmp_plan.write_text(json.dumps(plan_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
                tmp_plan.replace(plan_path)
        except (OSError, json.JSONDecodeError):
            pass

    # 4. Migrate identity.json: interests + plugin_embodiments + schema_version
    id_path = state_dir / "identity.json"
    if id_path.exists():
        try:
            id_data = json.loads(id_path.read_text(encoding="utf-8"))
            if isinstance(id_data, dict):
                id_data["schema_version"] = 2
                id_data.setdefault("plugin_embodiments", {})
                raw_interests = id_data.get("interests", [])
                tagged_interests: list[dict[str, Any]] = []
                for it in raw_interests:
                    if isinstance(it, str):
                        tagged_interests.append({"interest": it, "plugin": "core", "body": "container"})
                        stats["identity_interests_tagged"] += 1
                    elif isinstance(it, dict):
                        it.setdefault("plugin", "core")
                        it.setdefault("body", "container")
                        tagged_interests.append(it)
                        stats["identity_interests_tagged"] += 1
                id_data["interests"] = tagged_interests
                tmp_id = id_path.with_suffix(".tmp")
                tmp_id.write_text(json.dumps(id_data, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
                tmp_id.replace(id_path)
        except (OSError, json.JSONDecodeError):
            pass

    # 5. Migrate self_notes.md: ensure default tagging header/frontmatter
    notes_path = state_dir / "self_notes.md"
    if notes_path.exists():
        try:
            text = notes_path.read_text(encoding="utf-8")
            if not text.startswith("---") and not text.startswith("<!-- tags:"):
                tagged_text = "<!-- tags: plugin=core body=container -->\n" + text
                notes_path.write_text(tagged_text, encoding="utf-8", newline="\n")
        except OSError:
            pass

    # 6. Migrate tools/*/meta.json: tags
    if tools_dir.exists():
        for meta_file in tools_dir.rglob("meta.json"):
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                if isinstance(meta, dict):
                    meta.setdefault("plugin", "core")
                    meta.setdefault("body", "container")
                    stats["tools_meta_tagged"] += 1
                    tmp_tool = meta_file.with_suffix(".tmp")
                    tmp_tool.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
                    tmp_tool.replace(meta_file)
            except (OSError, json.JSONDecodeError):
                pass

    # 7. Write migration log
    log_file = state_dir / "migration_p14.log"
    log_content = (
        f"--- Migration P14 Log ---\n"
        f"Timestamp: {ts}\n"
        f"Schema Version: 2\n"
        f"Backup Directory: {backup_path}\n"
        f"Memory entries migrated: {stats['memory_migrated']}\n"
        f"Memory size change: {stats['memory_bytes_before']} bytes -> {stats['memory_bytes_after']} bytes\n"
        f"Map entries tagged: {stats['map_entries_tagged']}\n"
        f"Plan items tagged: {stats['plan_items_tagged']}\n"
        f"Identity interests tagged: {stats['identity_interests_tagged']}\n"
        f"Tool meta records tagged: {stats['tools_meta_tagged']}\n"
        f"Entries with report file: {stats['entries_with_report']}\n"
        f"Entries left unchanged (short lesson): {stats['entries_left_alone']}\n"
        f"Entries already at 4000 chars (upstream truncation): {stats['entries_already_4000']}\n\n"
        f"To restore pre-migration files byte-for-byte:\n"
        f"  python scripts/migrate_p14_tagged_state.py --restore {backup_path}\n"
    )
    log_file.write_text(log_content, encoding="utf-8", newline="\n")

    return stats
