"""Plugin lifecycle, discovery, dynamic tool registration, and hash verification."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

from agent.infra.event_log import EventLogger
from agent.plugins.lifecycle import (
    configuration,
    discovery,
    loading,
    prompts,
    state_ops,
    sync,
    tool_execution,
)
from agent.plugins.lifecycle.hashing import compute_plugin_hash
from agent.plugins.lifecycle.models import CORE_TOOL_NAMES, Plugin
from agent.plugins.manifest import RESERVED_SLASH_COMMANDS

__all__ = [
    "CORE_TOOL_NAMES",
    "Plugin",
    "PluginManager",
    "compute_plugin_hash",
]


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
        return configuration.read_config(self.config_file)

    def write_config(self, data: dict[str, Any]) -> None:
        """Write plugins.json to human config directory.

        Raises PermissionError if mounted read-only.
        """
        configuration.write_config(self.config_dir, self.config_file, data)

    def enable_by_human(self, name: str) -> dict[str, Any]:
        """Enable a plugin on behalf of human operator, computing and recording hash."""
        self.discover()
        plugin = self.discovered.get(name)
        res = configuration.enable_by_human(self.config_dir, self.config_file, name, plugin)
        self.refused_plugins.discard(name)
        return res

    def disable_by_human(self, name: str) -> dict[str, Any]:
        """Disable a plugin on behalf of human operator."""
        return configuration.disable_by_human(self.config_dir, self.config_file, name)

    # -------------------------------------------------------------------------
    # Discovery
    # -------------------------------------------------------------------------

    def discover(self) -> dict[str, Plugin]:
        """Scan shipped and workspace directories for plugin.json manifests."""
        self.discovered = discovery.discover_plugins(
            shipped_dir=self.shipped_dir,
            workspace_plugins_dir=self.workspace_plugins_dir,
            workspace=self.workspace,
            active_plugins=self.active_plugins,
            logger=self.logger,
            failed_plugins=self.failed_plugins,
        )
        return self.discovered

    def _discover_plugin_dir(self, plugin_dir: Path, is_shipped: bool) -> Plugin | None:
        return discovery.discover_single_plugin_dir(
            plugin_dir=plugin_dir,
            is_shipped=is_shipped,
            workspace=self.workspace,
            logger=self.logger,
            failed_plugins=self.failed_plugins,
        )

    # -------------------------------------------------------------------------
    # Lifecycle: Load, Enable, Disable, Remove
    # -------------------------------------------------------------------------

    def load_plugin(self, plugin: Plugin) -> bool:
        """Dynamically load a plugin module and extract tool handlers.

        A crashing plugin logs plugin_load_failed and never takes the core down.
        """
        return loading.load_plugin_module(plugin, self.logger)

    def _wrap_tool_handler(self, plugin_name: str, tool_name: str, handler: Callable[..., Any]) -> Callable[..., Any]:
        """Wrap a plugin tool handler so unexpected exceptions are returned as errors, not crashes."""
        return loading.wrap_tool_handler(plugin_name, tool_name, handler)

    def enable_plugin(self, plugin: Plugin) -> bool:
        """Call on_enable hook and activate plugin."""
        return state_ops.enable_plugin_runtime(
            plugin=plugin,
            active_plugins=self.active_plugins,
            vanished_plugins=self.vanished_plugins,
            workspace=self.workspace,
            logger=self.logger,
            register_command_fn=self.register_command,
            load_plugin_fn=self.load_plugin,
        )

    def disable_plugin(self, plugin_or_name: Plugin | str) -> bool:
        """Call on_disable hook and deactivate plugin."""
        return state_ops.disable_plugin_runtime(
            plugin_or_name=plugin_or_name,
            active_plugins=self.active_plugins,
            discovered=self.discovered,
            vanished_plugins=self.vanished_plugins,
            workspace=self.workspace,
            logger=self.logger,
            unregister_commands_fn=self.unregister_commands_for_plugin,
            register_command_fn=self.register_command,
        )

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
        return state_ops.remove_plugin_runtime(
            name=name,
            discovered=self.discovered,
            active_plugins=self.active_plugins,
            workspace_plugins_dir=self.workspace_plugins_dir,
            purge=purge,
            confirmed=confirmed,
            logger=self.logger,
            cleanup_pointers_fn=self._cleanup_removed_pointers,
            disable_plugin_fn=self.disable_plugin,
        )

    def _cleanup_removed_pointers(self, name: str) -> None:
        """Ensure core no longer references paths that no longer exist for removed plugin."""
        state_ops.cleanup_removed_pointers(
            name=name,
            active_plugins=self.active_plugins,
            vanished_plugins=self.vanished_plugins,
            refused_plugins=self.refused_plugins,
            read_config_fn=self.read_config,
            write_config_fn=self.write_config,
        )

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
        base_cmd = clean.split()[0].split("/")[0].lower()
        if clean.lower() in RESERVED_SLASH_COMMANDS or base_cmd in RESERVED_SLASH_COMMANDS:
            raise ValueError(
                f"Cannot register reserved slash command '/{clean}'. "
                "Hard human controls and core commands cannot be overridden by plugins."
            )
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
        return state_ops.dispatch_slash_command(
            line=line,
            active_commands=self.active_commands,
            discovered=self.discovered,
            logger=self.logger,
        )

    # -------------------------------------------------------------------------
    # Cycle Boundary Synchronization & Hash Pinning
    # -------------------------------------------------------------------------

    def sync_at_cycle_boundary(self, plan_store: Any = None, learning_store: Any = None) -> None:
        """Sync discovered plugins against ./config/plugins.json and verify SHA-256 hashes.

        Called strictly at cycle boundaries.
        """
        self.discover()
        cfg = self.read_config()
        ps = plan_store if plan_store is not None else getattr(self, "plan_store", None)
        ls = learning_store if learning_store is not None else getattr(self, "learning_store", None)
        sync.sync_plugins_at_cycle_boundary(
            discovered=self.discovered,
            active_plugins=self.active_plugins,
            refused_plugins=self.refused_plugins,
            cfg=cfg,
            logger=self.logger,
            enable_fn=self.enable_plugin,
            disable_fn=self.disable_plugin,
            plan_store=ps,
            learning_store=ls,
        )

    # -------------------------------------------------------------------------
    # Dynamic Tools and Structured Vanished Tool Observations
    # -------------------------------------------------------------------------

    def get_active_tool_definitions(self) -> list[dict[str, Any]]:
        """Return tool definitions for all currently enabled plugins."""
        return tool_execution.get_active_tool_definitions(self.active_plugins)

    def is_plugin_tool(self, name: str) -> bool:
        """Check if tool name belongs to any active plugin."""
        return tool_execution.is_plugin_tool_active(name, self.active_plugins)

    def is_vanished_or_disabled_tool(self, name: str) -> bool:
        """Check if tool belongs to a plugin that is disabled or vanished."""
        return tool_execution.is_vanished_or_disabled_tool(
            name,
            self.active_plugins,
            self.vanished_plugins,
            self.refused_plugins,
            self.discovered,
        )

    def get_plugin_for_tool(self, name: str) -> str:
        """Extract plugin name prefix from namespaced tool."""
        return tool_execution.get_plugin_for_tool(name)

    def execute_plugin_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute a dynamic plugin tool, or return structured observation if vanished."""
        return tool_execution.execute_plugin_tool_call(
            name=name,
            arguments=arguments,
            active_plugins=self.active_plugins,
            vanished_plugins=self.vanished_plugins,
            refused_plugins=self.refused_plugins,
            discovered=self.discovered,
            broker=self.broker,
        )

    # -------------------------------------------------------------------------
    # Prompts: Clearly Delimited Active Plugin Sections
    # -------------------------------------------------------------------------

    def get_embodiment_prompt(self) -> str:
        """Render clearly delimited embodiment section for enabled plugins."""
        return prompts.render_embodiment_prompt(self.active_plugins)

    def get_goal_notes_prompt(self) -> str:
        """Render clearly delimited goal notes and starting seeds for enabled plugins."""
        return prompts.render_goal_notes_prompt(self.active_plugins)
