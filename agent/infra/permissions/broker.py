"""Permission broker gatekeeping actions across body, plugins, and core."""
from __future__ import annotations

import os
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

from agent.infra.event_log import EventLogger
from agent.infra.permissions.level import PermissionLevel
from agent.infra.permissions.policy import PermissionPolicy
from agent.infra.permissions.verdict import ActionRequest, ActionVerdict


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
