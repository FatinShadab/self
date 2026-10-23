"""Discovery of plugin directories and manifests."""
from __future__ import annotations

from pathlib import Path

from agent.infra.event_log import EventLogger
from agent.plugins.lifecycle.models import Plugin
from agent.plugins.manifest import PluginManifestValidationError, parse_manifest


def discover_single_plugin_dir(
    plugin_dir: Path,
    is_shipped: bool,
    workspace: Path,
    logger: EventLogger,
    failed_plugins: dict[str, str],
) -> Plugin | None:
    """Parse and validate a single plugin directory manifest."""
    if "plugin_dev" in plugin_dir.parts:
        return None
    manifest_file = plugin_dir / "plugin.json"
    try:
        manifest = parse_manifest(manifest_file)
    except PluginManifestValidationError as exc:
        logger.log("plugin_load_failed", plugin=plugin_dir.name, error=str(exc))
        failed_plugins[plugin_dir.name] = str(exc)
        return None
    except Exception as exc:
        logger.log("plugin_load_failed", plugin=plugin_dir.name, error=f"Unexpected error: {exc}")
        failed_plugins[plugin_dir.name] = str(exc)
        return None

    state_dir = workspace / "plugins" / manifest.name / "state"

    return Plugin(
        manifest=manifest,
        plugin_dir=plugin_dir,
        is_shipped=is_shipped,
        state_dir=state_dir,
    )


def discover_plugins(
    shipped_dir: Path,
    workspace_plugins_dir: Path,
    workspace: Path,
    active_plugins: dict[str, Plugin],
    logger: EventLogger,
    failed_plugins: dict[str, str],
) -> dict[str, Plugin]:
    """Scan shipped and workspace directories for plugin.json manifests."""
    discovered: dict[str, Plugin] = {}
    failed_plugins.clear()

    # 1. Shipped plugins (read-only image content)
    if shipped_dir.exists() and shipped_dir.is_dir():
        search_dirs = [shipped_dir]
        examples_dir = shipped_dir / "examples"
        if examples_dir.exists() and examples_dir.is_dir():
            search_dirs.append(examples_dir)
        for s_dir in search_dirs:
            for entry in s_dir.iterdir():
                if entry.name in {"_archive", "_template", "examples"} or entry.name.startswith(('_', '.')):
                    continue
                if entry.is_dir() and (entry / "plugin.json").exists():
                    p = discover_single_plugin_dir(
                        entry,
                        is_shipped=True,
                        workspace=workspace,
                        logger=logger,
                        failed_plugins=failed_plugins,
                    )
                    if p:
                        if p.manifest.name in active_plugins:
                            active = active_plugins[p.manifest.name]
                            active.manifest = p.manifest
                            active.plugin_dir = p.plugin_dir
                            discovered[p.manifest.name] = active
                        else:
                            discovered[p.manifest.name] = p

    # 2. Workspace plugins (human-installed under workspace/plugins/<name>)
    if workspace_plugins_dir.exists() and workspace_plugins_dir.is_dir():
        ws_search_dirs = [workspace_plugins_dir]
        ws_examples = workspace_plugins_dir / "examples"
        if ws_examples.exists() and ws_examples.is_dir():
            ws_search_dirs.append(ws_examples)
        for ws_dir in ws_search_dirs:
            for entry in ws_dir.iterdir():
                if entry.name in {"_archive", "_template", "examples"} or entry.name.startswith(('_', '.')):
                    continue
                if entry.is_dir() and (entry / "plugin.json").exists():
                    p = discover_single_plugin_dir(
                        entry,
                        is_shipped=False,
                        workspace=workspace,
                        logger=logger,
                        failed_plugins=failed_plugins,
                    )
                    if p:
                        if p.manifest.name in active_plugins:
                            active = active_plugins[p.manifest.name]
                            active.manifest = p.manifest
                            active.plugin_dir = p.plugin_dir
                            discovered[p.manifest.name] = active
                        else:
                            discovered[p.manifest.name] = p

    return discovered
