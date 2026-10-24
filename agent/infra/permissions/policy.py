"""Permission policy configuration and grant resolution."""
from __future__ import annotations

import json
from pathlib import Path

from agent.infra.permissions.level import PermissionLevel
from agent.infra.permissions.verdict import RateLimitConfig


class PermissionPolicy:
    """Loads and resolves human-owned permission policy from ./config."""

    def __init__(self, config_file: Path | str | None = None) -> None:
        self.default_level: PermissionLevel = PermissionLevel.L0
        self.grants: dict[str, PermissionLevel] = {}
        self.action_grants: dict[str, PermissionLevel] = {}
        self.plugin_grants: dict[str, PermissionLevel] = {}
        self.rate_limits: dict[str, RateLimitConfig] = {}
        self.config_path: Path | None = Path(config_file) if config_file else None
        if self.config_path and self.config_path.exists():
            self.load(self.config_path)
            plugin_config = self.config_path.parent / "plugins.json"
            if plugin_config.exists():
                try:
                    self.set_plugin_grants_from_config(json.loads(plugin_config.read_text(encoding="utf-8")))
                except (OSError, json.JSONDecodeError):
                    pass

    def set_plugin_grants_from_config(self, config: dict) -> None:
        """Apply host-configured plugin ceilings; unpinned plugins stay at L0."""
        self.plugin_grants.clear()
        entries = config.get("plugins", {}) if isinstance(config, dict) else {}
        if not isinstance(entries, dict):
            return
        for name, entry in entries.items():
            if not isinstance(name, str) or not isinstance(entry, dict):
                continue
            if "permission_level" not in entry:
                continue
            level = str(entry["permission_level"]).upper()
            if level not in {"L0", "L1", "L2", "L3"}:
                continue
            pinned_hash = entry.get("hash", "")
            pinned = (
                isinstance(pinned_hash, str)
                and len(pinned_hash) == 64
                and all(c in "0123456789abcdef" for c in pinned_hash.lower())
            )
            allowed = PermissionLevel.from_value(level) if entry.get("enabled") and pinned else PermissionLevel.L0
            self.plugin_grants[f"plugins.{name}"] = allowed

    def load(self, path: Path) -> None:
        """Load policy definitions from JSON file."""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(data, dict):
            return

        self.default_level = PermissionLevel.from_value(data.get("default_level", "L0"))

        grants_data = data.get("grants", {})
        if isinstance(grants_data, dict):
            for src, lvl in grants_data.items():
                self.grants[str(src)] = PermissionLevel.from_value(lvl)
        elif isinstance(grants_data, list):
            for entry in grants_data:
                if isinstance(entry, dict):
                    actor = entry.get("actor", "")
                    max_lvl = PermissionLevel.from_value(entry.get("max_level", entry.get("level", 0)))
                    if actor and actor != "*":
                        self.grants[str(actor)] = max_lvl
                        for act_t in entry.get("action_types", []):
                            self.action_grants[f"{actor}:{act_t}"] = max_lvl
                    else:
                        for act_t in entry.get("action_types", []):
                            self.action_grants[str(act_t)] = max_lvl

        action_grants_data = data.get("action_grants", {})
        if isinstance(action_grants_data, dict):
            for act, lvl in action_grants_data.items():
                self.action_grants[str(act)] = PermissionLevel.from_value(lvl)

        rl_data = data.get("rate_limits", {})
        if isinstance(rl_data, dict):
            for act_class, cfg in rl_data.items():
                if isinstance(cfg, dict):
                    self.rate_limits[str(act_class)] = RateLimitConfig(
                        action_class=str(act_class),
                        max_actions=int(cfg.get("max_actions", 120)),
                        window_seconds=float(cfg.get("window_seconds", 60.0)),
                    )

    def max_allowed_level(self, source: str, action: str) -> PermissionLevel:
        """Resolve highest allowed level for a given source and action."""
        if source in self.plugin_grants:
            return self.plugin_grants[source]
        scoped = f"{source}:{action}"
        if scoped in self.action_grants:
            return self.action_grants[scoped]
        if action in self.action_grants:
            return self.action_grants[action]
        if source in self.grants:
            return self.grants[source]
        if "." in source:
            prefix = source.split(".", 1)[0]
            if prefix in self.grants:
                return self.grants[prefix]
        return self.default_level

    def get_rate_limit(self, action: str) -> RateLimitConfig | None:
        """Get rate limit config for an action or fallback default."""
        return self.rate_limits.get(action) or self.rate_limits.get("default")
