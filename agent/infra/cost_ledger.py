"""Measured cost ledger for tools and plugin projects built from event streams."""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now_utc() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


def compute_percentiles(values: list[float | int]) -> dict[str, float]:
    """Compute median (p50) and 90th percentile (p90) from numerical values."""
    if not values:
        return {"median": 0.0, "p90": 0.0}
    sorted_vals = sorted(float(v) for v in values)
    n = len(sorted_vals)

    # Median
    if n % 2 == 1:
        median = sorted_vals[n // 2]
    else:
        median = (sorted_vals[(n // 2) - 1] + sorted_vals[n // 2]) / 2.0

    # P90 using nearest-rank or linear interpolation
    # nearest rank index (1-based ceil(0.9 * n))
    idx = max(0, min(n - 1, math.ceil(0.9 * n) - 1))
    p90 = sorted_vals[idx]

    return {"median": round(median, 2), "p90": round(p90, 2)}


class CostLedger:
    """Maintains and queries state/cost_ledger.jsonl built from system events."""

    def __init__(self, workspace: Path | str) -> None:
        self.workspace = Path(workspace).resolve()
        self.state_dir = self.workspace / "state"
        self.ledger_file = self.state_dir / "cost_ledger.jsonl"
        self.actions_log = self.workspace / "logs" / "actions.jsonl"

    def ensure_storage(self) -> None:
        """Ensure state directory exists."""
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def load_entries(self) -> list[dict[str, Any]]:
        """Load all entries from state/cost_ledger.jsonl."""
        if not self.ledger_file.exists():
            return []
        entries: list[dict[str, Any]] = []
        try:
            for line in self.ledger_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        except OSError:
            return []
        return entries

    def append_entry(self, entry: dict[str, Any]) -> None:
        """Append a single cost entry to state/cost_ledger.jsonl."""
        self.ensure_storage()
        entry.setdefault("timestamp", now_utc())
        with open(self.ledger_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def build_from_events(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Build cost ledger records from a list of event objects.
        
        Aggregates tokens, LLM calls, wall time, and cycles per create_tool (all attempts
        included) and per plugin project.
        """
        # Map: tool_name -> list of attempts or accumulated stats
        tools_data: dict[str, dict[str, Any]] = {}
        # Map: plugin_name -> accumulated stats
        plugins_data: dict[str, dict[str, Any]] = {}

        for ev in events:
            if not isinstance(ev, dict):
                continue
            event_name = ev.get("event") or ev.get("name")

            # 1. Direct cost summary records
            if event_name in {"tool_cost", "tool_creation_cost"}:
                name = str(ev.get("name") or ev.get("tool") or "unnamed")
                td = tools_data.setdefault(name, {
                    "target": name,
                    "kind": "tool",
                    "tokens": 0,
                    "llm_calls": 0,
                    "wall_time_seconds": 0.0,
                    "cycles": 0,
                    "attempts": 0,
                    "status": "registered" if ev.get("success", True) else "failed",
                })
                td["tokens"] += int(ev.get("tokens", 0))
                td["llm_calls"] += int(ev.get("llm_calls", 0))
                td["wall_time_seconds"] += float(ev.get("wall_time_seconds", ev.get("wall_time", 0.0)))
                td["cycles"] = max(td["cycles"], int(ev.get("cycles", 1)))
                if "attempts" in ev:
                    td["attempts"] = max(td["attempts"], int(ev["attempts"]))
                elif "attempt" in ev:
                    td["attempts"] = max(td["attempts"], int(ev["attempt"]))
                else:
                    td["attempts"] += 1
                if ev.get("status"):
                    td["status"] = ev["status"]

            elif event_name in {"plugin_cost", "plugin_project_cost"}:
                name = str(ev.get("name") or ev.get("plugin") or "unnamed")
                pd = plugins_data.setdefault(name, {
                    "target": name,
                    "kind": "plugin",
                    "tokens": 0,
                    "llm_calls": 0,
                    "wall_time_seconds": 0.0,
                    "cycles": 0,
                    "status": str(ev.get("status", "in_progress")),
                })
                pd["tokens"] += int(ev.get("tokens", 0))
                pd["llm_calls"] += int(ev.get("llm_calls", 0))
                pd["wall_time_seconds"] += float(ev.get("wall_time_seconds", ev.get("wall_time", 0.0)))
                pd["cycles"] = max(pd["cycles"], int(ev.get("cycles", 1)))
                if ev.get("status"):
                    pd["status"] = ev["status"]

            # 2. Granular tool creation events
            elif event_name == "tool_registered":
                name = str(ev.get("name") or "unnamed")
                td = tools_data.setdefault(name, {
                    "target": name,
                    "kind": "tool",
                    "tokens": 0,
                    "llm_calls": 0,
                    "wall_time_seconds": 0.0,
                    "cycles": 1,
                    "attempts": 1,
                    "status": "registered",
                })
                td["status"] = "registered"
                if "tokens" in ev:
                    td["tokens"] += int(ev["tokens"])
                if "llm_calls" in ev:
                    td["llm_calls"] += int(ev["llm_calls"])
                if "wall_time_seconds" in ev or "wall_time" in ev:
                    td["wall_time_seconds"] += float(ev.get("wall_time_seconds", ev.get("wall_time", 0.0)))
                if "cycles" in ev:
                    td["cycles"] = max(td["cycles"], int(ev["cycles"]))
                if "attempts" in ev:
                    td["attempts"] = max(td["attempts"], int(ev["attempts"]))

            elif event_name == "tool_creation_failed":
                name = str(ev.get("name") or "unnamed")
                td = tools_data.setdefault(name, {
                    "target": name,
                    "kind": "tool",
                    "tokens": 0,
                    "llm_calls": 0,
                    "wall_time_seconds": 0.0,
                    "cycles": 1,
                    "attempts": int(ev.get("attempt", 1)),
                    "status": "failed",
                })
                td["attempts"] = max(td["attempts"], int(ev.get("attempt", 1)))
                if "tokens" in ev:
                    td["tokens"] += int(ev["tokens"])
                if "llm_calls" in ev:
                    td["llm_calls"] += int(ev["llm_calls"])
                if "wall_time_seconds" in ev or "wall_time" in ev:
                    td["wall_time_seconds"] += float(ev.get("wall_time_seconds", ev.get("wall_time", 0.0)))

            elif event_name == "tool_critic":
                # Critic call logged per attempt
                name = str(ev.get("name") or "unnamed")
                td = tools_data.setdefault(name, {
                    "target": name,
                    "kind": "tool",
                    "tokens": 0,
                    "llm_calls": 0,
                    "wall_time_seconds": 0.0,
                    "cycles": 1,
                    "attempts": int(ev.get("attempt", 1)),
                    "status": "in_progress",
                })
                td["llm_calls"] += 1
                td["attempts"] = max(td["attempts"], int(ev.get("attempt", 1)))
                if "tokens" in ev:
                    td["tokens"] += int(ev["tokens"])
                if "wall_time_seconds" in ev or "latency_ms" in ev:
                    secs = float(ev.get("wall_time_seconds", float(ev.get("latency_ms", 0)) / 1000.0))
                    td["wall_time_seconds"] += secs

            elif event_name == "tool_test":
                name = str(ev.get("name") or "unnamed")
                td = tools_data.setdefault(name, {
                    "target": name,
                    "kind": "tool",
                    "tokens": 0,
                    "llm_calls": 0,
                    "wall_time_seconds": 0.0,
                    "cycles": 1,
                    "attempts": int(ev.get("attempt", 1)),
                    "status": "in_progress",
                })
                res = ev.get("result")
                if isinstance(res, dict) and "duration" in res:
                    td["wall_time_seconds"] += float(res["duration"])

            # 3. Granular plugin events
            elif event_name in {"plugin_proposed", "plugin_scaffolded", "plugin_tested",
                                "plugin_validated", "plugin_review_completed",
                                "plugin_project_review", "plugin_promoted"}:
                name = str(ev.get("name") or ev.get("plugin") or ev.get("project") or "unnamed")
                pd = plugins_data.setdefault(name, {
                    "target": name,
                    "kind": "plugin",
                    "tokens": 0,
                    "llm_calls": 0,
                    "wall_time_seconds": 0.0,
                    "cycles": 0,
                    "status": "proposed" if event_name == "plugin_proposed" else "in_progress",
                })
                if event_name == "plugin_promoted":
                    pd["status"] = "promoted"
                elif event_name == "plugin_project_review" and ev.get("decision") == "abandon":
                    pd["status"] = "abandoned"

                if "tokens" in ev:
                    pd["tokens"] += int(ev["tokens"])
                if "tokens_spent" in ev:
                    pd["tokens"] = max(pd["tokens"], int(ev["tokens_spent"]))
                if "llm_calls" in ev:
                    pd["llm_calls"] += int(ev["llm_calls"])
                if "wall_time_seconds" in ev or "wall_time" in ev:
                    pd["wall_time_seconds"] += float(ev.get("wall_time_seconds", ev.get("wall_time", 0.0)))
                if "cycles" in ev:
                    pd["cycles"] = max(pd["cycles"], int(ev["cycles"]))
                if "cycles_spent" in ev:
                    pd["cycles"] = max(pd["cycles"], int(ev["cycles_spent"]))

        records: list[dict[str, Any]] = []
        for t in sorted(tools_data.values(), key=lambda x: str(x["target"])):
            t["wall_time_seconds"] = round(t["wall_time_seconds"], 2)
            records.append(t)
        for p in sorted(plugins_data.values(), key=lambda x: str(x["target"])):
            p["wall_time_seconds"] = round(p["wall_time_seconds"], 2)
            records.append(p)

        return records

    def sync_from_log(self) -> list[dict[str, Any]]:
        """Read logs/actions.jsonl, build ledger records, and rewrite cost_ledger.jsonl."""
        if not self.actions_log.exists():
            return self.load_entries()
        events: list[dict[str, Any]] = []
        try:
            for line in self.actions_log.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        except OSError:
            return self.load_entries()

        records = self.build_from_events(events)
        self.ensure_storage()
        with open(self.ledger_file, "w", encoding="utf-8") as f:
            for r in records:
                r.setdefault("timestamp", now_utc())
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        return records

    def get_summary(self) -> dict[str, Any]:
        """Return tool baselines (median & p90) and current plugin project totals."""
        entries = self.load_entries()
        if not entries and self.actions_log.exists():
            entries = self.sync_from_log()

        tool_tokens: list[int] = []
        tool_calls: list[int] = []
        tool_times: list[float] = []
        tool_cycles: list[int] = []
        tool_count = 0

        plugin_projects: dict[str, dict[str, Any]] = {}

        for entry in entries:
            kind = entry.get("kind")
            if kind == "tool":
                tool_count += 1
                tool_tokens.append(int(entry.get("tokens", 0)))
                tool_calls.append(int(entry.get("llm_calls", 0)))
                tool_times.append(float(entry.get("wall_time_seconds", 0.0)))
                tool_cycles.append(int(entry.get("cycles", 1)))
            elif kind == "plugin":
                target = str(entry.get("target") or "unnamed")
                plugin_projects[target] = {
                    "tokens": int(entry.get("tokens", 0)),
                    "llm_calls": int(entry.get("llm_calls", 0)),
                    "wall_time_seconds": round(float(entry.get("wall_time_seconds", 0.0)), 2),
                    "cycles": int(entry.get("cycles", 0)),
                    "status": str(entry.get("status", "unknown")),
                }

        # Safe fallback baseline floor if no historical tool data exists yet
        if tool_count == 0:
            baselines = {
                "tool": {
                    "count": 0,
                    "tokens": {"median": 1500.0, "p90": 3500.0},
                    "llm_calls": {"median": 2.0, "p90": 4.0},
                    "wall_time_seconds": {"median": 15.0, "p90": 45.0},
                    "cycles": {"median": 1.0, "p90": 2.0},
                    "note": "Default baseline floor (no historical create_tool events recorded yet)",
                }
            }
        else:
            baselines = {
                "tool": {
                    "count": tool_count,
                    "tokens": compute_percentiles(tool_tokens),
                    "llm_calls": compute_percentiles(tool_calls),
                    "wall_time_seconds": compute_percentiles(tool_times),
                    "cycles": compute_percentiles(tool_cycles),
                }
            }

        return {
            "ok": True,
            "baselines": baselines,
            "plugin_projects": plugin_projects,
        }
