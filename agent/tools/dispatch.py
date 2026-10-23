"""Tool dispatch registry mapping tool names to execution targets and plugins."""
from __future__ import annotations

from typing import Any, Callable

from agent.llm.llm import BudgetExceeded
from agent.tools.definitions import TOOL_DEFINITIONS

_DEFINED_TOOL_NAMES = frozenset(d["name"] for d in TOOL_DEFINITIONS)
_OPENCODE_DISPATCH_NAMES = frozenset({
    "opencode_status",
    "delegate_coding",
    "apply_delegation",
    "discard_delegation",
    "record_build_route",
    "record_build_outcome",
    "build_route_stats",
})
_PROVIDER_DISPATCH_NAMES = frozenset({
    "research_provider",
    "record_provider_verification",
    "request_provider_key",
    "ask_brain",
    "benchmark_providers",
    "probe_local_ollama",
})


def dispatch_tool(runner: Any, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Dispatch a tool call to the matching handler, model collaborator, or plugin."""
    try:
        if name == "create_tool" and runner.registry is not None:
            result = runner.registry.create_tool(**arguments)
        elif name in {"list_models", "record_model_assessment"}:
            if runner.model_registry is None:
                raise RuntimeError("model registry is not configured")
            result = getattr(runner.model_registry, name)(**arguments)
        elif name in {"probe_model", "research_model"}:
            if runner.model_prober is None:
                raise RuntimeError("model probes are not configured")
            result = getattr(runner.model_prober, name)(**arguments)
        elif name == "ask_model":
            if runner.model_decisions is None:
                raise RuntimeError("model decisions are not configured")
            result = runner.model_decisions.ask_model(**arguments)
        elif name == "record_delegation_outcome":
            if runner.model_decisions is None:
                raise RuntimeError("model decisions are not configured")
            result = runner.model_decisions.record_delegation_outcome(**arguments)
        elif name in _PROVIDER_DISPATCH_NAMES:
            if runner.brain_router is None:
                raise RuntimeError("brain router is not configured")
            result = getattr(runner, name)(**arguments)
        elif name == "request_capability":
            if runner.capabilities is None:
                raise RuntimeError("capability request system is not configured")
            result = runner.request_capability(**arguments)
        elif name == "propose_core_patch":
            if runner.identity is None:
                raise RuntimeError("identity and core-patch system is not configured")
            result = runner.propose_core_patch(**arguments)
        elif name in _DEFINED_TOOL_NAMES or name in _OPENCODE_DISPATCH_NAMES:
            result = getattr(runner, name)(**arguments)
        elif runner.plugins is not None and runner.plugins.is_plugin_tool(name):
            result = runner.plugins.execute_plugin_tool(name, arguments)
        elif runner.plugins is not None and runner.plugins.is_vanished_or_disabled_tool(name):
            result = runner.plugins.execute_plugin_tool(name, arguments)
        elif "." in name:
            plugin_name = name.split(".", 1)[0]
            result = {"ok": False, "error": f"tool no longer available: plugin {plugin_name} disabled"}
        elif runner.registry is not None:
            result = runner.registry.execute(name, arguments)
        else:
            raise ValueError(f"Unknown tool: {name}")

        result.setdefault("ok", True)
    except BudgetExceeded:
        raise
    except Exception as exc:  # Tool errors are observations for the next model turn.
        result = {"ok": False, "error": runner.logger.redactor.text(exc)}

    return result
