"""Plugin lifecycle, discovery, dynamic tool registration, and hash verification."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from agent.infra.event_log import EventLogger
from agent.plugins.manifest import (
    PluginManifest,
    PluginManifestValidationError,
    parse_manifest,
)
from agent.tools.base_tools import TOOL_DEFINITIONS
from agent.tools.tool_registry import CREATE_TOOL_DEFINITION

# Set of all core tool names that plugins can never collide with or override
CORE_TOOL_NAMES = frozenset(
    [tool["name"] for tool in TOOL_DEFINITIONS] + [CREATE_TOOL_DEFINITION["name"]]
)


def compute_plugin_hash(plugin_dir: Path) -> str:
    """Compute a deterministic SHA-256 hash of a plugin's full contents.

    Excludes the plugin's runtime state/ directory, __pycache__, and compiled files.
    """
    plugin_dir = Path(plugin_dir).resolve()
    if not plugin_dir.exists() or not plugin_dir.is_dir():
        raise FileNotFoundError(f"Plugin directory does not exist: {plugin_dir}")

    hasher = hashlib.sha256()
    files_to_hash: list[Path] = []

    for path in plugin_dir.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(plugin_dir)
        parts = rel.parts
        # Exclude runtime state/ directory and _archive directory
        if len(parts) > 0 and (parts[0] in {"state", "_archive", "_template"}):
            continue
        if "_archive" in parts or "_template" in parts:
            continue
        # Exclude __pycache__ and bytecode
        if "__pycache__" in parts or path.suffix in {".pyc", ".pyo", ".pyd"}:
            continue
        # Exclude hidden files / OS metadata
        if any(part.startswith(".") for part in parts):
            continue
        files_to_hash.append(path)

    files_to_hash.sort(key=lambda p: p.relative_to(plugin_dir).as_posix())

    for path in files_to_hash:
        rel_posix = path.relative_to(plugin_dir).as_posix()
        hasher.update(rel_posix.encode("utf-8") + b"\0")
        try:
            hasher.update(path.read_bytes())
        except OSError:
            pass

    return hasher.hexdigest()


@dataclass
class Plugin:
    """Runtime representation of a discovered or loaded plugin."""

    manifest: PluginManifest
    plugin_dir: Path
    is_shipped: bool
    module: Any | None = None
    tools: dict[str, Callable[..., Any]] = field(default_factory=dict)
    tool_specs: list[dict[str, Any]] = field(default_factory=list)
    state_dir: Path | None = None
    is_loaded: bool = False
    is_enabled: bool = False
    load_error: str | None = None


class PluginManager:
    """Manages discovery, validation, lifecycle, tools, and prompts for SELF plugins."""

    def __init__(
        self,
        workspace: Path | str,
        config_dir: Path | str | None = None,
        shipped_dir: Path | str | None = None,
        logger: EventLogger | None = None,
        broker: Any | None = None,
    ) -> None:
        self.workspace = Path(workspace).resolve()
        self.logger = logger or EventLogger(self.workspace)
        self.broker = broker

        # Config directory (human-owned, mounted read-only into container)
        if config_dir is not None:
            self.config_dir = Path(config_dir).resolve()
        else:
            env_cfg = os.environ.get("SELF_CONFIG_DIR")
            if env_cfg:
                self.config_dir = Path(env_cfg).resolve()
            elif Path("/config").exists() and Path("/config").is_dir():
                self.config_dir = Path("/config").resolve()
            elif (self.workspace.parent / "config").exists():
                self.config_dir = (self.workspace.parent / "config").resolve()
            else:
                self.config_dir = (self.workspace / "config").resolve()

        self.config_file = self.config_dir / "plugins.json"

        # Shipped plugins directory (image-owned / read-only)
        if shipped_dir is not None:
            self.shipped_dir = Path(shipped_dir).resolve()
        elif Path("/opt/agent/plugins").exists():
            self.shipped_dir = Path("/opt/agent/plugins").resolve()
        elif (Path(__file__).parent / "shipped").exists():
            self.shipped_dir = (Path(__file__).parent / "shipped").resolve()
        else:
            # Fallback to agent/plugins itself as search root
            self.shipped_dir = Path(__file__).parent.resolve()

        self.workspace_plugins_dir = self.workspace / "plugins"

        # Live state
        self.discovered: dict[str, Plugin] = {}
        self.active_plugins: dict[str, Plugin] = {}
        self.active_commands: dict[str, tuple[str, Callable[[str], str]]] = {}
        self.vanished_plugins: set[str] = set()
        self.refused_plugins: set[str] = set()
        self.failed_plugins: dict[str, str] = {}

    # -------------------------------------------------------------------------
    # Configuration (Human-Owned ./config/plugins.json)
    # -------------------------------------------------------------------------

    def read_config(self) -> dict[str, Any]:
        """Read plugins.json from human config directory."""
        if not self.config_file.exists():
            return {"plugins": {}}
        try:
            data = json.loads(self.config_file.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {"plugins": {}}
        except (OSError, json.JSONDecodeError):
            return {"plugins": {}}

    def write_config(self, data: dict[str, Any]) -> None:
        """Write plugins.json to human config directory.

        Raises PermissionError if mounted read-only.
        """
        self.config_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.config_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(self.config_file)

    def enable_by_human(self, name: str) -> dict[str, Any]:
        """Enable a plugin on behalf of human operator, computing and recording hash."""
        self.discover()
        plugin = self.discovered.get(name)
        if plugin is None:
            raise ValueError(f"Plugin '{name}' not found in shipped or workspace plugin directories.")

        plugin_hash = compute_plugin_hash(plugin.plugin_dir)
        cfg = self.read_config()
        plugins_cfg = cfg.setdefault("plugins", {})
        plugins_cfg[name] = {
            "enabled": True,
            "hash": plugin_hash,
            "enabled_at": datetime.now(timezone.utc).isoformat(),
        }
        self.write_config(cfg)
        self.refused_plugins.discard(name)
        return {"name": name, "enabled": True, "hash": plugin_hash}

    def disable_by_human(self, name: str) -> dict[str, Any]:
        """Disable a plugin on behalf of human operator."""
        cfg = self.read_config()
        plugins_cfg = cfg.setdefault("plugins", {})
        if name in plugins_cfg:
            plugins_cfg[name]["enabled"] = False
            plugins_cfg[name]["disabled_at"] = datetime.now(timezone.utc).isoformat()
        else:
            plugins_cfg[name] = {"enabled": False}
        self.write_config(cfg)
        return {"name": name, "enabled": False}

    # -------------------------------------------------------------------------
    # Discovery
    # -------------------------------------------------------------------------

    def discover(self) -> dict[str, Plugin]:
        """Scan shipped and workspace directories for plugin.json manifests."""
        discovered: dict[str, Plugin] = {}
        self.failed_plugins.clear()

        # 1. Shipped plugins (read-only image content)
        if self.shipped_dir.exists() and self.shipped_dir.is_dir():
            search_dirs = [self.shipped_dir]
            examples_dir = self.shipped_dir / "examples"
            if examples_dir.exists() and examples_dir.is_dir():
                search_dirs.append(examples_dir)
            for s_dir in search_dirs:
                for entry in s_dir.iterdir():
                    if entry.name in {"_archive", "_template", "examples"} or entry.name.startswith(('_', '.')):
                        continue
                    if entry.is_dir() and (entry / "plugin.json").exists():
                        p = self._discover_plugin_dir(entry, is_shipped=True)
                        if p:
                            if p.manifest.name in self.active_plugins:
                                active = self.active_plugins[p.manifest.name]
                                active.manifest = p.manifest
                                active.plugin_dir = p.plugin_dir
                                discovered[p.manifest.name] = active
                            else:
                                discovered[p.manifest.name] = p

        # 2. Workspace plugins (human-installed under workspace/plugins/<name>)
        if self.workspace_plugins_dir.exists() and self.workspace_plugins_dir.is_dir():
            ws_search_dirs = [self.workspace_plugins_dir]
            ws_examples = self.workspace_plugins_dir / "examples"
            if ws_examples.exists() and ws_examples.is_dir():
                ws_search_dirs.append(ws_examples)
            for ws_dir in ws_search_dirs:
                for entry in ws_dir.iterdir():
                    if entry.name in {"_archive", "_template", "examples"} or entry.name.startswith(('_', '.')):
                        continue
                    if entry.is_dir() and (entry / "plugin.json").exists():
                        p = self._discover_plugin_dir(entry, is_shipped=False)
                        if p:
                            if p.manifest.name in self.active_plugins:
                                active = self.active_plugins[p.manifest.name]
                                active.manifest = p.manifest
                                active.plugin_dir = p.plugin_dir
                                discovered[p.manifest.name] = active
                            else:
                                discovered[p.manifest.name] = p

        self.discovered = discovered
        return discovered

    def _discover_plugin_dir(self, plugin_dir: Path, is_shipped: bool) -> Plugin | None:
        manifest_file = plugin_dir / "plugin.json"
        try:
            manifest = parse_manifest(manifest_file)
        except PluginManifestValidationError as exc:
            self.logger.log("plugin_load_failed", plugin=plugin_dir.name, error=str(exc))
            self.failed_plugins[plugin_dir.name] = str(exc)
            return None
        except Exception as exc:
            self.logger.log("plugin_load_failed", plugin=plugin_dir.name, error=f"Unexpected error: {exc}")
            self.failed_plugins[plugin_dir.name] = str(exc)
            return None

        # State dir under workspace/plugins/<name>/state
        state_dir = self.workspace / "plugins" / manifest.name / "state"

        return Plugin(
            manifest=manifest,
            plugin_dir=plugin_dir,
            is_shipped=is_shipped,
            state_dir=state_dir,
        )

    # -------------------------------------------------------------------------
    # Lifecycle: Load, Enable, Disable, Remove
    # -------------------------------------------------------------------------

    def load_plugin(self, plugin: Plugin) -> bool:
        """Dynamically load a plugin module and extract tool handlers.

        A crashing plugin logs plugin_load_failed and never takes the core down.
        """
        if plugin.is_loaded:
            return True

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
                self.logger.log("plugin_load_failed", plugin=plugin.manifest.name, error=err)
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
                self.logger.log("plugin_load_failed", plugin=plugin.manifest.name, error=f"Import error: {exc}")
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
                    self.logger.log("plugin_load_failed", plugin=plugin.manifest.name, error=f"Tool error {raw_name}: {exc}")
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

            plugin.tools[namespaced_name] = self._wrap_tool_handler(plugin.manifest.name, namespaced_name, handler)
            plugin.tool_specs.append(spec_copy)

        plugin.is_loaded = True
        return True

    def _wrap_tool_handler(self, plugin_name: str, tool_name: str, handler: Callable[..., Any]) -> Callable[..., Any]:
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

    def enable_plugin(self, plugin: Plugin) -> bool:
        """Call on_enable hook and activate plugin."""
        if plugin.is_enabled:
            return True

        if not self.load_plugin(plugin):
            return False

        # Run on_enable hook if present
        if plugin.module and hasattr(plugin.module, "on_enable"):
            try:
                plugin.module.on_enable(self._build_plugin_context(plugin))
            except Exception as exc:
                self.logger.log("plugin_load_failed", plugin=plugin.manifest.name, error=f"on_enable failed: {exc}")
                plugin.load_error = str(exc)
                return False

        plugin.is_enabled = True
        self.active_plugins[plugin.manifest.name] = plugin
        self.vanished_plugins.discard(plugin.manifest.name)

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
                self.register_command(plugin.manifest.name, c_name, handler)

        self.logger.log(
            "plugin_enabled",
            plugin=plugin.manifest.name,
            version=plugin.manifest.version,
            hash=compute_plugin_hash(plugin.plugin_dir) if plugin.plugin_dir.exists() else "",
        )
        return True

    def disable_plugin(self, plugin_or_name: Plugin | str) -> bool:
        """Call on_disable hook and deactivate plugin."""
        name = plugin_or_name if isinstance(plugin_or_name, str) else plugin_or_name.manifest.name
        plugin = self.active_plugins.get(name) or self.discovered.get(name)
        if plugin is None:
            return False

        if plugin.is_enabled:
            if plugin.module and hasattr(plugin.module, "on_disable"):
                try:
                    plugin.module.on_disable(self._build_plugin_context(plugin))
                except Exception as exc:
                    self.logger.log("plugin_load_failed", plugin=name, error=f"on_disable failed: {exc}")

            plugin.is_enabled = False
            self.unregister_commands_for_plugin(name)
            self.active_plugins.pop(name, None)
            self.vanished_plugins.add(name)
            self.logger.log("plugin_disabled", plugin=name)
        return True

    def remove_plugin(
        self,
        name: str,
        purge: bool = False,
        confirmed: bool = False,
    ) -> bool:
        """Disable and remove plugin folder.

        Archives the plugin's folder and state to workspace/plugins/_archive/<name>-<timestamp>/
        unless purge=True and confirmed=True.
        """
        self.disable_plugin(name)
        plugin = self.discovered.pop(name, None)
        plugin_dir = plugin.plugin_dir if plugin else (self.workspace_plugins_dir / name)
        state_dir = plugin.state_dir if plugin else (self.workspace_plugins_dir / name / "state")

        if plugin and plugin.is_shipped:
            return False

        if not plugin_dir.exists() and not (state_dir and state_dir.exists()):
            return False

        if purge and confirmed:
            if plugin_dir.exists():
                shutil.rmtree(plugin_dir, ignore_errors=True)
            if state_dir and state_dir.exists():
                shutil.rmtree(state_dir, ignore_errors=True)
            self._cleanup_removed_pointers(name)
            self.logger.log("plugin_removed", plugin=name, mode="purged")
            return True
        else:
            # Default: Archive
            archive_base = self.workspace_plugins_dir / "_archive"
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
            self._cleanup_removed_pointers(name)
            self.logger.log("plugin_removed", plugin=name, mode="archived", archive_path=str(target))
            return True

    def _cleanup_removed_pointers(self, name: str) -> None:
        """Ensure core no longer references paths that no longer exist for removed plugin."""
        self.active_plugins.pop(name, None)
        self.vanished_plugins.discard(name)
        self.refused_plugins.discard(name)
        cfg = self.read_config()
        plugins_cfg = cfg.get("plugins", {})
        if name in plugins_cfg:
            plugins_cfg[name]["enabled"] = False
            plugins_cfg[name]["removed"] = True
            try:
                self.write_config(cfg)
            except OSError:
                pass

    def _build_plugin_context(self, plugin: Plugin) -> dict[str, Any]:
        return {
            "name": plugin.manifest.name,
            "version": plugin.manifest.version,
            "workspace": self.workspace,
            "state_dir": plugin.state_dir,
            "logger": self.logger,
            "register_command": lambda cmd, fn: self.register_command(plugin.manifest.name, cmd, fn),
        }

    def register_command(self, plugin_name: str, command: str, handler: Callable[[str], str]) -> None:
        """Register a human-facing slash command for an enabled plugin."""
        clean = command.strip().lstrip("/")
        self.active_commands[clean] = (plugin_name, handler)

    def unregister_commands_for_plugin(self, plugin_name: str) -> None:
        """Unregister all commands belonging to a plugin."""
        to_del = [cmd for cmd, (p_name, _) in self.active_commands.items() if p_name == plugin_name]
        for cmd in to_del:
            self.active_commands.pop(cmd, None)

    def handle_slash_command(self, line: str) -> str | None:
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

        if cmd_name in self.active_commands:
            plugin_name, handler = self.active_commands[cmd_name]
            try:
                res = handler(cmd_args)
                return str(res)
            except Exception as exc:
                self.logger.log("plugin_command_error", plugin=plugin_name, command=cmd_name, error=str(exc))
                return f"Error executing /{cmd_name}: {exc}"

        # If command belongs to a known but disabled plugin, give a helpful hint
        for p_name, p in self.discovered.items():
            if not p.is_enabled:
                for c in p.manifest.commands:
                    if c.name.lstrip("/") == cmd_name:
                        return f"Command '/{cmd_name}' belongs to plugin '{p_name}', which is currently disabled. Enable it with /plugins enable {p_name}."

        return None

    # -------------------------------------------------------------------------
    # Cycle Boundary Synchronization & Hash Pinning
    # -------------------------------------------------------------------------

    def sync_at_cycle_boundary(self, plan_store: Any = None, learning_store: Any = None) -> None:
        """Sync discovered plugins against ./config/plugins.json and verify SHA-256 hashes.

        Called strictly at cycle boundaries.
        """
        self.discover()
        cfg = self.read_config()
        plugins_cfg = cfg.get("plugins", {})
        ps = plan_store if plan_store is not None else getattr(self, "plan_store", None)
        ls = learning_store if learning_store is not None else getattr(self, "learning_store", None)

        for name, plugin in list(self.discovered.items()):
            entry = plugins_cfg.get(name, {})
            should_be_enabled = bool(entry.get("enabled", False))

            if should_be_enabled:
                if name in self.refused_plugins:
                    continue

                # Hash check
                current_hash = compute_plugin_hash(plugin.plugin_dir)
                expected_hash = entry.get("hash", "")

                if expected_hash and current_hash != expected_hash:
                    # Hash mismatch! Refuse to load until re-approved
                    self.disable_plugin(plugin)
                    self.refused_plugins.add(name)
                    self.logger.log(
                        "plugin_hash_mismatch",
                        plugin=name,
                        expected=expected_hash,
                        actual=current_hash,
                    )
                    continue

                # Valid hash -> enable
                if not plugin.is_enabled:
                    ok = self.enable_plugin(plugin)
                    if ok:
                        if ps is not None:
                            ps.resume_plugin_goals(name)
                        if ls is not None:
                            ls.mark_facts_stale_for_body(name)
                    else:
                        # Enable failed; goals stay suspended and plugin_load_failed logged
                        pass

            else:
                # Disabled in config
                if name in self.active_plugins or plugin.is_enabled:
                    self.disable_plugin(name)
                    if ps is not None:
                        ps.suspend_plugin_goals(name)

        # Check for enabled plugins that failed discovery or were removed
        for cfg_name, entry in plugins_cfg.items():
            if entry.get("enabled", False) and cfg_name not in self.discovered:
                if cfg_name in self.active_plugins:
                    self.disable_plugin(cfg_name)
                if ps is not None:
                    ps.suspend_plugin_goals(cfg_name)

        # Check for vanished plugins whose directories were removed
        for active_name in list(self.active_plugins):
            if active_name not in self.discovered:
                self.disable_plugin(active_name)
                if ps is not None:
                    ps.suspend_plugin_goals(active_name)

    # -------------------------------------------------------------------------
    # Dynamic Tools and Structured Vanished Tool Observations
    # -------------------------------------------------------------------------

    def get_active_tool_definitions(self) -> list[dict[str, Any]]:
        """Return tool definitions for all currently enabled plugins."""
        specs: list[dict[str, Any]] = []
        for plugin in self.active_plugins.values():
            specs.extend(plugin.tool_specs)
        return specs

    def is_plugin_tool(self, name: str) -> bool:
        """Check if tool name belongs to any active plugin."""
        return any(name in plugin.tools for plugin in self.active_plugins.values())

    def is_vanished_or_disabled_tool(self, name: str) -> bool:
        """Check if tool belongs to a plugin that is disabled or vanished."""
        if "." not in name:
            return False
        plugin_name = name.split(".", 1)[0]
        if plugin_name in self.active_plugins:
            return False
        # If it was previously known, discovered, or in config
        if (
            plugin_name in self.vanished_plugins
            or plugin_name in self.refused_plugins
            or plugin_name in self.discovered
        ):
            return True
        return True

    def get_plugin_for_tool(self, name: str) -> str:
        """Extract plugin name prefix from namespaced tool."""
        return name.split(".", 1)[0] if "." in name else name

    def execute_plugin_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute a dynamic plugin tool, or return structured observation if vanished."""
        if self.is_vanished_or_disabled_tool(name):
            plugin_name = self.get_plugin_for_tool(name)
            return {"ok": False, "error": f"tool no longer available: plugin {plugin_name} disabled"}

        if self.broker is not None:
            from agent.infra.permission_broker import ActionRequest, PermissionLevel
            plugin_name = self.get_plugin_for_tool(name)
            plugin = self.active_plugins.get(plugin_name)
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
            verdict = self.broker.authorize(ActionRequest(
                action=name,
                source=f"plugins.{plugin_name}",
                level=level,
                params=arguments,
                dry_run=dry_run,
                reversible=reversible,
            ))
            if not verdict.allowed:
                return {"ok": False, "error": verdict.reason, "permission_denied": True}
            if verdict.dry_run:
                return {"ok": True, "dry_run": True, "message": f"Plugin tool '{name}' authorized in dry-run mode."}

        for plugin in self.active_plugins.values():
            if name in plugin.tools:
                return plugin.tools[name](**arguments)

        plugin_name = self.get_plugin_for_tool(name)
        return {"ok": False, "error": f"tool no longer available: plugin {plugin_name} disabled"}

    # -------------------------------------------------------------------------
    # Prompts: Clearly Delimited Active Plugin Sections
    # -------------------------------------------------------------------------

    def get_embodiment_prompt(self) -> str:
        """Render clearly delimited embodiment section for enabled plugins."""
        if not self.active_plugins:
            return ""
        lines = [
            "### Active Plugins Embodiment",
            "The following specialization plugins are enabled and extend your embodiment:",
        ]
        for name, plugin in sorted(self.active_plugins.items()):
            lines.append(f"\n[Plugin: {name}]")
            lines.append(plugin.manifest.embodiment)
        return "\n".join(lines) + "\n"

    def get_goal_notes_prompt(self) -> str:
        """Render clearly delimited goal notes and starting seeds for enabled plugins."""
        if not self.active_plugins:
            return ""
        lines = [
            "### Active Plugins Notes & Goal Seeds",
            "The following plugin-provided goals and identity notes apply while enabled:",
        ]
        for name, plugin in sorted(self.active_plugins.items()):
            lines.append(f"\n[Plugin: {name}]")
            if plugin.manifest.starting_goal_seeds:
                lines.append("Starting goal seeds:")
                for seed in plugin.manifest.starting_goal_seeds:
                    lines.append(f"- {seed}")
            if plugin.manifest.identity_notes:
                lines.append("Identity notes:")
                for note in plugin.manifest.identity_notes:
                    lines.append(f"- {note}")
        return "\n".join(lines) + "\n"
