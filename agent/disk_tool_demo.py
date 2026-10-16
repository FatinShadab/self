# Compatibility shim: implementation lives in agent.ui.disk_tool_demo.
from agent.ui.disk_tool_demo import *  # noqa: F401,F403
from agent.ui.disk_tool_demo import main
if __name__ == "__main__":
    raise SystemExit(main())
