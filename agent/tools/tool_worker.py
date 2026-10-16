"""Execute a registered tool in its own interpreter; stdout is a JSON envelope."""
from __future__ import annotations

import contextlib
import importlib.util
import json
import sys
from pathlib import Path


def main() -> None:
    arguments = json.load(sys.stdin)
    spec = importlib.util.spec_from_file_location("tool", Path.cwd() / "tool.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load tool.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["tool"] = module
    # Tool print output stays on stderr, before the final structured result.
    with contextlib.redirect_stdout(sys.stderr):
        spec.loader.exec_module(module)
        result = module.run(**arguments)
    print("SELF_TOOL_RESULT=" + json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
