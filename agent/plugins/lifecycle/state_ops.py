"""Plugin runtime state transitions: activation, deactivation, removal, and command routing."""
from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from agent.infra.event_log import EventLogger
from agent.plugins.lifecycle.hashing import compute_plugin_hash
from agent.plugins.lifecycle.models import Plugin
from agent.plugins.manifest import RESERVED_SLASH_COMMANDS


def enable_plugin_runtime(
    plugin: Plugin,
    active_plugins: dict[str, Plugin],
    vanished_plugins: set[str],
    workspace: Path,
    logger: EventLogger,
    register_command_fn: Callable[[str, str, Callable[[str], str]], None],
    load_plugin_fn: Callable[[Plugin], bool],
) -> bool:
    """Call on_enable hook and activate plugin."""
    if plugin.is_enabled:
        return True

    if not load_plugin_fn(plugin):
        return False

    # Run on_enable hook if present
    if plugin.module and hasattr(plugin.module, "on_enable"):
        try:
            ctx = {
                "name": plugin.manifest.name,
                "version": plugin.manifest.version,
                "workspace": workspace,
                "state_dir": plugin.state_dir,
                "logger": logger,
                "register_command": lambda cmd, fn: register_command_fn(plugin.manifest.name, cmd, fn),
            }
            plugin.module.on_enable(ctx)
        except Exception as exc:
            logger.log("plugin_load_failed", plugin=plugin.manifest.name, error=f"on_enable failed: {exc}")
            plugin.load_error = str(exc)
            return False

    plugin.is_enabled = True
    active_plugins[plugin.manifest.name] = plugin
    vanished_plugins.discard(plugin.manifest.name)

    # Register manifest slash commands
    for cmd in plugin.manifest.commands:
        c_name = cmd.name.lstrip("/")
        handler = None
        if plugin.module:
            handler = (
                getattr(plugin.module, f"handle_{c_name}_command", None)
                or getattr(plugin.module, f"{c_name}_command", None)
                or getattr(plugin.module, "handle_command", None)
            )
        if handler is not None:
            register_command_fn(plugin.manifest.name, c_name, handler)

    logger.log(
        "plugin_enabled",
        plugin=plugin.manifest.name,
        version=plugin.manifest.version,
        hash=compute_plugin_hash(plugin.plugin_dir) if plugin.plugin_dir.exists() else "",
    )
    return True


def disable_plugin_runtime(
    plugin_or_name: Plugin | str,
    active_plugins: dict[str, Plugin],
    discovered: dict[str, Plugin],
    vanished_plugins: set[str],
    workspace: Path,
    logger: EventLogger,
    unregister_commands_fn: Callable[[str], None],
    register_command_fn: Callable[[str, str, Callable[[str], str]], None],
) -> bool:
    """Call on_disable hook and deactivate plugin."""
    name = plugin_or_name if isinstance(plugin_or_name, str) else plugin_or_name.manifest.name
    plugin = active_plugins.get(name) or discovered.get(name)
    if plugin is None:
        return False

    if plugin.is_enabled:
        if plugin.module and hasattr(plugin.module, "on_disable"):
            try:
                ctx = {
                    "name": plugin.manifest.name,
                    "version": plugin.manifest.version,
                    "workspace": workspace,
                    "state_dir": plugin.state_dir,
                    "logger": logger,
                    "register_command": lambda cmd, fn: register_command_fn(plugin.manifest.name, cmd, fn),
                }
                plugin.module.on_disable(ctx)
            except Exception as exc:
                logger.log("plugin_load_failed", plugin=name, error=f"on_disable failed: {exc}")
        plugin.is_enabled = False
        unregister_commands_fn(name)
        active_plugins.pop(name, None)
        vanished_plugins.add(name)
        logger.log("plugin_disabled", plugin=name)
    return True


def remove_plugin_runtime(
    name: str,
    discovered: dict[str, Plugin],
    active_plugins: dict[str, Plugin],
    workspace_plugins_dir: Path,
    purge: bool,
    confirmed: bool,
    logger: EventLogger,
    cleanup_pointers_fn: Callable[[str], None],
    disable_plugin_fn: Callable[[str], bool],
) -> bool:
    """Disable and remove plugin folder.

    Archives the plugin's folder and state to workspace/plugins/_archive/<name>-<timestamp>/
    unless purge=True and confirmed=True.
    """
    disable_plugin_fn(name)
    plugin = discovered.pop(name, None)
    plugin_dir = plugin.plugin_dir if plugin else (workspace_plugins_dir / name)
    state_dir = plugin.state_dir if plugin else (workspace_plugins_dir / name / "state")

    if plugin and plugin.is_shipped:
        return False

    if not plugin_dir.exists() and not (state_dir and state_dir.exists()):
        return False

    if purge and confirmed:
        if plugin_dir.exists():
            shutil.rmtree(plugin_dir, ignore_errors=True)
        if state_dir and state_dir.exists():
            shutil.rmtree(state_dir, ignore_errors=True)
        cleanup_pointers_fn(name)
        logger.log("plugin_removed", plugin=name, mode="purged")
        return True
    else:
        # Default: Archive
        archive_base = workspace_plugins_dir / "_archive"
        archive_base.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        target = archive_base / f"{name}-{ts}"
        target.mkdir(parents=True, exist_ok=True)
        if plugin_dir.exists():
            shutil.copytree(plugin_dir, target / "plugin", dirs_exist_ok=True)
            shutil.rmtree(plugin_dir, ignore_errors=True)
        if state_dir and state_dir.exists() and state_dir != (plugin_dir / "state"):
            shutil.copytree(state_dir, target / "state", dirs_exist_ok=True)
            shutil.rmtree(state_dir, ignore_errors=True)
        cleanup_pointers_fn(name)
        logger.log("plugin_removed", plugin=name, mode="archived", archive_path=str(target))
        return True


def cleanup_removed_pointers(
    name: str,
    active_plugins: dict[str, Plugin],
    vanished_plugins: set[str],
    refused_plugins: set[str],
    read_config_fn: Callable[[], dict[str, Any]],
    write_config_fn: Callable[[dict[str, Any]], None],
) -> None:
    """Ensure core no longer references paths that no longer exist for removed plugin."""
    active_plugins.pop(name, None)
    vanished_plugins.discard(name)
    refused_plugins.discard(name)
    cfg = read_config_fn()
    plugins_cfg = cfg.get("plugins", {})
    if name in plugins_cfg:
        plugins_cfg[name]["enabled"] = False
        plugins_cfg[name]["removed"] = True
        try:
            write_config_fn(cfg)
        except OSError:
            pass


def dispatch_slash_command(
    line: str,
    active_commands: dict[str, tuple[str, Callable[[str], str]]],
    discovered: dict[str, Plugin],
    logger: EventLogger,
) -> str | None:
    """Dispatch slash command to active plugin handler if registered.

    Returns string response from handler, or None if unrecognized.
    """
    raw = line.strip()
    if not raw.startswith("/"):
        return None
    parts = raw[1:].split(None, 1)
    if not parts:
        return None
    cmd_name = parts[0]
    cmd_args = parts[1] if len(parts) > 1 else ""
    full_cmd = f"{cmd_name} {cmd_args}".strip().lower()

    if cmd_name.lower() in RESERVED_SLASH_COMMANDS or full_cmd in RESERVED_SLASH_COMMANDS:
        return None

    if cmd_name in active_commands:
        plugin_name, handler = active_commands[cmd_name]
        try:
            res = handler(cmd_args)
            return str(res)
        except Exception as exc:
            logger.log("plugin_command_error", plugin=plugin_name, command=cmd_name, error=str(exc))
            return f"Error executing /{cmd_name}: {exc}"

    # If command belongs to a known but disabled plugin, give a helpful hint
    for p_name, p in discovered.items():
        if not p.is_enabled:
            for c in p.manifest.commands:
                if c.name.lstrip("/") == cmd_name:
                    return f"Command '/{cmd_name}' belongs to plugin '{p_name}', which is currently disabled. Enable it with /plugins enable {p_name}."

    return None
