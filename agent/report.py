"""Preserve the legacy learning-report entry point."""

# Compatibility shim: implementation lives in agent.reporting.report.
from agent.reporting.report import *  # noqa: F401,F403
from agent.reporting.report import main
if __name__ == "__main__":
    raise SystemExit(main())
