"""Command-line interface and entry point for wake sessions."""
from __future__ import annotations

import argparse
import signal
from typing import Any

from agent.session.coordinator import WakeCoordinator, run_headless
from agent.ui.tui.app import run_tui


def main() -> int:
    """Parse command-line arguments and run this module's entry point."""
    parser = argparse.ArgumentParser(description="Wake SELF with a persistent session and optional terminal UI.")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--workspace", default="/home/entity")
    parser.add_argument("--max-iterations", type=int)
    parser.add_argument("--token-budget", type=int)
    parser.add_argument("--max-wall-clock-seconds", type=int)
    args = parser.parse_args()

    coordinator = WakeCoordinator(
        args.workspace,
        max_iterations=args.max_iterations,
        token_budget=args.token_budget,
        max_wall_clock_seconds=args.max_wall_clock_seconds,
    )

    def stop_signal(*_: Any) -> None:
        coordinator.stop_requested = True
        (coordinator.workspace / "STOP").touch()

    signal.signal(signal.SIGTERM, stop_signal)
    signal.signal(signal.SIGINT, stop_signal)
    return run_headless(coordinator) if args.headless else run_tui(coordinator)


if __name__ == "__main__":
    raise SystemExit(main())

__all__ = [
    "main",
]
