"""Backup creation and byte-for-byte restore verification for state files."""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.infra.state_migration.hashing import sha256_file


def create_backup(
    workspace: Path,
    backup_dir: str | Path | None = None,
) -> tuple[Path, str, dict[str, str], list[str]]:
    """Create timestamped backup and backup_manifest.json with SHA-256 hashes."""
    state_dir = workspace / "state"
    tools_dir = workspace / "tools"
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
            rel = file_path.relative_to(workspace).as_posix()
            dest = backup_path / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file_path, dest)
            manifest[rel] = sha256_file(file_path)
            backed_up.append(rel)

    manifest_json = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    (backup_path / "backup_manifest.json").write_text(manifest_json, encoding="utf-8", newline="\n")

    return backup_path, ts, manifest, backed_up


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
