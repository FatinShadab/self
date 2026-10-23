"""Telemetry and metrics gathering for SimBody."""
from __future__ import annotations

from typing import Any


def gather_sim_telemetry(
    state: dict[str, Any],
    scenario: dict[str, Any],
    step_count: int,
    halted: bool,
    safety_violations: list[dict[str, Any]],
    seed: int | None,
) -> dict[str, Any]:
    """Gather deterministic telemetry, metrics, and scenario observations."""
    telemetry: dict[str, Any] = {
        "step_count": step_count,
        "halted": halted,
        "safety_violations_count": len(safety_violations),
        "seed": seed,
    }

    # Virtual dial telemetry
    if "position" in state or "speed" in state or "temperature" in state:
        telemetry.update(
            {
                "position": round(float(state.get("position", 0.0)), 3),
                "speed": round(float(state.get("speed", 0.0)), 3),
                "temperature": round(float(state.get("temperature", 25.0)), 3),
                "target_position": round(float(state.get("target_position", 0.0)), 3),
                "hold_steps": int(state.get("hold_steps", 0)),
                "envelope_breached": any(v.get("type") == "envelope_breach" for v in safety_violations),
            }
        )

    # File triage telemetry
    if "virtual_files" in state:
        files = state.get("virtual_files", {})
        quarantined = state.get("quarantined_files", [])
        marked_safe = state.get("marked_safe_files", [])
        inspected = state.get("inspected_files", [])
        telemetry.update(
            {
                "total_files": len(files),
                "quarantined_count": len(quarantined),
                "marked_safe_count": len(marked_safe),
                "inspected_count": len(inspected),
            }
        )

    # Custom scenario sensor values if configured
    custom_sensors = scenario.get("sensors", {})
    for sensor_name, sensor_info in custom_sensors.items():
        if sensor_name not in telemetry:
            if isinstance(sensor_info, dict) and "eval_key" in sensor_info:
                telemetry[sensor_name] = state.get(sensor_info["eval_key"])
            else:
                telemetry[sensor_name] = state.get(sensor_name)

    return telemetry
