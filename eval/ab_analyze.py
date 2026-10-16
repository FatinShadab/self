"""Analyze randomized A/B arms separately from observational helper use."""
from __future__ import annotations

import argparse
import json
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from eval.ab_plan import HERE, PLAN_PATH


RESULTS = HERE / "ab" / "results"


def _rate(rows: list[dict]) -> float:
    return sum(bool(row["passed"]) for row in rows) / len(rows)


def summarize(rows: list[dict], *, bootstrap_seed: int = 7, draws: int = 3000) -> dict[str, Any]:
    excluded = [row for row in rows if row.get("contaminated") or row.get("infra_error")]
    clean = [row for row in rows if not (row.get("contaminated") or row.get("infra_error"))]
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in clean:
        grouped[(row["task_id"], row["arm"])].append(row)
    task_ids = sorted({row["task_id"] for row in rows})
    arms = sorted({row["arm"] for row in rows})
    uninformative = []
    for task in task_ids:
        samples = [grouped[(task, arm)] for arm in arms]
        if samples and all(samples) and (all(_rate(sample) == 0 for sample in samples)
                                         or all(_rate(sample) == 1 for sample in samples)):
            uninformative.append(task)
    informative = [task for task in task_ids if task not in uninformative
                   and grouped[(task, "off")] and grouped[(task, "on")]]
    diffs = [_rate(grouped[(task, "on")]) - _rate(grouped[(task, "off")])
             for task in informative]
    pooled = sum(diffs) / len(diffs) if diffs else None
    interval = None
    if informative:
        rng = random.Random(bootstrap_seed)
        samples = []
        for _ in range(draws):
            sampled_diffs = []
            for task in informative:
                off, on = grouped[(task, "off")], grouped[(task, "on")]
                off_rate = sum(rng.choice(off)["passed"] for _ in off) / len(off)
                on_rate = sum(rng.choice(on)["passed"] for _ in on) / len(on)
                sampled_diffs.append(on_rate - off_rate)
            samples.append(sum(sampled_diffs) / len(sampled_diffs))
        samples.sort()
        interval = (samples[int(0.025 * (draws - 1))], samples[int(0.975 * (draws - 1))])
    on_rows = [row for row in clean if row["arm"] == "on"]
    helper_used = [row for row in on_rows if row.get("helper_calls", 0) > 0 or
                   any(model != row.get("base_model", "") for model in row.get("models_actually_called", []))]
    return {
        "clean": clean, "excluded": excluded, "grouped": grouped,
        "arms": arms, "tasks": task_ids, "uninformative": uninformative,
        "informative": informative, "pooled_difference": pooled,
        "bootstrap_interval": interval,
        "on_beats": sum(value > 0 for value in diffs),
        "on_ties": sum(value == 0 for value in diffs),
        "on_loses": sum(value < 0 for value in diffs),
        "on_rows": on_rows, "helper_used": helper_used,
    }


def render(rows: list[dict], *, calibration: dict | None = None) -> str:
    data = summarize(rows)
    lines = [f"A/B results: valid_runs={len(data['clean'])} excluded={len(data['excluded'])}",
             "Off arm prompt is slightly shorter by design.", "", "Per task and arm:"]
    for task in data["tasks"]:
        for arm in data["arms"]:
            sample = data["grouped"][(task, arm)]
            if sample:
                lines.append(f"  {task} {arm}: successes={sum(row['passed'] for row in sample)}/{len(sample)} "
                             f"mean_score={sum(row['score'] for row in sample)/len(sample):.3f} n={len(sample)}")
            else:
                lines.append(f"  {task} {arm}: successes=0/0 mean_score=n/a n=0")
    lines.append("Uninformative ceiling/floor tasks: " + (", ".join(data["uninformative"]) or "none"))
    lines.append(f"Informative tasks with both off and on: n={len(data['informative'])}")
    interval = data["bootstrap_interval"]
    if interval is None:
        lines.append("Pooled on-minus-off success difference: no comparison yet.")
    else:
        lo, hi = interval
        lines.append(f"Pooled on-minus-off success difference={data['pooled_difference']:+.3f}; "
                     f"95% bootstrap interval=[{lo:+.3f}, {hi:+.3f}]; "
                     f"runs_off={sum(len(data['grouped'][(task,'off')]) for task in data['informative'])} "
                     f"runs_on={sum(len(data['grouped'][(task,'on')]) for task in data['informative'])}")
        lines.append("Interval excludes zero." if lo > 0 or hi < 0 else
                     "Interval includes zero; no significance claim.")
        lines.append(f"Task outcomes: on beats={data['on_beats']} ties={data['on_ties']} loses={data['on_loses']}.")
    lines += ["", "OBSERVATIONAL: on-arm helper use, not a randomized comparison."]
    on_rows = data["on_rows"]
    used = data["helper_used"]
    lines.append(f"Helper usage rate={len(used)}/{len(on_rows)}" if on_rows else "Helper usage: no on-arm data yet.")
    for label, sample in (("with_helper", used), ("without_helper", [r for r in on_rows if r not in used])):
        if sample:
            lines.append(f"  {label}: successes={sum(r['passed'] for r in sample)}/{len(sample)} n={len(sample)}")
    by_model_category: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in used:
        for model in row.get("models_actually_called", []):
            if model != row.get("base_model"):
                by_model_category[(model, row["category"])].append(row)
    for (model, category), sample in sorted(by_model_category.items()):
        lines.append(f"  model={model} category={category}: successes={sum(r['passed'] for r in sample)}/{len(sample)} n={len(sample)}")
    origins = Counter()
    for row in on_rows:
        origins.update(row.get("decision_origins", {}))
    total = sum(origins.values())
    forced = sum(count for origin, count in origins.items() if origin != "model_choice")
    lines.append(f"Decision origins={dict(origins)}; model_choice={origins['model_choice']}/{total}; forced_defaults={forced}/{total}" if total else
                 "Decision origins: no data yet.")
    if calibration:
        category_map = {"create_tool": "code", "data_and_code": "code",
                        "extraction_and_summary": "summarization", "container_investigation": "reasoning"}
        lines += ["", "Latest calibration: helper choices and measured category scores:"]
        for (model, category), sample in sorted(by_model_category.items()):
            measured = calibration.get("scores", {}).get(model, {}).get(category_map.get(category, ""), {}).get("mean")
            lines.append(f"  {model} {category}: measured_score={measured if measured is not None else 'n/a'} n={len(sample)}")
    else:
        lines += ["", "Latest calibration: no data yet."]
    if data["excluded"]:
        lines += ["", "Excluded runs (counted above):"]
        for row in data["excluded"]:
            lines.append(f"  {row['run_id']}: contaminated={row.get('contaminated', False)} infra_error={row.get('infra_error', False)}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Analyze A/B result records.")
    parser.add_argument("--results", type=Path, default=RESULTS)
    args = parser.parse_args(argv)
    rows = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(args.results.glob("*.json"))]
    if PLAN_PATH.exists():
        plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
        campaign = plan.get("campaign_id", "").split("-", 1)[0]
        rows = [row for row in rows if row.get("campaign", "full") == campaign
                and row.get("plan_seed") == plan.get("plan_seed")]
    calibration_files = sorted((HERE / "results").glob("*.json"))
    calibration = json.loads(calibration_files[-1].read_text(encoding="utf-8")) if calibration_files else None
    print(render(rows, calibration=calibration))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
