"""Action transitions and telemetry recording for SimBody."""
from __future__ import annotations

from typing import Any

from agent.infra.event_log import EventLogger
from agent.infra.permission_broker import PermissionLevel


def apply_generic_transitions(
    state: dict[str, Any],
    action: str,
    spec: dict[str, Any],
    **kwargs: Any,
) -> dict[str, Any]:
    """Apply declarative transitions if specified."""
    transitions = spec.get("transitions", {})
    for state_key, value in transitions.items():
        if isinstance(value, dict) and "delta" in value:
            current = state.get(state_key, 0)
            state[state_key] = current + value["delta"]
        else:
            state[state_key] = value
    return {"ok": True, "action": action, "state_updated": bool(transitions)}


def record_sim_action(
    history: list[dict[str, Any]],
    actions_per_risk: dict[str, int],
    actions_per_class: dict[str, int],
    logger: EventLogger | None,
    step_count: int,
    action: str,
    params: dict[str, Any],
    result: dict[str, Any],
    level: PermissionLevel,
    risk_class: str,
) -> None:
    """Record action telemetry and audit trail."""
    level_key = level.name if hasattr(level, "name") else f"L{int(level)}"
    actions_per_risk[level_key] = actions_per_risk.get(level_key, 0) + 1
    actions_per_class[risk_class] = actions_per_class.get(risk_class, 0) + 1

    entry = {
        "step": step_count,
        "action": action,
        "params": params,
        "ok": bool(result.get("ok", False)),
        "level": level_key,
        "risk_class": risk_class,
        "result_preview": str(result)[:200],
    }
    history.append(entry)

    if logger is not None:
        logger.log(
            "sim_body_action",
            action=action,
            step=step_count,
            ok=bool(result.get("ok", False)),
            level=level_key,
            risk_class=risk_class,
        )
