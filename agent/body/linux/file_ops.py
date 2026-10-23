"""Filesystem inspection, protected path validation, and file manipulation for containers."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from agent.infra.event_log import EventLogger


def is_core_path(path: Path, core_root: Path, agent_root: Path) -> bool:
    """Treat symlink and traversal variants of image-owned harness paths as protected."""
    try:
        candidate = path.resolve(strict=False)
        return any(
            candidate.is_relative_to(root.resolve(strict=False))
            for root in (core_root, agent_root)
        )
    except OSError:
        return False


def read_container_file(path: str, max_chars: int, output_cap: int) -> dict[str, Any]:
    """Read a file that passes path checks."""
    limit = max(1, min(int(max_chars), output_cap))
    file_path = Path(path)
    with file_path.open("r", encoding="utf-8", errors="replace") as handle:
        content = handle.read(limit + 1)
    return {
        "ok": True,
        "path": str(file_path),
        "content": content[:limit],
        "truncated": len(content) > limit,
    }


def write_container_file(
    path: str,
    content: str,
    append: bool,
    workspace: Path,
    core_root: Path,
    agent_root: Path,
    identity: Any,
    logger: EventLogger,
) -> dict[str, Any]:
    """Write a workspace file after enforcing path and size limits."""
    file_path = Path(path)
    if is_core_path(file_path, core_root, agent_root):
        raise PermissionError(
            "The image-owned /opt/agent harness (including /opt/agent/core) is protected. "
            "Save a diff with propose_core_patch so the human can review and apply it from the host."
        )
    from agent.opencode.sandbox import is_protected_path

    if is_protected_path(file_path, workspace=workspace):
        raise PermissionError(
            f"Path '{path}' is protected against direct modification by agent tools."
        )
    if identity is not None and getattr(identity, "is_managed_path", None) is not None:
        if identity.is_managed_path(file_path):
            raise PermissionError(
                "Identity-managed state cannot be overwritten through write_file. "
                "Preserve the append-only identity trail; the human may edit identity.json directly from the host, "
                "while the harness records evidence-backed reflection changes."
            )
    file_path.parent.mkdir(parents=True, exist_ok=True)
    safe_content = logger.redactor.known(content)
    with file_path.open("a" if append else "w", encoding="utf-8") as handle:
        written = handle.write(safe_content)
    try:
        relative = file_path.resolve().relative_to((workspace / "tools").resolve())
    except ValueError:
        relative = None
    if relative is not None:
        logger.log("tool_created" if not append else "tool_updated", path=str(file_path), bytes=written)
    return {
        "ok": True,
        "path": str(file_path),
        "chars_written": written,
        "bytes_written": written,
        "append": bool(append),
    }


def list_container_dir(path: str, max_entries: int) -> dict[str, Any]:
    """List directory entries up to a bounded count without following links."""
    limit = max(1, min(int(max_entries), 5_000))
    entries: list[dict[str, Any]] = []
    truncated = False
    with os.scandir(path) as iterator:
        for index, entry in enumerate(iterator):
            if index >= limit:
                truncated = True
                break
            item: dict[str, Any] = {
                "name": entry.name,
                "type": "dir" if entry.is_dir(follow_symlinks=False) else "file",
            }
            if entry.is_symlink():
                item["type"] = "symlink"
            elif item["type"] == "file":
                try:
                    item["size"] = entry.stat(follow_symlinks=False).st_size
                except OSError:
                    pass
            entries.append(item)
    entries.sort(key=lambda item: (item["type"], item["name"].lower()))
    return {"ok": True, "path": str(path), "entries": entries, "truncated": truncated}
