"""Versioned migration and byte-for-byte restore for Prompt 14 tagged state and memory size bound."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

def deterministic_summary(text: str, max_chars: int = 280) -> str:
    """Produce a deterministic bounded summary of text without LLM or token spend."""
    if not text:
        return "Cycle completed without a textual report."
    clean = " ".join(text.strip().split())
    if len(clean) <= max_chars:
        return clean
    truncated = clean[:max_chars - 3]
    last_space = truncated.rfind(" ")
    if last_space > max_chars // 2:
        truncated = truncated[:last_space]
    return truncated + "..."


def sha256_file(path: Path) -> str:
    """Compute SHA-256 hash of a file's raw bytes."""
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def run_migration_p14(workspace: str | Path, backup_dir: str | Path | None = None) -> dict[str, Any]:
    """Execute a single-pass migration to tag state and bound memory lessons.

    Never modifies append-only logs (audit_trail.jsonl, actions.jsonl).
    Creates a timestamped backup with an exact manifest for byte-for-byte restore.
    """
    ws = Path(workspace).resolve()
    state_dir = ws / "state"
    tools_dir = ws / "tools"
    state_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = Path(backup_dir).resolve() if backup_dir else state_dir / "backups" / ts
    backup_path.mkdir(parents=True, exist_ok=True)

    # 1. Identify files to backup
    candidates: list[Path] = [
        state_dir / "memory.jsonl",
        state_dir / "map.json",
        state_dir / "plan.json",
        state_dir / "identity.json",
        state_dir / "self_notes.md",
    ]
    if tools_dir.exists():
        for meta_file in tools_dir.rglob("meta.json"):
            candidates.append(meta_file)

    manifest: dict[str, str] = {}
    backed_up: list[str] = []

    for file_path in candidates:
        if file_path.exists() and file_path.is_file():
            rel = file_path.relative_to(ws).as_posix()
            dest = backup_path / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file_path, dest)
            manifest[rel] = sha256_file(file_path)
            backed_up.append(rel)

    (backup_path / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

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
    }

    # 2. Migrate memory.jsonl: bounded summary + report pointer + tags
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
                if "report_path" not in rec and orig_lesson:
                    report_file = f"report_migrated_{idx:05d}.txt"
                    report_rel = f"state/reports/{report_file}"
                    report_abs = ws / report_rel
                    if not report_abs.exists():
                        report_abs.write_text(orig_lesson, encoding="utf-8")
                    rec["report_path"] = report_rel
                    rec["lesson"] = deterministic_summary(orig_lesson)
                elif "report_path" not in rec:
                    rec["lesson"] = deterministic_summary(orig_lesson)

                stats["memory_migrated"] += 1
                new_lines.append(json.dumps(rec, ensure_ascii=False, separators=(",", ":")))
            else:
                new_lines.append(line_str)

        tmp_mem = mem_path.with_suffix(".tmp")
        tmp_mem.write_text("\n".join(new_lines) + ("\n" if new_lines else ""), encoding="utf-8")
        tmp_mem.replace(mem_path)
        stats["memory_bytes_after"] = mem_path.stat().st_size

    # 3. Migrate map.json: tags + schema_version
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
                tmp_map.write_text(json.dumps(map_data, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
                tmp_map.replace(map_path)
        except (OSError, json.JSONDecodeError):
            pass

    # 4. Migrate plan.json: tags + schema_version
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
                tmp_plan.write_text(json.dumps(plan_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                tmp_plan.replace(plan_path)
        except (OSError, json.JSONDecodeError):
            pass

    # 5. Migrate identity.json: interests + plugin_embodiments + schema_version
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
                tmp_id.write_text(json.dumps(id_data, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
                tmp_id.replace(id_path)
        except (OSError, json.JSONDecodeError):
            pass

    # 6. Migrate self_notes.md: ensure default tagging header/frontmatter
    notes_path = state_dir / "self_notes.md"
    if notes_path.exists():
        try:
            text = notes_path.read_text(encoding="utf-8")
            if not text.startswith("---") and not text.startswith("<!-- tags:"):
                tagged_text = "<!-- tags: plugin=core body=container -->\n" + text
                notes_path.write_text(tagged_text, encoding="utf-8")
        except OSError:
            pass

    # 7. Migrate tools/*/meta.json: tags
    if tools_dir.exists():
        for meta_file in tools_dir.rglob("meta.json"):
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                if isinstance(meta, dict):
                    meta.setdefault("plugin", "core")
                    meta.setdefault("body", "container")
                    stats["tools_meta_tagged"] += 1
                    tmp_tool = meta_file.with_suffix(".tmp")
                    tmp_tool.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                    tmp_tool.replace(meta_file)
            except (OSError, json.JSONDecodeError):
                pass

    # 8. Write migration log
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
        f"Tool meta records tagged: {stats['tools_meta_tagged']}\n\n"
        f"To restore pre-migration files byte-for-byte:\n"
        f"  python scripts/migrate_p14_tagged_state.py --restore {backup_path}\n"
    )
    log_file.write_text(log_content, encoding="utf-8")

    return stats


def restore_migration_p14(workspace: str | Path, backup_dir: str | Path) -> dict[str, Any]:
    """Restore pre-migration files from timestamped backup and verify byte-for-byte equality."""
    ws = Path(workspace).resolve()
    backup_path = Path(backup_dir).resolve()

    manifest_path = backup_path / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Backup manifest not found: {manifest_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    restored_files: list[str] = []

    for rel_path, expected_hash in manifest.items():
        src = backup_path / rel_path
        dst = ws / rel_path
        if not src.exists():
            raise FileNotFoundError(f"Backup file missing: {src}")

        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

        actual_hash = sha256_file(dst)
        if actual_hash != expected_hash:
            raise ValueError(
                f"Byte-for-byte verification failed for {rel_path}!\n"
                f"Expected SHA-256: {expected_hash}\n"
                f"Actual SHA-256:   {actual_hash}"
            )
        restored_files.append(rel_path)

    return {
        "restored_count": len(restored_files),
        "backup_path": str(backup_path),
        "verified": True,
        "files": restored_files,
    }
