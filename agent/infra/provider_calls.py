"""Optional per-workspace provider-attempt cap for randomized campaigns."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from agent.infra.file_lock import locked_file


def reserve_provider_call(logger: Any, provider: str, model: str) -> int | None:
    """Reserve one actual API attempt before sending it; None means no cap."""
    limit = max(0, int(os.getenv("SELF_MAX_PROVIDER_CALLS", "0")))
    if not limit:
        return None
    workspace = Path(logger.path).parent.parent
    path = workspace / "state" / "ab_provider_calls.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with locked_file(path.with_suffix(".lock")):
        try:
            count = int(json.loads(path.read_text(encoding="utf-8")).get("calls", 0))
        except (OSError, ValueError):
            count = 0
        if count >= limit:
            logger.log("provider_call_cap_reached", limit=limit)
            raise RuntimeError("Provider call cap reached for this run")
        count += 1
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"calls": count}) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    return count
