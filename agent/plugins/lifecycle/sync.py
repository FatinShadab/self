"""Cycle boundary synchronization and hash verification for discovered plugins."""
from __future__ import annotations

from typing import Any, Callable

from agent.infra.event_log import EventLogger
from agent.plugins.lifecycle.hashing import compute_plugin_hash
from agent.plugins.lifecycle.models import Plugin


def sync_plugins_at_cycle_boundary(
    discovered: dict[str, Plugin],
    active_plugins: dict[str, Plugin],
    refused_plugins: set[str],
    cfg: dict[str, Any],
    logger: EventLogger,
    enable_fn: Callable[[Plugin], bool],
    disable_fn: Callable[[Any], bool],
    plan_store: Any = None,
    learning_store: Any = None,
) -> None:
    """Sync discovered plugins against ./config/plugins.json and verify SHA-256 hashes.

    Called strictly at cycle boundaries.
    """
    plugins_cfg = cfg.get("plugins", {})

    for name, plugin in list(discovered.items()):
        entry = plugins_cfg.get(name, {})
        should_be_enabled = bool(entry.get("enabled", False))

        if should_be_enabled:
            if name in refused_plugins:
                continue

            # Hash check
            current_hash = compute_plugin_hash(plugin.plugin_dir)
            expected_hash = entry.get("hash", "")

            if expected_hash and current_hash != expected_hash:
                # Hash mismatch! Refuse to load until re-approved
                disable_fn(plugin)
                refused_plugins.add(name)
                logger.log(
                    "plugin_hash_mismatch",
                    plugin=name,
                    expected=expected_hash,
                    actual=current_hash,
                )
                continue

            # Valid hash -> enable
            if not plugin.is_enabled:
                ok = enable_fn(plugin)
                if ok:
                    if plan_store is not None:
                        plan_store.resume_plugin_goals(name)
                    if learning_store is not None:
                        learning_store.mark_facts_stale_for_body(name)
                else:
                    # Enable failed; goals stay suspended and plugin_load_failed logged
                    pass

        else:
            # Disabled in config
            if name in active_plugins or plugin.is_enabled:
                disable_fn(name)
                if plan_store is not None:
                    plan_store.suspend_plugin_goals(name)

    # Check for enabled plugins that failed discovery or were removed
    for cfg_name, entry in plugins_cfg.items():
        if entry.get("enabled", False) and cfg_name not in discovered:
            if cfg_name in active_plugins:
                disable_fn(cfg_name)
            if plan_store is not None:
                plan_store.suspend_plugin_goals(cfg_name)

    # Check for vanished plugins whose directories were removed
    for active_name in list(active_plugins):
        if active_name not in discovered:
            disable_fn(active_name)
            if plan_store is not None:
                plan_store.suspend_plugin_goals(active_name)
