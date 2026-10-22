"""Live Soak Gate: post-run invariant verification for workspace states.

Evaluates workspace state read-only against the core soak invariants:
1. Handoff size cap (<= 6,000 chars/bytes).
2. Recursive nesting prevention ('Session complete after' <= 1).
3. Autonomous plan activity (plan events recorded).
4. Failure classes and error recovery (tool failures, API errors, crash loops).
5. Growth bounds (action log size, memory bounds).
6. Token ledger integrity (0 leaked active reservations).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple


def evaluate_workspace(workspace_path: Path) -> List[Tuple[str, str, str]]:
    """Evaluate workspace invariants and return list of (status, check_name, detail)."""
    results: List[Tuple[str, str, str]] = []

    # 1. Handoff Size Check
    handoff_json = workspace_path / "state" / "handoff.json"
    handoff_md = workspace_path / "state" / "handoff.md"
    handoff_overflow = workspace_path / "state" / "handoff_overflow.json"

    handoff_content = ""
    handoff_size = 0
    if handoff_json.exists():
        handoff_size = handoff_json.stat().st_size
        try:
            handoff_content = handoff_json.read_text(encoding="utf-8")
        except Exception as exc:
            handoff_content = ""
    elif handoff_md.exists():
        handoff_size = handoff_md.stat().st_size
        try:
            handoff_content = handoff_md.read_text(encoding="utf-8")
        except Exception:
            handoff_content = ""

    if not handoff_content:
        results.append(("FAIL", "Handoff Size", "No handoff file found in state/"))
    else:
        # Check size <= 6000
        overflow_note = " (overflow archived)" if handoff_overflow.exists() else ""
        if handoff_size <= 6000:
            results.append(("PASS", "Handoff Size", f"{handoff_size:,} bytes <= 6,000 cap{overflow_note}"))
        else:
            results.append(("FAIL", "Handoff Size", f"{handoff_size:,} bytes exceeds 6,000 cap{overflow_note}"))

    # 2. Handoff Recursive Nesting
    if handoff_content:
        repeats = len(re.findall(r"Session complete after", handoff_content))
        if repeats <= 1:
            results.append(("PASS", "Handoff Recursive Nesting", f"{repeats} occurrence(s) of 'Session complete after' (cap <= 1)"))
        else:
            results.append(("FAIL", "Handoff Recursive Nesting", f"Found {repeats} occurrences of 'Session complete after' (nested framing detected)"))
    else:
        results.append(("WARN", "Handoff Recursive Nesting", "No handoff text to inspect"))

    # 3. Autonomous Plan Activity
    actions_log = workspace_path / "logs" / "actions.jsonl"
    plan_file = workspace_path / "state" / "plan.json"

    plan_events_count = 0
    total_events = 0
    create_tool_failures = 0
    api_errors = 0
    unhandled_errors = 0

    if actions_log.exists():
        try:
            with open(actions_log, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    total_events += 1
                    try:
                        data = json.loads(line)
                    except Exception:
                        continue

                    ev = str(data.get("event", ""))
                    act = str(data.get("action", ""))
                    typ = str(data.get("type", ""))

                    if (
                        ev.startswith("plan_")
                        or act == "plan"
                        or typ == "plan"
                        or "plan" in ev
                    ):
                        plan_events_count += 1

                    # Tool failures
                    if act == "create_tool" and data.get("status") in ("failed", "error"):
                        create_tool_failures += 1
                    elif ev in ("tool_execution_failed", "create_tool_failed"):
                        create_tool_failures += 1

                    # API errors
                    err_msg = str(data.get("error", "")) + str(data.get("exception", "")) + str(data.get("detail", ""))
                    if any(e in err_msg for e in ("APIConnectionError", "InternalServerError", "APITimeoutError", "RateLimitError")):
                        api_errors += 1
                    if "panic" in err_msg.lower() or "unhandled" in err_msg.lower():
                        unhandled_errors += 1
        except Exception as exc:
            results.append(("WARN", "Log Read", f"Error reading actions.jsonl: {exc}"))

    plan_items_count = 0
    if plan_file.exists():
        try:
            plan_data = json.loads(plan_file.read_text(encoding="utf-8"))
            if isinstance(plan_data, dict):
                plan_items_count = len(plan_data.get("items", [])) or len(plan_data.get("steps", []))
            elif isinstance(plan_data, list):
                plan_items_count = len(plan_data)
        except Exception:
            pass

    if plan_events_count > 0 or plan_items_count > 0:
        results.append(("PASS", "Plan Activity", f"{plan_events_count} plan events in log, {plan_items_count} items in plan.json"))
    else:
        results.append(("FAIL", "Plan Activity", "Zero plan events logged and no plan items found in plan.json"))

    # 4. Failure Classes & Error Recovery
    if create_tool_failures >= 5 or unhandled_errors > 0:
        results.append(
            (
                "FAIL",
                "Failure Recovery",
                f"{create_tool_failures} create_tool failures, {unhandled_errors} broker panics/unhandled errors",
            )
        )
    elif api_errors > 50:
        results.append(
            (
                "FAIL",
                "Failure Recovery",
                f"Severe API error storm detected ({api_errors} errors); loop failed to maintain forward progress",
            )
        )
    elif api_errors > 0:
        results.append(
            (
                "WARN",
                "Failure Recovery",
                f"{api_errors} transient API errors logged, recovered without crash ({create_tool_failures} tool failures)",
            )
        )
    else:
        results.append(
            (
                "PASS",
                "Failure Recovery",
                f"Clean execution ({create_tool_failures} tool failures, {api_errors} API errors, {unhandled_errors} crashes)",
            )
        )

    # 5. Workspace Growth Bounds
    log_size = actions_log.stat().st_size if actions_log.exists() else 0
    if log_size > 50 * 1024 * 1024:
        results.append(("FAIL", "Growth Bounds", f"Action log size excessive: {log_size / (1024*1024):.1f} MB > 50 MB"))
    elif total_events > 0 and log_size < 100 * 1024 * 1024:
        results.append(("PASS", "Growth Bounds", f"Action log bounded: {log_size / 1024:.1f} KB ({total_events} events)"))
    else:
        results.append(("WARN", "Growth Bounds", f"Action log missing or empty ({log_size} bytes)"))

    # 6. Token Ledger State
    ledger_path = workspace_path / "state" / "token_ledger.json"
    if ledger_path.exists():
        try:
            ledger_data = json.loads(ledger_path.read_text(encoding="utf-8"))
            reserved = int(ledger_data.get("reserved_tokens", 0))
            if reserved == 0:
                results.append(("PASS", "Token Ledger", "0 active reservations at boundary"))
            else:
                results.append(("FAIL", "Token Ledger", f"Leaked active reservations: {reserved} tokens > 0"))
        except Exception as exc:
            results.append(("WARN", "Token Ledger", f"Could not parse token_ledger.json: {exc}"))
    else:
        # Not all setups use token_ledger.json
        results.append(("PASS", "Token Ledger", "token_ledger.json absent or not configured"))

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Live soak gate invariant validator.")
    parser.add_argument("--workspace", default="workspace", help="Path to workspace directory")
    parser.add_argument("--fail-on-warn", action="store_true", help="Fail if any check produces WARN")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    args = parser.parse_args()

    ws = Path(args.workspace).resolve()
    if not ws.exists():
        print(f"ERROR: Workspace directory not found: {ws}", file=sys.stderr)
        return 1

    results = evaluate_workspace(ws)

    if args.json:
        out = [{"status": s, "check": c, "detail": d} for s, c, d in results]
        print(json.dumps(out, indent=2))
    else:
        print("=" * 72)
        print("SELF LIVE SOAK GATE (INVARIANT EVALUATION)")
        print(f"Workspace: {ws}")
        print("=" * 72)
        for status, name, detail in results:
            print(f"[{status:<4}] {name:<28} : {detail}")
        print("=" * 72)

    has_fail = any(s == "FAIL" for s, _, _ in results)
    has_warn = any(s == "WARN" for s, _, _ in results)

    if has_fail:
        if not args.json:
            print("OVERALL RESULT: FAILED (one or more invariants violated)")
        return 1
    elif has_warn and args.fail_on_warn:
        if not args.json:
            print("OVERALL RESULT: FAILED (--fail-on-warn active and warnings present)")
        return 1
    else:
        if not args.json:
            print("OVERALL RESULT: PASSED (all invariants satisfied)")
        return 0


if __name__ == "__main__":
    sys.exit(main())
