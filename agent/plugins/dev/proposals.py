"""Plugin proposal validation, cost ledger derivation checks, and milestone creation."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from agent.infra.cost_ledger import CostLedger
from agent.infra.event_log import EventLogger
from agent.plugins.dev.environment import now_utc


def list_proposals(proposals_file: Path) -> list[dict[str, Any]]:
    """Return all proposals from state/plugin_proposals.jsonl."""
    if not proposals_file.exists():
        return []
    proposals: list[dict[str, Any]] = []
    try:
        for line in proposals_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    proposals.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return proposals


def get_proposal(proposals_file: Path, name: str) -> dict[str, Any] | None:
    """Fetch proposal by name from state/plugin_proposals.jsonl."""
    for p in list_proposals(proposals_file):
        if p.get("name") == name:
            return p
    return None


def validate_derivation(
    derivation: str,
    cost_ledger: CostLedger,
) -> tuple[bool, str]:
    """Validate that derivation cites measured cost ledger data consistently."""
    clean_deriv = derivation.strip().lower()
    if not clean_deriv:
        return False, "Proposal estimate 'derivation' field cannot be empty."

    ledger_keywords = {
        "ledger", "baseline", "median", "p90", "cost_ledger",
        "measured", "bootstrap", "cold_start", "floor", "initial",
    }
    has_ledger_ref = any(kw in clean_deriv for kw in ledger_keywords)
    summary = cost_ledger.get_summary()
    tool_baselines = summary.get("baselines", {}).get("tool", {})
    tokens_base = tool_baselines.get("tokens", {})
    actual_median = int(tokens_base.get("median", 0))
    actual_p90 = int(tokens_base.get("p90", 0))

    if not has_ledger_ref:
        if actual_p90 and str(actual_p90) in clean_deriv:
            has_ledger_ref = True
        elif actual_median and str(actual_median) in clean_deriv:
            has_ledger_ref = True

    if not has_ledger_ref:
        return (
            False,
            "Estimate derivation must explicitly reference measured cost ledger data (cite ledger baselines, median, p90, bootstrap floor, or read_cost_ledger values).",
        )

    tokens_in_derivation = clean_deriv.split()
    has_digits = bool(re.search(r"\d+", clean_deriv))
    if len(tokens_in_derivation) <= 3 and not has_digits:
        return (
            False,
            "Estimate derivation cannot simply contain a keyword; it must explain an arithmetic calculation or breakdown citing measured values or bootstrap floor.",
        )

    actual_count = int(tool_baselines.get("count", 0))
    if actual_count == 0:
        claimed_numbers = re.findall(
            r"(?:baseline|recorded|measured|historical)(?:\s+tool)?(?:\s+tokens)?(?:\s+of|\s+is|\s*[:=])?\s*(\d+)",
            clean_deriv,
        )
        for m in claimed_numbers:
            val = int(m)
            if val not in {1500, 3500}:
                return (
                    False,
                    f"Cost ledger contains 0 recorded tool baselines. Cannot claim non-zero measured baseline of {val} tokens when ledger is empty.",
                )

    if actual_median > 0:
        median_matches = re.findall(
            r"median(?:\s+tool)?(?:\s+tokens)?(?:\s+of|\s+is|\s*[:=])?\s*(\d+)",
            clean_deriv,
        )
        for m in median_matches:
            val = int(m)
            if abs(val - actual_median) > max(10, 0.2 * actual_median):
                return (
                    False,
                    f"Estimate derivation claims tool median of {val} tokens, but ledger recorded median is {actual_median} tokens. Numbers cited must match the measured cost ledger.",
                )

    if actual_p90 > 0:
        p90_matches = re.findall(
            r"p90(?:\s+tool)?(?:\s+tokens)?(?:\s+of|\s+is|\s*[:=])?\s*(\d+)",
            clean_deriv,
        )
        for m in p90_matches:
            val = int(m)
            if abs(val - actual_p90) > max(10, 0.2 * actual_p90):
                return (
                    False,
                    f"Estimate derivation claims tool p90 of {val} tokens, but ledger recorded p90 is {actual_p90} tokens. Numbers cited must match the measured cost ledger.",
                )

    return True, ""


def validate_and_record_proposal(
    proposals_file: Path,
    cost_ledger: CostLedger,
    logger: EventLogger,
    name: str,
    need: str,
    evidence: str,
    alternatives_considered: Any,
    estimate: dict[str, Any] | str,
    expected_benefit: str,
    actions_needed_with_risk_levels: Any,
    maintenance_burden: str,
    stop_loss: Any,
    rollback: str,
    plan_store: Any | None = None,
    cycle: int = 1,
) -> dict[str, Any]:
    """Validate and record a plugin proposal with required cost derivation."""
    clean_name = str(name).strip()
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", clean_name):
        return {
            "ok": False,
            "error": f"Plugin name '{clean_name}' must be lowercase snake_case (letters, digits, underscore, max 64 chars).",
        }

    fields = {
        "need": str(need).strip(),
        "evidence": str(evidence).strip(),
        "alternatives_considered": alternatives_considered,
        "expected_benefit": str(expected_benefit).strip(),
        "actions_needed_with_risk_levels": actions_needed_with_risk_levels,
        "maintenance_burden": str(maintenance_burden).strip(),
        "stop_loss": stop_loss,
        "rollback": str(rollback).strip(),
    }
    for field_name, field_val in fields.items():
        if not field_val or (isinstance(field_val, str) and not field_val.strip()):
            return {"ok": False, "error": f"Required proposal field '{field_name}' cannot be empty."}

    parsed_estimate: dict[str, Any] = {}
    if isinstance(estimate, str):
        try:
            parsed_estimate = json.loads(estimate)
        except Exception:
            return {"ok": False, "error": "Field 'estimate' must be a valid JSON object or dict."}
    elif isinstance(estimate, dict):
        parsed_estimate = dict(estimate)
    else:
        return {"ok": False, "error": "Field 'estimate' must be a dict or valid JSON object."}

    required_estimate_keys = {"tokens", "cycles", "wall_time", "human_review_minutes", "derivation"}
    missing_keys = required_estimate_keys - set(parsed_estimate.keys())
    if missing_keys:
        return {
            "ok": False,
            "error": f"Proposal estimate is missing required cost fields: {sorted(missing_keys)}. All fields (tokens, cycles, wall_time, human_review_minutes, derivation) are required.",
        }

    derivation = str(parsed_estimate.get("derivation", ""))
    valid_deriv, err_msg = validate_derivation(derivation, cost_ledger)
    if not valid_deriv:
        return {"ok": False, "error": err_msg}

    proposal_record = {
        "name": clean_name,
        "timestamp": now_utc(),
        "status": "proposed",
        "need": fields["need"],
        "evidence": fields["evidence"],
        "alternatives_considered": alternatives_considered,
        "estimate": parsed_estimate,
        "expected_benefit": fields["expected_benefit"],
        "actions_needed_with_risk_levels": actions_needed_with_risk_levels,
        "maintenance_burden": fields["maintenance_burden"],
        "stop_loss": stop_loss,
        "rollback": fields["rollback"],
        "cycle": cycle,
        "comments": [],
    }

    proposals_file.parent.mkdir(parents=True, exist_ok=True)
    with open(proposals_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(proposal_record, ensure_ascii=False) + "\n")

    milestones = [
        f"[plugin_project:{clean_name}] 1. Scaffold draft and declare manifest in workspace/plugin_dev/{clean_name}",
        f"[plugin_project:{clean_name}] 2. Implement handlers in plugin.py under declared permission levels",
        f"[plugin_project:{clean_name}] 3. Write unit tests and SimBody simulation tests in tests/",
        f"[plugin_project:{clean_name}] 4. Pass static validate_plugin checks and request critic review",
        f"[plugin_project:{clean_name}] 5. Prepare review diff and permission summary for human promotion",
    ]

    if plan_store is not None and hasattr(plan_store, "update_plan"):
        for m in milestones:
            plan_store.update_plan(
                action="add",
                goal=m,
                priority=2,
                reason=f"Plugin project proposal {clean_name} milestone",
                cycle=cycle,
                source=f"plugin_project:{clean_name}",
            )

    logger.log(
        "plugin_proposed",
        name=clean_name,
        need=fields["need"][:200],
        token_estimate=parsed_estimate.get("tokens"),
        cycle_estimate=parsed_estimate.get("cycles"),
    )

    return {
        "ok": True,
        "name": clean_name,
        "status": "proposed",
        "proposal_file": str(proposals_file),
        "milestones": milestones,
        "message": f"Plugin proposal for '{clean_name}' recorded in state/plugin_proposals.jsonl and added to plan.",
    }
