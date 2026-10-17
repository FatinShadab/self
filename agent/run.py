"""Headless execution entry point for SELF."""
from __future__ import annotations

import argparse
import signal
from typing import Any

from agent.session.coordinator import WakeCoordinator, run_headless


def main() -> int:
    """Parse command-line arguments and run headless coordinator without Textual."""
    parser = argparse.ArgumentParser(description="Run SELF in headless mode without Textual.")
    parser.add_argument("--headless", action="store_true", default=True, help="Run without terminal UI.")
    parser.add_argument("--workspace", default="/home/entity", help="Path to workspace directory.")
    parser.add_argument("--max-iterations", type=int, help="Maximum autonomous cycle iterations.")
    parser.add_argument("--token-budget", type=int, help="Deprecated; ledger-only budget is enforced.")
    parser.add_argument("--max-wall-clock-seconds", type=int, help="Maximum execution wall clock seconds.")
    parser.add_argument("--command", "-c", help="Execute a slash command such as '/plugins list' and exit.")
    parser.add_argument("command_arg", nargs="?", help="Optional command string e.g. '/plugins list'.")
    args = parser.parse_args()

    coordinator = WakeCoordinator(
        args.workspace,
        max_iterations=args.max_iterations,
        token_budget=args.token_budget,
        max_wall_clock_seconds=args.max_wall_clock_seconds,
    )

    cmd = args.command or args.command_arg
    if cmd:
        if cmd.startswith("/plugins"):
            print(coordinator.handle_plugins_command(cmd))
            return 0
        print(f"Unknown headless command: {cmd}")
        return 1

    def stop_signal(*_: Any) -> None:
        coordinator.stop_requested = True
        try:
            (coordinator.workspace / "STOP").touch()
        except OSError:
            pass

    signal.signal(signal.SIGTERM, stop_signal)
    signal.signal(signal.SIGINT, stop_signal)
    return run_headless(coordinator)


if __name__ == "__main__":
    raise SystemExit(main())
