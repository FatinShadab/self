"""Broker authorization request builder and verdict resolution for tool execution."""
from __future__ import annotations

from typing import Any

from agent.infra.permission_broker import ActionRequest, PermissionBroker, PermissionLevel
from agent.tools.permissions import REVERSIBLE_TOOL_NAMES, TOOL_PERMISSION_LEVELS


def build_action_request(
    name: str,
    arguments: dict[str, Any],
    plugins: Any = None,
) -> ActionRequest:
    """Construct an ActionRequest with resolved permission levels and reversibility flags."""
    source = "core"
    if name in {"run_shell", "read_file", "write_file", "list_dir", "http_get", "probe_local_ollama"}:
        source = "body"
    elif plugins is not None and (plugins.is_plugin_tool(name) or plugins.is_vanished_or_disabled_tool(name)):
        source = f"plugins.{plugins.get_plugin_for_tool(name)}"

    level = TOOL_PERMISSION_LEVELS.get(name, PermissionLevel.L2)
    reversible = name in REVERSIBLE_TOOL_NAMES

    if source.startswith("plugins.") and plugins is not None:
        p_name = plugins.get_plugin_for_tool(name)
        plugin_obj = plugins.active_plugins.get(p_name) or plugins.discovered.get(p_name)
        if plugin_obj is not None:
            for act in plugin_obj.manifest.actions:
                if act.name == name or f"{p_name}.{act.name}" == name:
                    level = PermissionLevel.from_value(act.required_permission_level)
                    reversible = act.reversible
                    break
            for sens in plugin_obj.manifest.sensors:
                if sens.name == name or f"{p_name}.{sens.name}" == name:
                    level = PermissionLevel.from_value(sens.required_permission_level)
                    reversible = sens.reversible
                    break

    dry_run = bool(arguments.get("dry_run", False))
    return ActionRequest(
        action=name,
        source=source,
        level=level,
        params=arguments,
        dry_run=dry_run,
        reversible=reversible,
    )


def authorize_tool_action(
    broker: PermissionBroker | None,
    action_request: ActionRequest | None,
) -> dict[str, Any] | None:
    """Check action authorization through the broker.

    Returns:
        Early response dict if blocked or in dry-run mode; None if authorized to proceed.
    """
    if broker is None or action_request is None:
        return None

    verdict = broker.authorize(action_request)
    if not verdict.allowed:
        return {"ok": False, "error": verdict.reason, "permission_denied": True}
    if verdict.dry_run:
        return {"ok": True, "dry_run": True, "message": f"Action '{action_request.action}' authorized in dry-run mode."}
    return None


def record_action_execution(
    broker: PermissionBroker | None,
    action_request: ActionRequest | None,
    safe_result: dict[str, Any],
) -> None:
    """Record execution outcome in the permission broker ledger."""
    if broker is not None and action_request is not None and not action_request.dry_run:
        broker.record_execution(
            action_request,
            success=bool(safe_result.get("ok", False)),
            reversible=action_request.reversible,
            error=safe_result.get("error"),
        )
