"""Headless wake execution loop without terminal UI."""
from __future__ import annotations

import time
from typing import Any


def run_headless(coordinator: Any) -> int:
    """Run a wake session repeatedly in the foreground without the terminal UI."""
    try:
        while True:
            try:
                result = coordinator.run()
            except Exception as exc:
                coordinator.logger.narrate(f"Wake coordinator failed: {type(exc).__name__}; retrying automatically.")
                time.sleep(3.0)
                continue
            if (
                (coordinator.workspace / "STOP").exists()
                or coordinator.stop_requested
                or (hasattr(coordinator, "broker") and getattr(coordinator.broker, "in_panic", False))
            ):
                break
            if (coordinator.workspace / "HUMAN_REQUEST.md").exists():
                coordinator.logger.narrate(
                    "Waiting for the human request to be resolved; the next session will start automatically afterward."
                )
                while (
                    (coordinator.workspace / "HUMAN_REQUEST.md").exists()
                    and not (coordinator.workspace / "STOP").exists()
                    and not coordinator.stop_requested
                ):
                    time.sleep(2.0)
                continue
            delay = 3.0 if result is not None and getattr(result, "reason", "") == "provider_error" else 0.8
            coordinator.logger.narrate("Session ended; starting the next session automatically.")
            time.sleep(delay)
    finally:
        coordinator.close()
    return 0


__all__ = [
    "run_headless",
]
