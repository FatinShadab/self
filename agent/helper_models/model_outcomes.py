"""Append-only, provenance-labelled outcomes linked to model decisions."""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.infra.event_log import EventLogger
from agent.infra.file_lock import locked_file


SELF_REPORTED_USEFULNESS = {"used", "partly_used", "not_used", "wrong"}


class ModelOutcomes:
    def __init__(self, workspace: str | Path, logger: EventLogger) -> None:
        self.path = Path(workspace) / "state" / "model_outcomes.jsonl"
        self.lock_path = self.path.with_suffix(".lock")
        self.logger = logger

    def append(self, call_id: str, model: str, source: str, signal: str,
               value: Any, provenance: str, *, session_id: str,
               task_id: str | None = None, tool_name: str | None = None,
               attempt: int | None = None) -> None:
        if provenance not in {"objective", "self_reported"}:
            raise ValueError("Outcome provenance must be objective or self_reported")
        if not call_id or not signal or not session_id:
            raise ValueError("Outcome call id, signal, and session id are required")
        row = {"call_id": call_id, "session_id": session_id, "task_id": task_id,
               "model": model, "source": source, "tool_name": tool_name,
               "attempt": attempt, "signal": signal,
               "value": value, "provenance": provenance,
               "timestamp": datetime.now(timezone.utc).isoformat()}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with locked_file(self.lock_path):
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(self.logger.redactor.value(row), ensure_ascii=False) + "\n")


def print_outcome_summary(workspace: str | Path = "/home/entity", *, output: Any = None) -> None:
    """Small descriptive tally; do not infer causality from these rates."""
    state = Path(workspace) / "state"
    decisions: dict[str, dict[str, Any]] = {}
    try:
        with (state / "model_decisions.jsonl").open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                    if isinstance(row, dict) and row.get("call_id"):
                        decisions[row["call_id"]] = row
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    outcomes: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    baseline: list[dict[str, Any]] = []
    try:
        with (state / "model_outcomes.jsonl").open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(row, dict):
                    continue
                if row.get("source") == "task_baseline":
                    baseline.append(row)
                else:
                    outcomes[(str(row.get("model")), str(row.get("source")))].append(row)
    except OSError:
        pass
    counts: Counter[tuple[str, str]] = Counter(
        (str(row.get("model")), str(row.get("source"))) for row in decisions.values())
    stream = output or sys.stdout
    for key in sorted(set(counts) | set(outcomes)):
        model, source = key
        rows = outcomes[key]
        print(f"model={model} source={source} calls={counts[key]}", file=stream)
        objective: dict[str, list[Any]] = defaultdict(list)
        reported: Counter[str] = Counter()
        for row in rows:
            if row.get("provenance") == "objective":
                objective[str(row.get("signal"))].append(row.get("value"))
            elif row.get("provenance") == "self_reported" and row.get("signal") == "usefulness":
                reported[str(row.get("value"))] += 1
        for signal, values in sorted(objective.items()):
            if all(isinstance(value, bool) for value in values):
                successes = sum(values)
                print(f"  objective {signal}: {successes}/{len(values)} ({successes / len(values):.1%})", file=stream)
            else:
                print(f"  objective {signal}: n={len(values)} values={json.dumps(dict(Counter(map(str, values))), sort_keys=True)}", file=stream)
        print(f"  self_reported usefulness: n={sum(reported.values())} {json.dumps(dict(sorted(reported.items())))}", file=stream)
    by_signal: dict[str, list[Any]] = defaultdict(list)
    for row in baseline:
        if row.get("provenance") == "objective":
            by_signal[str(row.get("signal"))].append(row.get("value"))
    task_count = len({row.get("call_id") for row in baseline})
    print(f"tasks_without_helpers={task_count}", file=stream)
    for signal, values in sorted(by_signal.items()):
        if all(isinstance(value, bool) for value in values):
            successes = sum(values)
            print(f"  objective {signal}: {successes}/{len(values)} ({successes / len(values):.1%})", file=stream)
        else:
            print(f"  objective {signal}: n={len(values)} values={json.dumps(dict(Counter(map(str, values))), sort_keys=True)}", file=stream)


if __name__ == "__main__":
    print_outcome_summary(sys.argv[1] if len(sys.argv) > 1 else "/home/entity")
