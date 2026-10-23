"""Stop-loss review tracking and threshold evaluation."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent.infra.cost_ledger import CostLedger


def find_proposal(proposals_file: Path, name: str) -> dict[str, Any] | None:
    """Fetch proposal by name from proposals file."""
    if not proposals_file.exists():
        return None
    try:
        for line in proposals_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    p = json.loads(line)
                    if isinstance(p, dict) and p.get("name") == name:
                        return p
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return None


def get_pending_stop_loss(
    proposals_file: Path,
    cost_ledger: CostLedger,
    reviewed_thresholds: dict[str, set[int]],
    name: str,
) -> list[int]:
    """Check if any stop-loss review threshold (25, 50, 100) is reached but unacknowledged."""
    proposal = find_proposal(proposals_file, name)
    if not proposal:
        return []
    est = proposal.get("estimate", {})
    tokens_est = est.get("tokens", {}) if isinstance(est.get("tokens"), dict) else {}
    cycles_est = est.get("cycles", {}) if isinstance(est.get("cycles"), dict) else {}
    max_tokens = tokens_est.get("max", 0)
    max_cycles = cycles_est.get("max", 0)
    if not max_tokens and not max_cycles:
        return []

    ledger_summary = cost_ledger.get_summary()
    proj_data = ledger_summary.get("plugin_projects", {}).get(name, {})
    spent_tokens = proj_data.get("tokens", 0)
    spent_cycles = proj_data.get("cycles", 0)

    reviewed = reviewed_thresholds.setdefault(name, set())
    pending = []
    for pct in (25, 50, 100):
        if pct not in reviewed:
            tok_thresh = (pct / 100.0) * max_tokens if max_tokens else 999999999
            cyc_thresh = (pct / 100.0) * max_cycles if max_cycles else 999999999
            if (max_tokens and spent_tokens >= tok_thresh) or (max_cycles and spent_cycles >= cyc_thresh):
                pending.append(pct)
    return pending


def record_review_decision(
    reviewed_thresholds: dict[str, set[int]],
    name: str,
    threshold: int,
) -> None:
    """Mark a stop-loss review threshold as acknowledged and reviewed."""
    reviewed_thresholds.setdefault(name, set()).add(threshold)
