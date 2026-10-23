"""Handoff generation, pending human input tracking, and request aggregation."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def requests_text(root: Path) -> str:
    """Read pending human requests from capability/key requests and HUMAN_REQUEST.md."""
    chunks = []
    for path in (
        root / "state" / "capability_requests.md",
        root / "state" / "key_requests.md",
        root / "HUMAN_REQUEST.md",
    ):
        try:
            chunks.append(path.read_text(encoding="utf-8", errors="replace")[-4_000:])
        except OSError:
            pass
    return "\n".join(chunks) or "No pending human requests recorded."


def pending_human_inputs(workspace: Path) -> list[str]:
    """Scan state files and workspace root for pending human requests."""
    pending: list[str] = []
    for name in ("capability_requests.md", "key_requests.md", "HUMAN_REQUEST.md", "HUMAN_INPUT.md"):
        path = workspace / "state" / name if name not in {"HUMAN_REQUEST.md", "HUMAN_INPUT.md"} else workspace / name
        try:
            text = path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        if text:
            pending.append(f"{name}: {text.splitlines()[0][:300]}")
    return pending


def tool_list(workspace: Path) -> list[str]:
    """Return sorted names of all registered tools created in the workspace."""
    result = []
    tools_dir = workspace / "tools"
    if tools_dir.exists():
        for meta in tools_dir.glob("*/meta.json"):
            data = _read_json(meta)
            if data.get("registered"):
                result.append(str(data.get("name", meta.parent.name)))
    return sorted(result)


def make_handoff(
    workspace: Path,
    learning_store: Any,
    old_handoff: dict[str, Any],
    plan: list[dict[str, Any]],
    report: str,
    reason: str,
) -> dict[str, Any]:
    """Build a durable handoff packet summarizing the current run for the next wake."""
    map_entries = learning_store._load_map().get("entries", {})
    discoveries = [
        f"{name}: {str(value.get('value'))[:240]} (source: {value.get('evidence', 'state/map.json')})"
        for name, value in list(map_entries.items())[:12]
    ]
    failures = []
    try:
        actions_path = workspace / "logs" / "actions.jsonl"
        for line in actions_path.read_text(encoding="utf-8", errors="replace").splitlines()[-200:]:
            event = json.loads(line)
            if event.get("event") in {"tool_creation_failed", "run_failed", "llm_call_failed", "provider_call_failed"}:
                failures.append(f"{event.get('event')}: {event.get('error_type') or event.get('error') or 'see actions log'}")
    except (OSError, json.JSONDecodeError):
        pass

    long_term = old_handoff.get("long_term_summary", "")
    long_term = re.sub(r"Session complete after \d+ cycle\(s\)\.?\s*", "", long_term).strip()
    return {
        "summary": report[:3_000] or "The session completed without a textual cycle report.",
        "long_term_summary": long_term,
        "discoveries": discoveries,
        "tools_created": [f"{name}: registered reusable tool" for name in tool_list(workspace)],
        "failures_and_lessons": failures[-12:] or ["No new recorded harness failures."],
        "open_questions": ["Weigh pending human inputs before attempting capability expansions."],
        "plan": plan,
        "pending_human_inputs": pending_human_inputs(workspace),
        "mood_of_run": "stuck" if reason in {"token_budget", "wall_clock_budget"} else "progressing" if report else "exploring",
    }


__all__ = [
    "requests_text",
    "pending_human_inputs",
    "tool_list",
    "make_handoff",
    "_read_json",
]
