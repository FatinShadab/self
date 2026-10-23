"""Deterministic plugin SHA-256 hash calculation."""
from __future__ import annotations

import hashlib
from pathlib import Path


def compute_plugin_hash(plugin_dir: Path) -> str:
    """Compute a deterministic SHA-256 hash of a plugin's full contents.

    Excludes the plugin's runtime state/ directory, __pycache__, and compiled files.
    """
    plugin_dir = Path(plugin_dir).resolve()
    if not plugin_dir.exists() or not plugin_dir.is_dir():
        raise FileNotFoundError(f"Plugin directory does not exist: {plugin_dir}")

    hasher = hashlib.sha256()
    files_to_hash: list[Path] = []

    for path in plugin_dir.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(plugin_dir)
        parts = rel.parts
        # Exclude runtime state/ directory and _archive directory
        if len(parts) > 0 and (parts[0] in {"state", "_archive", "_template"}):
            continue
        if "_archive" in parts or "_template" in parts:
            continue
        # Exclude __pycache__ and bytecode
        if "__pycache__" in parts or path.suffix in {".pyc", ".pyo", ".pyd"}:
            continue
        # Exclude hidden files / OS metadata
        if any(part.startswith(".") for part in parts):
            continue
        files_to_hash.append(path)

    files_to_hash.sort(key=lambda p: p.relative_to(plugin_dir).as_posix())

    for path in files_to_hash:
        rel_posix = path.relative_to(plugin_dir).as_posix()
        hasher.update(rel_posix.encode("utf-8") + b"\0")
        try:
            hasher.update(path.read_bytes())
        except OSError:
            pass

    return hasher.hexdigest()
