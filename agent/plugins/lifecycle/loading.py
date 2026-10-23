"""Dynamic plugin module loading, entrypoint execution, and tool handler wrapping."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, Callable

from agent.infra.event_log import EventLogger
from agent.plugins.lifecycle.models import CORE_TOOL_NAMES, Plugin


def wrap_tool_handler(plugin_name: str, tool_name: str, handler: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap a plugin tool handler so unexpected exceptions are returned as errors, not crashes."""
    def safe_invoke(**kwargs: Any) -> dict[str, Any]:
        try:
            res = handler(**kwargs)
            if isinstance(res, dict):
                res.setdefault("ok", True)
                return res
            return {"ok": True, "result": res}
        except Exception as exc:
            return {"ok": False, "error": f"Plugin tool '{tool_name}' failed: {exc}"}
    return safe_invoke


def load_plugin_module(plugin: Plugin, logger: EventLogger) -> bool:
    """Dynamically load a plugin module and extract tool handlers.

    A crashing plugin logs plugin_load_failed and never takes the core down.
    """
    if plugin.is_loaded:
        return True

    if plugin.state_dir is not None:
        plugin.state_dir.mkdir(parents=True, exist_ok=True)
    plugin.tools.clear()
    plugin.tool_specs.clear()

    # Collect all callable specifications: declared tools, plus actions and sensors
    all_tool_defs: list[dict[str, Any]] = [dict(t) for t in plugin.manifest.tools]
    registered_names = {t["name"] for t in all_tool_defs}
    for s in plugin.manifest.sensors:
        if s.name not in registered_names:
            all_tool_defs.append({"name": s.name, "description": s.description})
            registered_names.add(s.name)
    for a in plugin.manifest.actions:
        if a.name not in registered_names:
            all_tool_defs.append({"name": a.name, "description": a.description})
            registered_names.add(a.name)

    # Check for core tool collisions
    for tool_def in all_tool_defs:
        raw_tool_name = tool_def["name"]
        namespaced_name = f"{plugin.manifest.name}.{raw_tool_name}"

        # Collisions with core tools or unqualified names
        if raw_tool_name in CORE_TOOL_NAMES or namespaced_name in CORE_TOOL_NAMES:
            err = f"Plugin '{plugin.manifest.name}' tool '{raw_tool_name}' collides with core tool."
            logger.log("plugin_load_failed", plugin=plugin.manifest.name, error=err)
            plugin.load_error = err
            return False

    # Load python module if plugin.py or tools.py exists
    mod = None
    plugin_py = plugin.plugin_dir / "plugin.py"
    tools_py = plugin.plugin_dir / "tools.py"
    entry_file = plugin_py if plugin_py.exists() else (tools_py if tools_py.exists() else None)

    if entry_file:
        try:
            mod_name = f"agent_plugins_{plugin.manifest.name}"
            spec = importlib.util.spec_from_file_location(mod_name, str(entry_file))
            if spec is None or spec.loader is None:
                raise ImportError(f"Cannot create spec for {entry_file}")
            mod = importlib.util.module_from_spec(spec)
            sys.modules[mod_name] = mod
            spec.loader.exec_module(mod)
            plugin.module = mod
        except Exception as exc:
            logger.log("plugin_load_failed", plugin=plugin.manifest.name, error=f"Import error: {exc}")
            plugin.load_error = str(exc)
            return False

    # Register tools
    for tool_def in all_tool_defs:
        raw_name = tool_def["name"]
        namespaced_name = f"{plugin.manifest.name}.{raw_name}"

        # Locate handler
        handler = None
        if mod is not None:
            handler = getattr(mod, raw_name, None) or getattr(mod, "run", None)

        # Check individual tool file under tools/<raw_name>.py
        tool_subpath = plugin.plugin_dir / "tools" / f"{raw_name}.py"
        if handler is None and tool_subpath.exists():
            try:
                t_mod_name = f"agent_plugins_{plugin.manifest.name}_{raw_name}"
                t_spec = importlib.util.spec_from_file_location(t_mod_name, str(tool_subpath))
                if t_spec and t_spec.loader:
                    t_mod = importlib.util.module_from_spec(t_spec)
                    sys.modules[t_mod_name] = t_mod
                    t_spec.loader.exec_module(t_mod)
                    handler = getattr(t_mod, "run", None) or getattr(t_mod, raw_name, None)
            except Exception as exc:
                logger.log("plugin_load_failed", plugin=plugin.manifest.name, error=f"Tool error {raw_name}: {exc}")
                plugin.load_error = str(exc)
                return False

        if handler is None:
            # Provide default safe fallback handler
            def make_default_handler(p_name: str, t_name: str) -> Callable[..., Any]:
                def default_handler(**kwargs: Any) -> dict[str, Any]:
                    return {"ok": True, "plugin": p_name, "tool": t_name, "args": kwargs}
                return default_handler
            handler = make_default_handler(plugin.manifest.name, raw_name)

        # Build namespaced tool spec
        spec_copy = dict(tool_def)
        spec_copy["name"] = namespaced_name
        spec_copy["description"] = f"[{plugin.manifest.name}] {spec_copy.get('description', '')}"

        plugin.tools[namespaced_name] = wrap_tool_handler(plugin.manifest.name, namespaced_name, handler)
        plugin.tool_specs.append(spec_copy)

    plugin.is_loaded = True
    return True
