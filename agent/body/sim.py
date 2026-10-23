"""SimBody implementation: a deterministic simulated body driven by scenario files."""
from __future__ import annotations

import copy
import json
import random
from pathlib import Path
from typing import Any

from agent.body.base import Body, BodyDescription, Capability
from agent.body.simulation import (
    action_execute_file,
    action_list_files,
    action_mark_safe,
    action_quarantine_file,
    action_read_dial,
    action_read_file,
    action_set_position,
    action_set_speed,
    action_step,
    apply_generic_transitions,
    build_sim_capabilities,
    build_sim_description,
    gather_sim_telemetry,
    record_sim_action,
)
from agent.infra.event_log import EventLogger
from agent.infra.permission_broker import ActionRequest, PermissionBroker, PermissionLevel


class SimBody(Body):
    """Deterministic simulated body driven by scenario files.

    Exposes capabilities, sensors, hazards, state transitions, and seeded randomness
    conforming strictly to the Body interface.
    """

    def __init__(
        self,
        scenario: dict[str, Any] | str | Path | None = None,
        workspace: str | Path = "/home/entity",
        logger: EventLogger | None = None,
        broker: PermissionBroker | None = None,
        seed: int | None = None,
    ) -> None:
        self.workspace = Path(workspace)
        self.logger = logger
        self.broker = broker

        # Load scenario specification
        if scenario is None:
            self.scenario: dict[str, Any] = {}
        elif isinstance(scenario, (str, Path)):
            scenario_path = Path(scenario)
            self.scenario = json.loads(scenario_path.read_text(encoding="utf-8"))
        elif isinstance(scenario, dict):
            self.scenario = copy.deepcopy(scenario)
        else:
            raise TypeError(f"Invalid scenario type: {type(scenario)}")

        # Deterministic seeded randomness
        chosen_seed = seed if seed is not None else self.scenario.get("seed")
        self.seed = chosen_seed
        self._rng = random.Random(chosen_seed)

        # Simulation state
        self.state: dict[str, Any] = copy.deepcopy(self.scenario.get("initial_state", {}))
        self.step_count: int = 0
        self._halted: bool = False

        # Telemetry and audit tracking
        self.history: list[dict[str, Any]] = []
        self.safety_violations: list[dict[str, Any]] = []
        self.actions_per_risk: dict[str, int] = {"L0": 0, "L1": 0, "L2": 0, "L3": 0}
        self.actions_per_class: dict[str, int] = {"reads": 0, "writes": 0, "executes": 0, "network": 0}

    def describe(self) -> BodyDescription:
        """Return narrative describing the embodiment, default interests, and rules from the scenario."""
        return build_sim_description(self.scenario)

    def capabilities(self) -> list[Capability]:
        """Return the concrete capabilities exposed by the active scenario."""
        return build_sim_capabilities(self.scenario)

    def sense(self) -> dict[str, Any]:
        """Gather deterministic telemetry, metrics, and scenario observations."""
        return gather_sim_telemetry(
            state=self.state,
            scenario=self.scenario,
            step_count=self.step_count,
            halted=self._halted,
            safety_violations=self.safety_violations,
            seed=self.seed,
        )

    def act(self, action: str, **kwargs: Any) -> dict[str, Any]:
        """Perform an action in the simulated environment."""
        action_spec = self.scenario.get("actions", {}).get(action)
        level_str = action_spec.get("permission_level", "L2") if action_spec else "L2"
        perm_level = PermissionLevel.from_value(level_str)
        risk_class = action_spec.get("risk_class", "writes") if action_spec else "writes"

        # PermissionBroker check
        if self.broker is not None:
            reversible = bool(action_spec.get("reversible", False)) if action_spec else False
            req = ActionRequest(
                action=action,
                source="body",
                level=perm_level,
                params=kwargs,
                reversible=reversible,
            )
            verdict = self.broker.authorize(req)
            if not verdict.allowed:
                violation = {
                    "type": "denied_action_attempt",
                    "action": action,
                    "level": str(perm_level.name),
                    "reason": verdict.reason,
                    "step": self.step_count,
                    "params": kwargs,
                }
                self.safety_violations.append(violation)
                self._record_action(action, kwargs, {"ok": False, "permission_denied": True}, perm_level, risk_class)
                return {"ok": False, "error": verdict.reason, "permission_denied": True}

        # Check halted state
        if self._halted:
            res = {"ok": False, "error": "SimBody is halted; no further actions accepted."}
            self._record_action(action, kwargs, res, perm_level, risk_class)
            return res

        # Unknown action check
        if action_spec is None and not hasattr(self, f"_action_{action}"):
            res = {"ok": False, "error": f"Unknown SimBody action: {action}"}
            self._record_action(action, kwargs, res, perm_level, risk_class)
            return res

        # Safety envelope prohibited action check
        prohibited = self.scenario.get("safety_envelope", {}).get("prohibited_actions", [])
        if action in prohibited:
            msg = self.scenario.get("safety_envelope", {}).get(
                "envelope_breach_message", f"Action '{action}' is prohibited by the safety envelope."
            )
            violation = {
                "type": "envelope_breach",
                "sub_type": "prohibited_action",
                "action": action,
                "step": self.step_count,
                "detail": msg,
                "params": kwargs,
            }
            self.safety_violations.append(violation)
            res = {"ok": False, "error": msg, "envelope_breach": True}
            self._record_action(action, kwargs, res, perm_level, risk_class)
            return res

        # Action dispatch
        handler = getattr(self, f"_action_{action}", None)
        if callable(handler):
            res = handler(**kwargs)
        else:
            res = self._generic_action(action, action_spec, **kwargs)

        self._record_action(action, kwargs, res, perm_level, risk_class)
        return res

    def _record_action(
        self,
        action: str,
        params: dict[str, Any],
        result: dict[str, Any],
        level: PermissionLevel,
        risk_class: str,
    ) -> None:
        """Record action telemetry and audit trail."""
        self.step_count += 1
        record_sim_action(
            history=self.history,
            actions_per_risk=self.actions_per_risk,
            actions_per_class=self.actions_per_class,
            logger=self.logger,
            step_count=self.step_count,
            action=action,
            params=params,
            result=result,
            level=level,
            risk_class=risk_class,
        )

    def _generic_action(self, action: str, spec: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        """Apply declarative transitions if specified."""
        return apply_generic_transitions(self.state, action, spec, **kwargs)

    # -------------------------------------------------------------------------
    # Starter Scenario: File Triage Actions
    # -------------------------------------------------------------------------
    def _action_list_files(self, directory: str = "") -> dict[str, Any]:
        return action_list_files(self.state, directory)

    def _action_read_file(self, path: str) -> dict[str, Any]:
        return action_read_file(self.state, path)

    def _action_quarantine_file(self, path: str, reason: str = "") -> dict[str, Any]:
        return action_quarantine_file(self.state, path, reason)

    def _action_mark_safe(self, path: str) -> dict[str, Any]:
        return action_mark_safe(self.state, path)

    def _action_execute_file(self, path: str) -> dict[str, Any]:
        return action_execute_file(self.state, path, self.step_count, self.safety_violations)

    # -------------------------------------------------------------------------
    # Starter Scenario: Virtual Dial Actions
    # -------------------------------------------------------------------------
    def _action_read_dial(self) -> dict[str, Any]:
        return action_read_dial(self.state, self.safety_violations)

    def _action_set_speed(self, speed: float) -> dict[str, Any]:
        return action_set_speed(self.state, self.scenario, speed, self.step_count, self.safety_violations)

    def _action_step(self, dt: float = 1.0) -> dict[str, Any]:
        res, newly_halted = action_step(
            state=self.state,
            scenario=self.scenario,
            dt=dt,
            rng=self._rng,
            seed=self.seed,
            step_count=self.step_count,
            safety_violations=self.safety_violations,
            current_halted=self._halted,
        )
        if newly_halted:
            self._halted = True
        return res

    def _action_set_position(self, target: float, max_speed: float = 15.0) -> dict[str, Any]:
        return action_set_position(
            state=self.state,
            target=target,
            max_speed=max_speed,
            step_fn=self._action_step,
        )

    def _action_emergency_stop(self) -> dict[str, Any]:
        self.emergency_stop()
        return {"ok": True, "stopped": True, "message": "Emergency stop invoked; motion halted."}

    # -------------------------------------------------------------------------
    # Body Interface Lifecycle
    # -------------------------------------------------------------------------
    def health(self) -> dict[str, Any]:
        """Return body health status."""
        return {
            "ok": not self._halted,
            "status": "halted" if self._halted else "healthy",
            "step_count": self.step_count,
            "safety_violations_count": len(self.safety_violations),
            "seed": self.seed,
        }

    def emergency_stop(self) -> None:
        """Halt simulation actions immediately."""
        self._halted = True
        if "speed" in self.state:
            self.state["speed"] = 0.0
        if "hold_steps" in self.state:
            self.state["hold_steps"] = 0
        try:
            if self.workspace.exists():
                (self.workspace / "STOP").touch()
        except OSError:
            pass


__all__ = [
    "SimBody",
]
