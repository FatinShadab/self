"""Preserve the legacy autonomous loop entry point."""

# Compatibility shim: implementation lives in agent.runtime.loop.
from agent.runtime.loop import *  # noqa: F401,F403
from agent.runtime.loop import main
if __name__ == "__main__":
    raise SystemExit(main())
