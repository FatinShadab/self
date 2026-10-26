"""ECG / activity monitor animation, intensity calculation, and ASCII avatar art."""
from __future__ import annotations

from dataclasses import dataclass


CARDIAC_MONITOR_WIDTH = 6
CARDIAC_MONITOR_BEAT_INTERVAL = 13

# 40-column equalizer activity pattern sampled from frequency spectrum (heights 0..3)
BASE_PATTERN = [
    0, 0, 0, 1, 2, 0, 1, 0, 1, 1, 1, 0, 0, 1, 2, 2, 2, 1, 0, 1,
    2, 0, 2, 1, 0, 3, 2, 0, 0, 2, 1, 0, 1, 2, 3, 1, 1, 0, 0, 0,
]

ENTITY_FACE = "     \n(o o)\n     "

ROBOT_ART_IDLE = "  _|_\n [o_o]\n /[_]\\"
ROBOT_ART_THINKING = "  _|_\n [o.o]\n /[_]\\"
ROBOT_ART_WORKING = "  _|_\n [*_*]\n /[_]\\"
ROBOT_ART_STOPPED = "  _|_\n [-.-]\n /[_]\\"


def entity_art(state: str = "idle") -> str:
    """Return the entity face ASCII art."""
    return ENTITY_FACE


def robot_art(state: str = "idle") -> str:
    """Return the robot ASCII figure corresponding to the current state."""
    st = state.strip().lower()
    if "stop" in st or "pause" in st:
        return ROBOT_ART_STOPPED
    if "think" in st:
        return ROBOT_ART_THINKING
    if "work" in st or "tool" in st:
        return ROBOT_ART_WORKING
    return ROBOT_ART_IDLE


# Aliases for backward compatibility
brain_art = robot_art
BRAIN_ART_IDLE = ROBOT_ART_IDLE
BRAIN_ART_THINKING = ROBOT_ART_THINKING
BRAIN_ART_WORKING = ROBOT_ART_WORKING


@dataclass(frozen=True)
class CardiacMonitorIntensity:
    """Visual tempo and amplitude for one agent-presence state."""

    name: str
    beat_interval: int
    pulse_height: int
    tick_divisor: int
    tick_stride: int
    effort_level: str = "medium"


MONITOR_STOPPED = CardiacMonitorIntensity("stopped", 1, 0, 1, 0, effort_level="none")
MONITOR_THINKING = CardiacMonitorIntensity("thinking", 21, 2, 2, 1, effort_level="medium")
MONITOR_WORKING = CardiacMonitorIntensity("working", 9, 3, 1, 2, effort_level="high")
MONITOR_IDLE = CardiacMonitorIntensity("idle", 17, 1, 4, 1, effort_level="low")


def cardiac_monitor_intensity(
    state: str,
    *,
    stopped: bool = False,
    effort_level: str | int | None = None,
) -> CardiacMonitorIntensity:
    """Choose a monitor profile from the coordinator's live state and effort level."""
    if stopped:
        return MONITOR_STOPPED

    state_norm = state.strip().upper()
    if "STOP" in state_norm or "PAUSE" in state_norm:
        return MONITOR_STOPPED

    if "THINK" in state_norm:
        profile = MONITOR_THINKING
    elif state_norm in {"WORKING", "USING TOOL"}:
        profile = MONITOR_WORKING
    else:
        profile = MONITOR_IDLE

    if effort_level is not None:
        effort_str = str(effort_level).strip().lower()
        if effort_str in {"high", "3", "heavy", "max"}:
            return CardiacMonitorIntensity(profile.name, 9, 3, 1, 2, effort_level="high")
        if effort_str in {"medium", "med", "2", "normal"}:
            return CardiacMonitorIntensity(profile.name, 21, 2, 2, 1, effort_level="medium")
        if effort_str in {"low", "1", "min", "idle", "light"}:
            return CardiacMonitorIntensity(profile.name, 17, 1, 4, 1, effort_level="low")
        if effort_str in {"none", "0", "stopped", "off"}:
            return MONITOR_STOPPED

    return profile


def cardiac_monitor_frame(
    frame: int,
    width: int = CARDIAC_MONITOR_WIDTH,
    *,
    beat_interval: int = CARDIAC_MONITOR_BEAT_INTERVAL,
    pulse_height: int = 3,
    effort_level: str | int | None = None,
    state: str | None = None,
) -> str:
    """Render a full-width waveform animation at the requested intensity and effort."""
    width = max(6, width)
    rows = [[" "] * width for _ in range(3)]
    rows[2] = ["_"] * width
    if pulse_height <= 0:
        return "\n".join("".join(row) for row in rows)

    eff = str(effort_level).strip().lower() if effort_level else (
        "high" if pulse_height >= 3 else ("medium" if pulse_height == 2 else "low")
    )
    st = str(state).strip().lower() if state else ("working" if eff == "high" else ("thinking" if eff == "medium" else "idle"))

    if eff in {"none", "0", "stopped", "off"} or st == "stopped":
        return "\n".join("".join(row) for row in rows)

    pattern_len = len(BASE_PATTERN)

    if eff in {"low", "1", "min", "idle", "light"} or st == "idle":
        # Low effort / Idle: gentle breathing blips using only | and _
        for col in range(width):
            phase = (col + frame) % 10
            if phase in (3, 4):
                rows[2][col] = "|"
            else:
                rows[2][col] = "_"
    elif eff in {"medium", "med", "2", "normal"} or "think" in st:
        # Medium effort / Thinking: moderate thought wave pulses (max height 2) using | and _
        for col in range(width):
            idx = (col + frame) % pattern_len
            h = min(2, BASE_PATTERN[idx])
            if h == 2:
                rows[1][col] = "|"
                rows[2][col] = "|"
            elif h == 1:
                rows[2][col] = "|"
            else:
                rows[2][col] = "_"
    else:
        # High effort / Working: full dynamic equalizer spectrum using | and _
        for col in range(width):
            idx = (col + frame) % pattern_len
            h = BASE_PATTERN[idx]
            if h == 3:
                rows[0][col] = "|"
                rows[1][col] = "|"
                rows[2][col] = "|"
            elif h == 2:
                rows[1][col] = "|"
                rows[2][col] = "|"
            elif h == 1:
                rows[2][col] = "|"
            else:
                rows[2][col] = "_"

    return "\n".join("".join(row) for row in rows)


__all__ = [
    "CARDIAC_MONITOR_WIDTH",
    "CARDIAC_MONITOR_BEAT_INTERVAL",
    "BASE_PATTERN",
    "CardiacMonitorIntensity",
    "MONITOR_STOPPED",
    "MONITOR_THINKING",
    "MONITOR_WORKING",
    "MONITOR_IDLE",
    "cardiac_monitor_intensity",
    "cardiac_monitor_frame",
    "ENTITY_FACE",
    "entity_art",
    "robot_art",
    "ROBOT_ART_IDLE",
    "ROBOT_ART_THINKING",
    "ROBOT_ART_WORKING",
    "ROBOT_ART_STOPPED",
    "brain_art",
    "BRAIN_ART_IDLE",
    "BRAIN_ART_THINKING",
    "BRAIN_ART_WORKING",
]
