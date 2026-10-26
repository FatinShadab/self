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

BRAIN_ART_IDLE = " .--. .--.\n( (_)|(_) )\n '--' '--'"
BRAIN_ART_THINKING = " .--. .--.\n( (~)|(~) )\n '--' '--'"
BRAIN_ART_WORKING = " .--. .--.\n( (*)|(*) )\n '--' '--'"


def brain_art(state: str = "idle") -> str:
    """Return the brain-like ASCII figure corresponding to the current state."""
    st = state.strip().lower()
    if "think" in st:
        return BRAIN_ART_THINKING
    if "work" in st or "tool" in st:
        return BRAIN_ART_WORKING
    return BRAIN_ART_IDLE


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
        # Low effort / Idle: gentle breathing ripples with ~ and _ and small | pulses
        for col in range(width):
            phase = (col + frame) % 12
            if phase in (2, 3):
                rows[1][col] = "~"
                rows[2][col] = "|" if phase == 2 else "~"
            elif phase in (1, 4):
                rows[2][col] = "~"
            elif phase == 7:
                rows[2][col] = "|"
            else:
                rows[2][col] = "_"
    elif eff in {"medium", "med", "2", "normal"} or "think" in st:
        # Medium effort / Thinking: undulating thought wave oscillations with ~ crests and | pulses (max height 2)
        for col in range(width):
            idx = (col + frame) % pattern_len
            h = min(2, BASE_PATTERN[idx])
            if h == 2:
                rows[1][col] = "~" if (col % 2 == 0) else "|"
                rows[2][col] = "|"
            elif h == 1:
                rows[2][col] = "|"
            else:
                prev_h = min(2, BASE_PATTERN[(idx - 1) % pattern_len])
                next_h = min(2, BASE_PATTERN[(idx + 1) % pattern_len])
                rows[2][col] = "~" if (prev_h > 0 or next_h > 0) else "_"
    else:
        # High effort / Working: full dynamic equalizer spectrum
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
                prev_h = BASE_PATTERN[(idx - 1) % pattern_len]
                next_h = BASE_PATTERN[(idx + 1) % pattern_len]
                rows[2][col] = "~" if (prev_h > 0 or next_h > 0) else "_"
            # Wave crest / harmonic accents on flanks of tall spikes
            if h == 0 and (BASE_PATTERN[(idx - 1) % pattern_len] == 3 or BASE_PATTERN[(idx + 1) % pattern_len] == 3):
                rows[1][col] = "~"

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
    "brain_art",
    "BRAIN_ART_IDLE",
    "BRAIN_ART_THINKING",
    "BRAIN_ART_WORKING",
]
