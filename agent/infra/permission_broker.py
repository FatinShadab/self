"""Permission broker: central gatekeeper for all body, plugin, and core actions.

Levels:
- L0: observe (read-only, no side-effects)
- L1: reversible change (quarantine, plan updates, reversible edits)
- L2: destructive or irreversible (run_shell, file overwrites/deletions)
- L3: physical actuation (hardware/robotic movement or triggers)

Default policy: deny everything above L0 until granted by the human operator
via the human-owned configuration file (./config/permissions.json).
"""
from __future__ import annotations

import enum
import json
import os
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from agent.infra.event_log import EventLogger


class PermissionLevel(enum.IntEnum):
    """Permission level hierarchy."""
    L0 = 0  # observe
    L1 = 1  # reversible change
    L2 = 2  # destructive / irreversible
    L3 = 3  # physical actuation

    @classmethod
    def from_value(cls, val: Any) -> PermissionLevel:
        """Parse permission level from int, string ('L0', '0', 'observe', etc.)."""
        if isinstance(val, PermissionLevel):
            return val
        if isinstance(val, int):
            return cls(min(3, max(0, val)))
        s = str(val).strip().upper()
        if s in {"L0", "0", "OBSERVE", "READS", "READ_ONLY"}:
            return cls.L0
        if s in {"L1", "1", "REVERSIBLE", "QUARANTINE"}:
            return cls.L1
        if s in {"L2", "2", "DESTRUCTIVE", "IRREVERSIBLE", "WRITES", "EXECUTES"}:
            return cls.L2
        if s in {"L3", "3", "PHYSICAL", "ACTUATION"}:
            return cls.L3
        return cls.L0


@dataclass
class ActionRequest:
    """Action request submitted to the permission broker."""
    action: str = ""
    source: str = "core"
    level: PermissionLevel = PermissionLevel.L0
    params: dict[str, Any] = field(default_factory=dict)
    dry_run: bool = False
    reversible: bool = False
    undo_hint: str = ""
    action_id: str = ""
    actor: str = ""
    action_type: str = ""
    target: str = ""

    def __post_init__(self) -> None:
        if self.actor and (self.source == "core" or not self.source):
            self.source = self.actor
        if self.action_type and not self.action:
            self.action = self.action_type
        if self.target and "target" not in self.params:
            self.params["target"] = self.target


@dataclass
class ActionVerdict:
    """Decision returned by the permission broker."""
    allowed: bool
    reason: str
    request: ActionRequest
    dry_run: bool = False


@dataclass
class RateLimitConfig:
    """Rate limit per action class (actions per time window, NOT tokens)."""
    action_class: str
    max_actions: int
    window_seconds: float


class PermissionPolicy:
    """Loads and resolves human-owned permission policy from ./config."""

    def __init__(self, config_file: Path | str | None = None) -> None:
        self.default_level: PermissionLevel = PermissionLevel.L0
        self.grants: dict[str, PermissionLevel] = {}
        self.action_grants: dict[str, PermissionLevel] = {}
        self.rate_limits: dict[str, RateLimitConfig] = {}
        self.config_path: Path | None = Path(config_file) if config_file else None
        if self.config_path and self.config_path.exists():
            self.load(self.config_path)

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
        # 1. Scoped action grant (actor:action) takes highest precedence
        scoped = f"{source}:{action}"
        if scoped in self.action_grants:
            return self.action_grants[scoped]
        # 2. Global action grant
        if action in self.action_grants:
            return self.action_grants[action]
        # 3. Source grant (e.g. 'core', 'body:container')
        if source in self.grants:
            return self.grants[source]
        # 4. Prefix match for plugin namespaces (e.g. 'plugins.*')
        if "." in source:
            prefix = source.split(".", 1)[0]
            if prefix in self.grants:
                return self.grants[prefix]
        return self.default_level

    def get_rate_limit(self, action: str) -> RateLimitConfig | None:
        """Get rate limit config for an action or fallback default."""
        return self.rate_limits.get(action) or self.rate_limits.get("default")


class PermissionBroker:
    """Core-owned permission broker gatekeeping every action from body or plugins."""

    def __init__(
        self,
        workspace: Path | str | None = None,
        config_dir: Path | str | None = None,
        policy_path: Path | str | None = None,
        logger: EventLogger | None = None,
        policy: PermissionPolicy | None = None,
        panic_threshold: int = 5,
        max_consecutive_denials: int | None = None,
        on_panic: Callable[[str], None] | None = None,
        audit_trail: Any | None = None,
        dry_run: bool = False,
    ) -> None:
        self.workspace = Path(workspace).resolve() if workspace else None
        self.logger = logger
        self.panic_threshold = max(1, max_consecutive_denials if max_consecutive_denials is not None else panic_threshold)
        self.on_panic = on_panic
        self.audit_trail = audit_trail
        self.dry_run = dry_run

        # Config / policy file resolution
        if policy_path is not None:
            self.policy_file = Path(policy_path).resolve()
            self.config_dir = self.policy_file.parent
        elif config_dir is not None:
            self.config_dir = Path(config_dir).resolve()
            self.policy_file = self.config_dir / "permissions.json"
        else:
            env_cfg = os.environ.get("SELF_CONFIG_DIR")
            if env_cfg:
                self.config_dir = Path(env_cfg).resolve()
            elif Path("/config").exists() and Path("/config").is_dir():
                self.config_dir = Path("/config").resolve()
            elif self.workspace and (self.workspace.parent / "config").exists():
                self.config_dir = (self.workspace.parent / "config").resolve()
            elif self.workspace:
                self.config_dir = (self.workspace / "config").resolve()
            else:
                self.config_dir = Path("config").resolve()
            self.policy_file = self.config_dir / "permissions.json"

        self.policy = policy or PermissionPolicy(self.policy_file)

        # Rate limiting state: action_class -> list of float timestamps
        self._action_timestamps: dict[str, list[float]] = defaultdict(list)

        # Undo hooks: action_class -> callable
        self._undo_hooks: dict[str, Callable[..., Any]] = {}

        # Panic tracking
        self._consecutive_denials = 0
        self._consecutive_failures = 0
        self._in_panic = False

    @property
    def in_panic(self) -> bool:
        return self._in_panic

    def register_undo_hook(self, action: str, hook: Callable[..., Any]) -> None:
        """Register an undo handler for a reversible action."""
        self._undo_hooks[action] = hook

    def request_undo(self, action: str, **kwargs: Any) -> dict[str, Any]:
        """Execute an undo hook for a previously executed action."""
        hook = self._undo_hooks.pop(action, None)
        if hook is None:
            return {"ok": False, "error": f"No undo hook registered for action '{action}'."}
        try:
            result = hook(**kwargs)
            if self.logger:
                self.logger.log("action_undone", action=action, status="success")
            return {"ok": True, "result": result}
        except Exception as exc:
            if self.logger:
                self.logger.log("action_undo_failed", action=action, error=str(exc))
            return {"ok": False, "error": f"Undo failed for '{action}': {exc}"}

    def execute_undo(self, action: str, **kwargs: Any) -> bool:
        """Alias for request_undo returning boolean success."""
        return bool(self.request_undo(action, **kwargs).get("ok", False))

    def reset_panic(self) -> None:
        """Reset panic state after human recovery or restart."""
        self._consecutive_denials = 0
        self._consecutive_failures = 0
        self._in_panic = False

    def authorize(self, request: ActionRequest) -> ActionVerdict:
        """Validate request against policy, rate limits, and panic state.

        Logs: action_requested, then action_allowed or action_denied.
        """
        # 1. Log action_requested
        self._log_event(
            "action_requested",
            action=request.action,
            source=request.source,
            level=request.level.name,
            dry_run=request.dry_run or self.dry_run,
            reversible=request.reversible,
        )

        # Check dry run mode
        if self.dry_run or request.dry_run:
            verdict = ActionVerdict(
                allowed=True,
                reason=f"Dry run simulation: action '{request.action}' (level {request.level.name}) allowed without execution.",
                request=request,
                dry_run=True,
            )
            self._log_event("action_allowed", action=request.action, source=request.source, dry_run=True, reason=verdict.reason)
            return verdict

        # 2. Check if broker is in panic
        if self._in_panic:
            verdict = ActionVerdict(
                allowed=False,
                reason="Broker in panic mode due to repeated denied or failed actions; emergency stop active.",
                request=request,
                dry_run=request.dry_run,
            )
            self._log_event(
                "action_denied",
                action=request.action,
                source=request.source,
                level=request.level.name,
                reason=verdict.reason,
            )
            return verdict

        # 3. Check permission level against policy
        max_level = self.policy.max_allowed_level(request.source, request.action)
        if request.level > max_level:
            self._consecutive_denials += 1
            verdict = ActionVerdict(
                allowed=False,
                reason=(
                    f"Permission denied: action '{request.action}' requires level {request.level.name} "
                    f"but source '{request.source}' is only granted up to {max_level.name}."
                ),
                request=request,
                dry_run=request.dry_run,
            )
            self._log_event(
                "action_denied",
                action=request.action,
                source=request.source,
                level=request.level.name,
                reason=verdict.reason,
            )
            self._check_panic()
            return verdict

        # 4. Check rate limits
        rl = self.policy.get_rate_limit(request.action)
        if rl is not None:
            now = time.monotonic()
            stamps = self._action_timestamps[request.action]
            cutoff = now - rl.window_seconds
            self._action_timestamps[request.action] = [t for t in stamps if t > cutoff]
            if len(self._action_timestamps[request.action]) >= rl.max_actions:
                self._consecutive_denials += 1
                verdict = ActionVerdict(
                    allowed=False,
                    reason=(
                        f"Rate limit exceeded for action '{request.action}': "
                        f"maximum {rl.max_actions} actions per {rl.window_seconds}s reached."
                    ),
                    request=request,
                    dry_run=request.dry_run,
                )
                self._log_event(
                "action_denied",
                action=request.action,
                source=request.source,
                level=request.level.name,
                reason=verdict.reason,
            )
                self._check_panic()
                return verdict

        # 5. Allowed
        if not request.dry_run and rl is not None:
            self._action_timestamps[request.action].append(time.monotonic())

        self._consecutive_denials = 0
        verdict = ActionVerdict(
            allowed=True,
            reason="Action authorized by permission policy.",
            request=request,
            dry_run=request.dry_run,
        )
        self._log_event("action_allowed", action=request.action, source=request.source, dry_run=request.dry_run)
        return verdict

    def record_execution(
        self,
        request: ActionRequest,
        success: bool | None = None,
        reversible: bool = False,
        error: str | None = None,
        ok: bool | None = None,
    ) -> None:
        """Record the actual execution outcome of an authorized action."""
        eff_success = ok if ok is not None else (success if success is not None else True)
        if not eff_success:
            self._consecutive_failures += 1
        else:
            self._consecutive_failures = 0
            self._consecutive_denials = 0

        self._log_event(
            "action_executed",
            action=request.action,
            source=request.source,
            level=request.level.name,
            success=success,
            reversible=reversible,
            error=error or "",
        )

        if not success:
            self._check_panic()

    def _check_panic(self) -> None:
        total_issues = self._consecutive_denials + self._consecutive_failures
        if total_issues >= self.panic_threshold and not self._in_panic:
            self._in_panic = True
            reason = (
                f"Broker panic triggered: {self._consecutive_denials} consecutive denials, "
                f"{self._consecutive_failures} consecutive failures (threshold={self.panic_threshold})."
            )
            self._log_event("broker_panic", reason=reason)
            if self.on_panic:
                try:
                    self.on_panic(reason)
                except Exception:
                    pass

    def _log_event(self, event: str, **fields: Any) -> None:
        if self.logger:
            self.logger.log(event, **fields)
        if self.audit_trail:
            try:
                self.audit_trail.append(event=event, **fields)
            except Exception:
                pass
