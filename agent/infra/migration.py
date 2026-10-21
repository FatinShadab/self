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
    """Produce a deterministic bounded summary of cycle-report text.

    Rules (applied in order):
    1. Empty input → sentinel string.
    2. Already ≤ max_chars → returned unchanged (no report file).
    3. Strip markdown noise and boilerplate header lines.
    4. Prefer a "findings" section if one is present.
    5. Otherwise: first sentence + (if room) last sentence.
    6. Cut at a sentence/clause boundary; append "…" only when truncated.
    """
    import re

    if not text:
        return "Cycle completed without a textual report."

    # ── 1. Collapse unicode non-breaking / thin spaces to regular space ──────
    text = text.replace("\u00a0", " ").replace("\u202f", " ").replace("\u2011", "-")

    # ── 2. Line cleaning & section parsing ───────────────────────────────────
    _MD_INLINE = re.compile(r"\*{1,2}([^*]*?)\*{1,2}|`([^`]*)`")
    _MD_HEADER = re.compile(r"^#+\s*")
    _MD_LIST   = re.compile(r"^\s*(\d+\.|\d+\)|\*|-|\+|[>|])\s+")

    def clean_text(s: str) -> str:
        s = _MD_HEADER.sub("", s)
        s = _MD_LIST.sub("", s)
        s = _MD_INLINE.sub(lambda m: m.group(1) or m.group(2) or "", s)
        return s.strip()

    # Priority ranking for findings sections:
    # Rank 1: Direct discoveries/findings
    _P1 = re.compile(
        r"^(?:what\s+i\s+discovered|discoveries|verified\s+discoveries|key\s+verified\s+findings|findings|what\s+i\s+learned|new\s+knowledge|new\s+verified\s+entries)",
        re.IGNORECASE,
    )
    # Rank 2: Observations / explored
    _P2 = re.compile(
        r"^(?:recorded\s+observation|what\s+i\s+observed|what\s+i\s+explored|lesson|result)",
        re.IGNORECASE,
    )
    # Rank 3: Actions / what I did / narrative
    _P3 = re.compile(
        r"^(?:what\s+i\s+did|action\s+taken|narrative|narration)",
        re.IGNORECASE,
    )
    # Rank 4: Next steps (fallback if no findings/actions)
    _P4 = re.compile(
        r"^(?:(?:best\s+)?next\s+(?:steps?|actions?|recommended)|what[’\']?s\s+next)",
        re.IGNORECASE,
    )

    # Title lines to ignore as sections
    _TITLE = re.compile(
        r"^(?:cycle\s*[\u2011\-]?\s*\d+|exploration\s+cycle\s*\d+)",
        re.IGNORECASE,
    )

    sections: list[tuple[int, str, list[str]]] = []
    current_rank = 3
    current_header = "body"
    current_lines: list[str] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        cleaned = clean_text(line)
        if not cleaned:
            continue

        hdr_candidate = cleaned.strip(":*# -")

        if _TITLE.match(hdr_candidate):
            continue

        is_header = False
        rank = 3
        if _P1.match(hdr_candidate):
            is_header = True
            rank = 1
        elif _P2.match(hdr_candidate):
            is_header = True
            rank = 2
        elif _P3.match(hdr_candidate):
            is_header = True
            rank = 3
        elif _P4.match(hdr_candidate):
            is_header = True
            rank = 4

        if is_header:
            if current_lines:
                sections.append((current_rank, current_header, current_lines))
            current_rank = rank
            current_header = hdr_candidate
            current_lines = []
            colon_idx = cleaned.find(":")
            if colon_idx != -1 and colon_idx < len(cleaned) - 1:
                after_col = cleaned[colon_idx + 1 :].strip()
                if after_col:
                    current_lines.append(after_col)
        else:
            current_lines.append(cleaned)

    if current_lines:
        sections.append((current_rank, current_header, current_lines))

    # Pick the best section by rank
    sections.sort(key=lambda s: s[0])

    chosen_rank = 3
    chosen_lines: list[str] = []
    if sections:
        chosen_rank = sections[0][0]
        chosen_lines = sections[0][2]

    body = " ".join(chosen_lines)
    body = re.sub(r"\s{2,}", " ", body).strip()

    if not body:
        body_lines = [
            clean_text(l)
            for l in text.splitlines()
            if clean_text(l) and not _TITLE.match(clean_text(l))
        ]
        body = " ".join(body_lines)
        body = re.sub(r"\s{2,}", " ", body).strip()
        chosen_rank = 3

    if chosen_rank >= 3 and len(body) > max_chars:
        # If no preferred findings section was found and body is long:
        # Take first sentence of the body plus the last sentence
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Za-z0-9])", body) if s.strip()]
        if len(sentences) >= 3:
            combined = f"{sentences[0]} … {sentences[-1]}"
            if len(combined) <= max_chars:
                return combined
            body = combined
        elif len(sentences) == 2:
            combined = f"{sentences[0]} {sentences[1]}"
            if len(combined) <= max_chars:
                return combined
            body = combined

    if len(body) <= max_chars:
        return body

    # ── 5. Cut at a boundary ─────────────────────────────────────────────────
    budget = max_chars - 1  # leave room for ellipsis char
    window_start = budget - max(1, budget // 5)  # last 20 % of budget

    # Prefer sentence-end boundary (. ! ?)
    for end_char in ".!?":
        idx = body.rfind(end_char, window_start, budget)
        if idx != -1:
            return body[: idx + 1] + "…"

    # Fall back to clause boundary (; ,)
    for end_char in ";,":
        idx = body.rfind(end_char, window_start, budget)
        if idx != -1:
            return body[: idx + 1] + "…"

    # Fall back to word boundary
    idx = body.rfind(" ", window_start, budget)
    if idx != -1:
        return body[:idx] + "…"

    # Hard cut
    return body[:budget] + "…"


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

    base_ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if backup_dir:
        backup_path = Path(backup_dir).resolve()
        ts = backup_path.name
    else:
        backup_path = state_dir / "backups" / base_ts
        counter = 1
        while backup_path.exists():
            backup_path = state_dir / "backups" / f"{base_ts}_{counter}"
            counter += 1
        ts = backup_path.name
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

    manifest_json = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    (backup_path / "backup_manifest.json").write_text(manifest_json, encoding="utf-8", newline="\n")

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
                if "report_path" in rec:
                    # Already migrated – leave lesson and report_path unchanged (idempotent)
                    pass
                elif orig_lesson and len(orig_lesson) > 280:
                    # Needs bounding: write full report, store summary in lesson
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
                    # Short lesson – keep as-is, no report file
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
                tmp_map.write_text(json.dumps(map_data, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
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
                tmp_plan.write_text(json.dumps(plan_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
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
                tmp_id.write_text(json.dumps(id_data, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
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
                notes_path.write_text(tagged_text, encoding="utf-8", newline="\n")
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
                    tmp_tool.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
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
        f"Tool meta records tagged: {stats['tools_meta_tagged']}\n"
        f"Entries with report file: {stats['entries_with_report']}\n"
        f"Entries left unchanged (short lesson): {stats['entries_left_alone']}\n"
        f"Entries already at 4000 chars (upstream truncation): {stats['entries_already_4000']}\n\n"
        f"To restore pre-migration files byte-for-byte:\n"
        f"  python scripts/migrate_p14_tagged_state.py --restore {backup_path}\n"
    )
    log_file.write_text(log_content, encoding="utf-8", newline="\n")

    return stats


def restore_migration_p14(workspace: str | Path, backup_dir: str | Path) -> dict[str, Any]:
    """Restore pre-migration files from timestamped backup and verify byte-for-byte equality."""
    ws = Path(workspace).resolve()
    backup_path = Path(backup_dir).resolve()

    manifest_path = backup_path / "backup_manifest.json"
    if not manifest_path.exists():
        manifest_path = backup_path / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Backup manifest not found in: {backup_path}")

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
