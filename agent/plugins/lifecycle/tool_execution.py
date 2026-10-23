"""Dynamic plugin tool execution, permission broker checks, and vanished-tool handling."""
from __future__ import annotations

from typing import Any

from agent.plugins.lifecycle.models import Plugin


def get_active_tool_definitions(active_plugins: dict[str, Plugin]) -> list[dict[str, Any]]:
    """Return tool definitions for all currently enabled plugins."""
    specs: list[dict[str, Any]] = []
    for plugin in active_plugins.values():
        specs.extend(plugin.tool_specs)
    return specs


def is_plugin_tool_active(name: str, active_plugins: dict[str, Plugin]) -> bool:
    """Check if tool name belongs to any active plugin."""
    return any(name in plugin.tools for plugin in active_plugins.values())


def is_vanished_or_disabled_tool(
    name: str,
    active_plugins: dict[str, Plugin],
    vanished_plugins: set[str],
    refused_plugins: set[str],
    discovered: dict[str, Plugin],
) -> bool:
    """Check if tool belongs to a plugin that is disabled or vanished."""
    if "." not in name:
        return False
    plugin_name = name.split(".", 1)[0]
    if plugin_name in active_plugins:
        return False
    # If it was previously known, discovered, or in config
    if (
        plugin_name in vanished_plugins
        or plugin_name in refused_plugins
        or plugin_name in discovered
    ):
        return True
    return True


def get_plugin_for_tool(name: str) -> str:
    """Extract plugin name prefix from namespaced tool."""
    return name.split(".", 1)[0] if "." in name else name


def execute_plugin_tool_call(
    name: str,
    arguments: dict[str, Any],
    active_plugins: dict[str, Plugin],
    vanished_plugins: set[str],
    refused_plugins: set[str],
    discovered: dict[str, Plugin],
    broker: Any | None = None,
) -> dict[str, Any]:
    """Execute a dynamic plugin tool, or return structured observation if vanished."""
    if is_vanished_or_disabled_tool(name, active_plugins, vanished_plugins, refused_plugins, discovered):
        plugin_name = get_plugin_for_tool(name)
        return {"ok": False, "error": f"tool no longer available: plugin {plugin_name} disabled"}

    if broker is not None:
        from agent.infra.permission_broker import ActionRequest, PermissionLevel

        plugin_name = get_plugin_for_tool(name)
        plugin = active_plugins.get(plugin_name)
        level = PermissionLevel.L2
        reversible = False
        if plugin:
            for act in plugin.manifest.actions:
                if act.name == name or f"{plugin_name}.{act.name}" == name:
                    level = PermissionLevel.from_value(act.required_permission_level)
                    reversible = act.reversible
                    break
            for sens in plugin.manifest.sensors:
                if sens.name == name or f"{plugin_name}.{sens.name}" == name:
                    level = PermissionLevel.from_value(sens.required_permission_level)
                    reversible = sens.reversible
                    break
        dry_run = bool(arguments.get("dry_run", False))
        verdict = broker.authorize(
            ActionRequest(
                action=name,
                source=f"plugins.{plugin_name}",
                level=level,
                params=arguments,
                dry_run=dry_run,
                reversible=reversible,
            )
        )
        if not verdict.allowed:
            return {"ok": False, "error": verdict.reason, "permission_denied": True}
        if verdict.dry_run:
            return {"ok": True, "dry_run": True, "message": f"Plugin tool '{name}' authorized in dry-run mode."}

    for plugin in active_plugins.values():
        if name in plugin.tools:
            return plugin.tools[name](**arguments)

    plugin_name = get_plugin_for_tool(name)
    return {"ok": False, "error": f"tool no longer available: plugin {plugin_name} disabled"}
