"""Human-readable summary of learning since the last report."""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:  # Supports both `python -m agent.report` and direct test imports.
    from .event_log import EventLogger
    from .learning import LearningStore
except ImportError:  # pragma: no cover - direct script compatibility
    from event_log import EventLogger
    from learning import LearningStore


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    except OSError:
        pass
    return rows


def _load_cursor(path: Path) -> str | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value.get("last_report_at") if isinstance(value, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _after(rows: list[dict[str, Any]], since: str | None) -> list[dict[str, Any]]:
    if not since:
        return rows
    return [row for row in rows if str(row.get("timestamp", "")) > since]


def create_report(workspace: str | Path, *, advance_cursor: bool = True) -> str:
    root = Path(workspace)
    logger = EventLogger(root / "logs" / "actions.jsonl")
    learning = LearningStore(root, logger)
    learning.initialize()
    cursor_path = learning.state_dir / "report_cursor.json"
    since = _load_cursor(cursor_path)
    memories = _after(learning.memory_entries(), since)
    events = _after(_read_jsonl(logger.path), since)

    registered = [event for event in events if event.get("event") == "tool_registered"]
    failures = [
        event for event in events
        if event.get("event") in {"tool_creation_failed", "run_failed", "tool_load_rejected", "llm_call_failed"}
        or (event.get("event") == "tool_result" and not event.get("ok", True))
    ]
    spending = [event for event in events if event.get("event") == "token_spend"]
    input_tokens = sum(int(event.get("call_input_tokens", event.get("input_tokens", 0)) or 0) for event in spending)
    output_tokens = sum(int(event.get("call_output_tokens", event.get("output_tokens", 0)) or 0) for event in spending)
    reserved_tokens = sum(int(event.get("reserved_tokens", 0) or 0) for event in spending)

    lines = [f"SELF learning report since {since or 'the beginning'}", ""]
    egress_rows = _after(_read_jsonl(learning.state_dir / "egress.jsonl"), since)
    egress: dict[str, int] = {}
    for row in egress_rows:
        domain = str(row.get("domain", ""))
        if domain:
            egress[domain] = egress.get(domain, 0) + int(row.get("request_count", 1) or 1)
    today = datetime.now(timezone.utc).date().isoformat()
    daily_rows = [row for row in _read_jsonl(learning.state_dir / "egress.jsonl") if row.get("date") == today]
    daily_egress: dict[str, int] = {}
    for row in daily_rows:
        domain = str(row.get("domain", ""))
        if domain:
            daily_egress[domain] = daily_egress.get(domain, 0) + int(row.get("request_count", 1) or 1)
    lines.append(f"Egress this report period: {sum(egress.values())} harness-observed request(s) to {len(egress)} domain(s).")
    for domain, count in sorted(egress.items()):
        lines.append(f"- {domain}: {count}")
    lines.append(f"Today's egress ({today}): {sum(daily_egress.values())} harness-observed request(s).")
    for domain, count in sorted(daily_egress.items()):
        lines.append(f"- {domain}: {count}")
    lines.append("")
    lines.append(f"Learned this period: {len(memories)} cycle/task record(s).")
    for memory in memories[-8:]:
        lines.append(f"- {memory.get('lesson', 'No lesson recorded.')[:500]}")
    if not memories:
        lines.append("- No new persistent learning records.")
    lines.extend(["", f"Tools created or updated: {len(registered)}."])
    for event in registered:
        lines.append(f"- {event.get('name', 'unknown')} (version {event.get('version', '?')})")
    if not registered:
        lines.append("- None.")
    lines.extend(["", f"Failures observed: {len(failures)}."])
    for event in failures[-8:]:
        lines.append(f"- {event.get('event')}: {event.get('tool') or event.get('name') or event.get('error_type') or 'details in actions log'}")
    if not failures:
        lines.append("- None.")
    lines.extend([
        "",
        f"Token spend: input={input_tokens}, output={output_tokens}, total={input_tokens + output_tokens}; reserved capacity={reserved_tokens}.",
        "",
        "Current verified map:",
        learning.map_context(),
    ])
    provider_path = learning.state_dir / "providers.json"
    try:
        provider_data = json.loads(provider_path.read_text(encoding="utf-8"))
        providers = provider_data.get("providers", {})
        lines.extend(["", "Provider research:"])
        for name in sorted(providers):
            meta = providers[name]
            lines.append(f"- {name}: {meta.get('verification_status', 'unknown')}; verified={meta.get('last_verified') or 'never'}")
    except (OSError, json.JSONDecodeError):
        pass
    report = logger.redactor.text("\n".join(lines))
    if advance_cursor:
        now = datetime.now(timezone.utc).isoformat()
        temporary = cursor_path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"last_report_at": now}, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, cursor_path)
        logger.log("report_generated", since=since or "beginning", memories=len(memories))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize SELF learning since the prior report.")
    parser.add_argument("--workspace", default="/home/entity")
    parser.add_argument("--no-advance", action="store_true", help="Do not advance the report cursor.")
    args = parser.parse_args()
    print(create_report(args.workspace, advance_cursor=not args.no_advance))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
