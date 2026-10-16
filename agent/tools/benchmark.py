"""Small transparent provider evaluation; it never creates accounts or bypasses quotas."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.llm.brain_router import BrainRouter
from agent.infra.event_log import EventLogger


EVALS = [
    {"name": "arithmetic", "prompt": "Reply with only the number: 17 + 25 =", "must_contain": "42"},
    {"name": "concise_summary", "prompt": "Summarize in at most eight words: Tools should be tested before they are reused.", "must_contain": "tested"},
]


def run_benchmark(workspace: str | Path, logger: EventLogger, router: BrainRouter, providers: list[str] | None = None) -> dict[str, Any]:
    """Run the small transparent provider checks and save their scores."""
    root = Path(workspace)
    selected = providers or router.registry.configured()
    scores: dict[str, Any] = {"schema_version": 1, "updated_at": datetime.now(timezone.utc).isoformat(), "providers": {}}
    for provider in selected:
        cases = []
        for case in EVALS:
            result = router.chat([{"role": "user", "content": case["prompt"]}], None, 64, "simple", provider)
            text = str(result.get("text", ""))
            cases.append({"name": case["name"], "ok": bool(result.get("ok")) and case["must_contain"].lower() in text.lower(), "latency_ms": result.get("latency_ms"), "provider": result.get("provider"), "error": result.get("error")})
        successful = sum(1 for case in cases if case["ok"])
        scores["providers"][provider] = {"quality": successful / len(EVALS), "cases": cases, "metadata_last_verified": router.registry.metadata(provider).get("last_verified")}
    path = root / "state" / "provider_scores.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(logger.redactor.value(scores), indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    logger.log("provider_benchmark_completed", providers=selected, cases_per_provider=len(EVALS))
    return {"ok": True, "path": str(path), "providers": scores["providers"]}
