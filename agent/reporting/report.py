"""Human-readable summary of learning since the last report."""
from __future__ import annotations

import argparse
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.infra.event_log import EventLogger
from agent.learning.learning import LearningStore


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


def _host_results_allowed() -> bool:
    """The image-owned agent and eval containers never read host eval output."""
    return not Path("/opt/agent").exists()


def _external_summary(path: str | Path | None, label: str) -> list[str]:
    if not path:
        return [f"{label}: no data yet."]
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return [f"{label}: no data yet."]
    content = [line for line in lines if line.strip()]
    return [f"{label} (host-provided):", *(content[:20] or ["no data yet."])]


def helper_model_section(root: Path, events: list[dict[str, Any]], since: str | None = None) -> list[str]:
    """Describe recorded model use without treating self-reports as objective."""
    lines = ["", "Helper-model activity:"]
    attempts = [row for row in events if row.get("event") in {"llm_call_attempt", "provider_call_attempt"}]
    if not attempts:  # Older logs have only call-start events.
        attempts = [row for row in events if row.get("event") == "llm_call_started"]
    completed = [row for row in events if row.get("event") in {"llm_call_completed", "provider_call_completed"}]
    failures = [row for row in events if row.get("event") in
                {"llm_call_failed", "provider_call_failed", "provider_call_unavailable"}]
    names = sorted({str(row.get("model")) for row in [*attempts, *completed, *failures] if row.get("model")})
    if not names:
        lines.append("- Calls, tokens, latency, failures by model: no data yet.")
    for name in names:
        calls = sum(row.get("model") == name for row in attempts)
        results = [row for row in completed if row.get("model") == name]
        tokens = sum(int(row.get("total_tokens", int(row.get("input_tokens", 0)) +
                                                      int(row.get("output_tokens", 0)))) for row in results)
        latency = sum(float(row.get("latency_ms", 0)) for row in results)
        errors = sum(row.get("model") == name for row in failures)
        lines.append(f"- {name}: calls={calls}, total tokens {tokens}, mean_latency_ms={latency/len(results):.1f} "
                     f"(n={len(results)}), failures={errors}")
    decisions = _after(_read_jsonl(root / "state" / "model_decisions.jsonl"), since)
    delegations = Counter((str(row.get("model", "unknown")), str(row.get("task_type", "unknown")))
                          for row in decisions if row.get("source") == "agent_tool")
    lines.append("Delegations by model and task type:")
    lines.extend(f"- {model} / {task}: {count}" for (model, task), count in sorted(delegations.items()))
    if not delegations:
        lines.append("- no data yet.")
    choices = [row for row in decisions if row.get("source") == "agent_tool" or
               str(row.get("source", "")).startswith("checkpoint:")]
    sources = Counter(str(row.get("source", "unknown")) for row in choices)
    origins = Counter(str(row.get("origin", "unknown")) for row in choices)
    try:
        base = json.loads((root / "state" / "models.json").read_text(encoding="utf-8")).get("base_model")
    except (OSError, json.JSONDecodeError):
        base = None
    checkpoints = [row for row in choices if str(row.get("source", "")).startswith("checkpoint:")]
    chosen_base = sum(row.get("model") == base for row in checkpoints) if base else 0
    forced = sum(row.get("origin") != "model_choice" for row in checkpoints)
    lines.append(f"Decisions by source: {dict(sorted(sources.items())) or 'no data yet'}")
    lines.append(f"Decisions by origin: {dict(sorted(origins.items())) or 'no data yet'}")
    lines.append(f"Checkpoint chose base: {chosen_base}/{len(checkpoints)}; "
                 f"forced defaults: {forced}/{len(checkpoints)} "
                 f"({forced/len(checkpoints):.1%})." if checkpoints else
                 "Checkpoint chose base / forced defaults: no data yet.")
    outcomes = _after(_read_jsonl(root / "state" / "model_outcomes.jsonl"), since)
    lines.append("Outcome signals (observational records; objective and self-reported separate):")
    for group, predicate in (("delegated", lambda row: row.get("source") != "task_baseline"),
                             ("non-delegated", lambda row: row.get("source") == "task_baseline")):
        selected = [row for row in outcomes if predicate(row)]
        for provenance in ("objective", "self_reported"):
            by_signal: dict[str, list[Any]] = defaultdict(list)
            for row in selected:
                if row.get("provenance") == provenance and row.get("signal") != "note":
                    by_signal[str(row.get("signal", "unknown"))].append(row.get("value"))
            if not by_signal:
                lines.append(f"- {group} {provenance}: no data yet.")
            for signal, values in sorted(by_signal.items()):
                if all(isinstance(value, bool) for value in values):
                    summary = f"true={sum(values)}/{len(values)}"
                else:
                    summary = str(dict(Counter(map(str, values))))
                lines.append(f"- {group} {provenance} {signal}: n={len(values)} {summary}")
    return lines


def create_report(workspace: str | Path, *, advance_cursor: bool = True,
                  calibration_file: str | Path | None = None,
                  ab_comparison_file: str | Path | None = None) -> str:
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
    lines.extend(helper_model_section(root, events, since))
    if _host_results_allowed():
        calibration_file = calibration_file or os.getenv("SELF_REPORT_CALIBRATION_FILE")
        ab_comparison_file = ab_comparison_file or os.getenv("SELF_REPORT_AB_FILE")
        lines.extend(["", *_external_summary(calibration_file, "Latest calibration")])
        lines.extend(["", *_external_summary(ab_comparison_file, "Latest A/B comparison")])
    else:
        lines.extend(["", "Latest calibration: no data yet (host-only).",
                      "Latest A/B comparison: no data yet (host-only)."])
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
