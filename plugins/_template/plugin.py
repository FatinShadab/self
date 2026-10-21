"""Template plugin implementation.

This module provides sample implementations for tools, sensors, actions, and lifecycle hooks.
Plugin authors should replace or extend these implementations to match their specialization.
"""
from __future__ import annotations

from typing import Any


def sample_tool(message: str = "hello") -> dict[str, Any]:
    """Sample tool handler that echoes an input message.

    Tools registered in plugin.json are exposed to the agent loop under namespaced
    names (<plugin_name>.<tool_name>). Tool outputs must be JSON-serializable dictionaries.
    """
    if not isinstance(message, str):
        return {"ok": False, "error": "message argument must be a string"}
    return {
        "ok": True,
        "echo": message,
        "status": "received",
    }


def sample_sensor() -> dict[str, Any]:
    """Sample sensor function providing telemetry observation.

    Sensors represent passive observations (L0 permission level). They should be
    strictly read-only and non-destructive.
    """
    return {
        "ok": True,
        "operational": True,
        "mode": "simulated",
        "metric": 42.0,
    }


def sample_action(parameter: str = "default") -> dict[str, Any]:
    """Sample action function executing an operation.

    Actions represent active operations (L1+ permission levels). Reversible actions
    should document how modifications can be undone.
    """
    return {
        "ok": True,
        "action": "sample_action",
        "parameter": parameter,
        "applied": True,
    }


def on_enable(context: dict[str, Any]) -> None:
    """Optional lifecycle hook called when the plugin is enabled at a cycle boundary.

    The context dictionary provides:
      - name: plugin identifier
      - version: plugin version
      - workspace: Path to active workspace
      - state_dir: Path to private plugin state directory (workspace/plugins/<name>/state)
      - logger: EventLogger instance for recording structured events
    """
    # Initialize any runtime resources or state files here.
    state_dir = context.get("state_dir")
    if state_dir:
        state_dir.mkdir(parents=True, exist_ok=True)


def on_disable(context: dict[str, Any]) -> None:
    """Optional lifecycle hook called when the plugin is disabled at a cycle boundary.

    Use this hook to clean up volatile resources, release locks, or flush state.
    """
    pass
