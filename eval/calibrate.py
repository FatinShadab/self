"""Host-side comparison of pre-benchmark agent ratings with hidden eval scores."""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
CATEGORIES = ("reasoning", "code", "instruction_following", "summarization", "json_output")
RATING_SCORE = {"low": 1, "medium": 2, "high": 3}


def _ranks(values: list[float]) -> list[float]:
    ranked = sorted(enumerate(values), key=lambda pair: pair[1])
    result = [0.0] * len(values)
    start = 0
    while start < len(ranked):
        end = start + 1
        while end < len(ranked) and ranked[end][1] == ranked[start][1]:
            end += 1
        mean_rank = (start + 1 + end) / 2
        for index, _ in ranked[start:end]:
            result[index] = mean_rank
        start = end
    return result


def spearman(pairs: list[tuple[float, float]]) -> float | None:
    """Compute Spearman rank correlation for paired values."""
    if len(pairs) < 2:
        return None
    left = _ranks([pair[0] for pair in pairs])
    right = _ranks([pair[1] for pair in pairs])
    mean_left, mean_right = sum(left) / len(left), sum(right) / len(right)
    numerator = sum((a - mean_left) * (b - mean_right) for a, b in zip(left, right))
    denominator = math.sqrt(sum((a - mean_left) ** 2 for a in left) *
                            sum((b - mean_right) ** 2 for b in right))
    return numerator / denominator if denominator else None


def matching_category(task_type: str) -> str | None:
    """Map a decision task type to a benchmark category."""
    value = task_type.casefold().replace("-", "_")
    if "json" in value:
        return "json_output"
    if "summar" in value:
        return "summarization"
    if "instruction" in value or "format" in value:
        return "instruction_following"
    if "code" in value or "critic" in value or "create_tool" in value:
        return "code"
    if "reason" in value or "plan" in value:
        return "reasoning"
    return None


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def report(registry: dict[str, Any], benchmark: dict[str, Any],
           decisions: list[dict[str, Any]], *, output: Any = None) -> None:
    """Print calibration between agent ratings and measured benchmark scores."""
    stream = output or sys.stdout
    started = datetime.fromisoformat(benchmark["started_at"].replace("Z", "+00:00"))
    entries = {entry["name"]: entry for entry in registry["models"]}
    scores = benchmark["scores"]
    category_rhos = []
    print(f"benchmark_started={benchmark['started_at']} models_scored={len(scores)}", file=stream)
    for category in CATEGORIES:
        print(f"\n{category}:", file=stream)
        pairs: list[tuple[float, float]] = []
        rows = []
        for model, category_scores in sorted(scores.items()):
            metric = category_scores.get(category, {})
            measured = metric.get("mean")
            entry = entries.get(model, {})
            ratings = entry.get("ratings") or {}
            rating = ratings.get(category, "missing")
            ratings_at = entry.get("ratings_at")
            tainted = bool(ratings_at and datetime.fromisoformat(str(ratings_at).replace("Z", "+00:00")) > started)
            status = "TAINTED" if tainted else "missing" if rating == "missing" else "unknown" if rating == "unknown" else "pre-benchmark"
            rows.append((model, rating, measured, metric, status))
            if rating in RATING_SCORE and measured is not None and not tainted:
                pairs.append((float(RATING_SCORE[rating]), float(measured)))
        for model, rating, measured, metric, status in rows:
            print(f"  {model}: agent={rating} measured={_fmt(measured)} "
                  f"n={metric.get('conclusive', 0)} inconclusive={metric.get('inconclusive', 0)} {status}", file=stream)
        agreement = 0
        compared = 0
        for index, first in enumerate(pairs):
            for second in pairs[index + 1:]:
                if first[0] == second[0] or first[1] == second[1]:
                    continue
                compared += 1
                agreement += (first[0] - second[0]) * (first[1] - second[1]) > 0
        rho = spearman(pairs)
        if rho is not None:
            category_rhos.append(rho)
        print(f"  ordering_agreement={agreement}/{compared} pairs spearman={_fmt(rho)} models_used={len(pairs)}", file=stream)
    overall = sum(category_rhos) / len(category_rhos) if category_rhos else None
    print(f"\noverall_mean_spearman={_fmt(overall)} categories_used={len(category_rhos)}", file=stream)
    print("Caveat: rank agreement is weak with few models, tied ratings, or missing pre-benchmark ratings.", file=stream)
    base = registry["base_model"]
    counts = {category: {"at_or_above": 0, "below": 0, "unmatched": 0}
              for category in CATEGORIES}
    for row in decisions:
        if row.get("origin") != "model_choice" or row.get("model") == base:
            continue
        category = matching_category(str(row.get("task_type", "")))
        if category is None:
            continue
        helper_score = scores.get(row["model"], {}).get(category, {}).get("mean")
        base_score = scores.get(base, {}).get(category, {}).get("mean")
        if helper_score is None or base_score is None:
            counts[category]["unmatched"] += 1
        elif helper_score >= base_score:
            counts[category]["at_or_above"] += 1
        else:
            counts[category]["below"] += 1
    print("\nhelper choices by matching task_type (origin=model_choice):", file=stream)
    for category, values in counts.items():
        print(f"  {category}: at_or_above_base={values['at_or_above']} "
              f"below_base={values['below']} unmatched={values['unmatched']}", file=stream)


def main(argv: list[str] | None = None) -> int:
    """Parse command-line arguments and run this module's entry point."""
    args = argv or []
    workspace = Path(args[0]) if args else HERE.parent / "workspace"
    results = sorted((HERE / "results").glob("*.json"))
    if not results:
        print("No hidden benchmark result found; run the eval service first.")
        return 1
    registry = json.loads((workspace / "state" / "models.json").read_text(encoding="utf-8"))
    benchmark = json.loads(results[-1].read_text(encoding="utf-8"))
    decisions = []
    try:
        with (workspace / "state" / "model_decisions.jsonl").open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    decisions.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    report(registry, benchmark, decisions)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
