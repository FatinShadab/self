"""ECG cardiac monitor animation and intensity calculation for agent presence."""
from __future__ import annotations

from dataclasses import dataclass


CARDIAC_MONITOR_WIDTH = 6
CARDIAC_MONITOR_BEAT_INTERVAL = 13


@dataclass(frozen=True)
class CardiacMonitorIntensity:
    """Visual tempo and amplitude for one agent-presence state."""

    name: str
    beat_interval: int
    pulse_height: int
    tick_divisor: int
    tick_stride: int


MONITOR_STOPPED = CardiacMonitorIntensity("stopped", 1, 0, 1, 0)
MONITOR_THINKING = CardiacMonitorIntensity("thinking", 21, 2, 3, 1)
MONITOR_WORKING = CardiacMonitorIntensity("working", 9, 3, 1, 2)
MONITOR_IDLE = CardiacMonitorIntensity("idle", 17, 2, 4, 1)


def cardiac_monitor_intensity(state: str, *, stopped: bool = False) -> CardiacMonitorIntensity:
    """Choose a monitor profile from the coordinator's live state."""
    if stopped:
        return MONITOR_STOPPED
    state = state.strip().upper()
    if "THINK" in state:
        return MONITOR_THINKING
    if state in {"WORKING", "USING TOOL"}:
        return MONITOR_WORKING
    return MONITOR_IDLE


def cardiac_monitor_frame(
    frame: int,
    width: int = CARDIAC_MONITOR_WIDTH,
    *,
    beat_interval: int = CARDIAC_MONITOR_BEAT_INTERVAL,
    pulse_height: int = 3,
) -> str:
    """Render a full-width ECG trace at the requested intensity."""
    width = max(6, width)
    rows = [[" "] * width for _ in range(3)]
    rows[2] = ["_"] * width
    if pulse_height <= 0:
        return "\n".join("".join(row) for row in rows)

    # Thinking has a short, quiet peak. Work has a taller and more frequent
    # spike. Both sweep across the full available header width.
    pulse = (
        ((0, 2, "/"), (1, 1, "/"), (2, 1, "\\"), (3, 2, "\\"))
        if pulse_height < 3
        else ((0, 2, "/"), (1, 1, "/"), (2, 0, "|"), (3, 1, "\\"), (4, 2, "\\"))
    )
    phase = frame % max(5, beat_interval)
    for pulse_x in range(width - phase, -len(pulse), -max(5, beat_interval)):
        for offset, row, character in pulse:
            column = pulse_x + offset
            if 0 <= column < width:
                rows[row][column] = character
    return "\n".join("".join(row) for row in rows)


__all__ = [
    "CARDIAC_MONITOR_WIDTH",
    "CARDIAC_MONITOR_BEAT_INTERVAL",
    "CardiacMonitorIntensity",
    "MONITOR_STOPPED",
    "MONITOR_THINKING",
    "MONITOR_WORKING",
    "MONITOR_IDLE",
    "cardiac_monitor_intensity",
    "cardiac_monitor_frame",
]
