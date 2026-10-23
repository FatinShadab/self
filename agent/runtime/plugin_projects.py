"""Active plugin projects stop-loss budget checking and prompt formatting."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent.prompts.cycle import build_active_plugin_project_part


def check_active_plugin_projects(
    workspace: Path,
    plan_store: Any,
    cost_ledger: Any,
    reviewed_thresholds: dict[str, set[int]],
    cycle: int,
) -> str:
    """Check active plugin projects for exploration nudge and stop-loss reviews."""
    proposals_file = workspace / "state" / "plugin_proposals.jsonl"
    if not proposals_file.exists():
        return ""

    proposals: list[dict[str, Any]] = []
    try:
        for line in proposals_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                proposals.append(json.loads(line))
    except OSError:
        return ""

    active = [p for p in proposals if p.get("status") in {"proposed", "in_progress"}]
    if not active:
        return ""

    summary_parts: list[str] = []
    for p in active:
        p_name = p.get("name", "unknown")
        est = p.get("estimate", {})
        tokens_est = est.get("tokens", {})
        cycles_est = est.get("cycles", {})
        max_tokens = tokens_est.get("max", 0) if isinstance(tokens_est, dict) else 0
        max_cycles = cycles_est.get("max", 0) if isinstance(cycles_est, dict) else 0

        ledger_summary = cost_ledger.get_summary() if cost_ledger is not None else {}
        proj_data = ledger_summary.get("plugin_projects", {}).get(p_name, {})
        spent_tokens = proj_data.get("tokens", 0)
        spent_cycles = proj_data.get("cycles", 0)

        milestone_str = "Scaffold and manifest definition"
        if plan_store is not None:
            for item in getattr(plan_store, "items", []):
                goal_str = str(item.get("goal", ""))
                if f"plugin_project:{p_name}" in goal_str or f"[{p_name}]" in goal_str:
                    if str(item.get("status", "")).lower() not in {"done", "completed"}:
                        milestone_str = goal_str
                        break

        pending_stop_loss = []
        for pct in (25, 50, 100):
            if pct not in reviewed_thresholds.setdefault(p_name, set()):
                tok_thresh = (pct / 100.0) * max_tokens if max_tokens else 999999999
                cyc_thresh = (pct / 100.0) * max_cycles if max_cycles else 999999999
                if (max_tokens and spent_tokens >= tok_thresh) or (max_cycles and spent_cycles >= cyc_thresh):
                    pending_stop_loss.append(pct)

        highest_thresh = max(pending_stop_loss) if pending_stop_loss else None
        summary_parts.append(
            build_active_plugin_project_part(
                name=p_name,
                milestone=milestone_str,
                spent_tokens=spent_tokens,
                spent_cycles=spent_cycles,
                tokens_est=tokens_est,
                cycles_est=cycles_est,
                pending_stop_loss_pct=highest_thresh,
            )
        )

    return "\n\n".join(summary_parts) + "\n\n"
