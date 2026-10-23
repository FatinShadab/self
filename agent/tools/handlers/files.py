"""File, shell, and network execution handlers with stop-loss and protected path guards."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from agent.tools.permissions import DEFAULT_OUTPUT_CAP


def check_is_core_path(path: Path, core_root: Path, agent_root: Path, workspace: Path, body: Any = None) -> bool:
    """Treat symlink and traversal variants of image-owned harness paths as protected."""
    checker = getattr(body, "_is_core_path", None)
    if callable(checker):
        return bool(checker(path))
    try:
        candidate = path.resolve(strict=False)
        if any(candidate.is_relative_to(root.resolve(strict=False)) for root in (core_root, agent_root)):
            return True
        for cfg in (Path("/config"), workspace / "config", workspace.parent / "config"):
            try:
                if candidate.is_relative_to(cfg.resolve(strict=False)):
                    return True
            except (OSError, ValueError):
                pass
        return False
    except OSError:
        return False


def handle_run_shell(body: Any, cmd: str, timeout: float = 30, plugin_dev: Any = None) -> dict[str, Any]:
    """Execute a shell command with plugin-dev stop-loss gating."""
    if plugin_dev is not None and hasattr(plugin_dev, "get_pending_stop_loss"):
        m = re.search(r"plugin_dev[/\\]([a-z0-9_]+)", str(cmd))
        if m:
            proj_name = m.group(1)
            pending = plugin_dev.get_pending_stop_loss(proj_name)
            if pending:
                return {
                    "ok": False,
                    "error": (
                        f"Plugin development for '{proj_name}' has reached stop-loss threshold ({pending[0]}%). "
                        f"Shell commands targeting plugin_dev/{proj_name} are blocked until a review decision "
                        "(continue, reduce_scope, abandon) is recorded via update_plan."
                    ),
                }
    return body.run_shell(cmd=cmd, timeout=timeout)


def handle_read_file(body: Any, path: str, max_chars: int = DEFAULT_OUTPUT_CAP) -> dict[str, Any]:
    """Read file content bounded by output cap."""
    return body.read_file(path=path, max_chars=max_chars)


def handle_write_file(
    body: Any,
    workspace: Path,
    path: str,
    content: str,
    append: bool = False,
    plugin_dev: Any = None,
    identity: Any = None,
) -> dict[str, Any]:
    """Write workspace file enforcing protected-path checks and plugin stop-loss."""
    from agent.opencode.sandbox import is_protected_path

    if is_protected_path(path, workspace=workspace):
        return {
            "ok": False,
            "error": f"Path '{path}' is protected against direct modification by agent tools.",
        }
    if plugin_dev is not None and hasattr(plugin_dev, "get_pending_stop_loss"):
        norm_p = str(path).replace("\\", "/")
        m = re.search(r"plugin_dev/([a-z0-9_]+)", norm_p)
        if m:
            proj_name = m.group(1)
            pending = plugin_dev.get_pending_stop_loss(proj_name)
            if pending:
                return {
                    "ok": False,
                    "error": (
                        f"Plugin development for '{proj_name}' has reached stop-loss threshold ({pending[0]}%). "
                        f"File modifications in plugin_dev/{proj_name} are blocked until a review decision "
                        "(continue, reduce_scope, abandon) is recorded via update_plan."
                    ),
                }
    if identity is not None and getattr(body, "identity", None) is None:
        body.identity = identity
    return body.write_file(path=path, content=content, append=append)


def handle_list_dir(body: Any, path: str, max_entries: int = 500) -> dict[str, Any]:
    """List directory entries up to bounded count without following links."""
    return body.list_dir(path=path, max_entries=max_entries)


def handle_http_get(body: Any, url: str, timeout: float = 20, max_chars: int = DEFAULT_OUTPUT_CAP) -> dict[str, Any]:
    """Fetch URL and record observable network access."""
    return body.http_get(url=url, timeout=timeout, max_chars=max_chars)
