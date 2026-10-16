"""Preserve the legacy wake and terminal UI entry point."""

# Compatibility shim: implementation lives in agent.ui.wake.
from agent.ui.wake import *  # noqa: F401,F403
from agent.ui.wake import main
if __name__ == "__main__":
    raise SystemExit(main())
