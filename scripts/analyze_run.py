#!/usr/bin/env python3
"""analyze_run.py - Detailed log analysis for 30-cycle autonomous runs (Prompt 18).

Analyzes:
1. Plan activity: count and ratio of plan_updated vs plan_unchanged (agent vs harness_auto)
2. Handoff growth: character count, line count, threshold check (6000 chars), overflow archives
3. Human input decisions: breakdown by accepted, modified, declined, deferred, noted
4. Failure types: tool execution failures, llm_call_failed (400, 429, timeouts), action_denied
5. Plugin events: lifecycle, slash commands, self-dev pipeline, stop-loss review decisions
6. Token spend per cycle: input, output, cycle total, cumulative trajectory, and daily ledger comparison
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class CycleMetrics:
    cycle: int
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cumulative_tokens: int = 0
    tool_calls: list[str] = field(default_factory=list)
    plan_action: str | None = None
    plan_source: str | None = None
    failures: list[str] = field(default_factory=list)


@dataclass
class RunAnalysisResult:
    cycles_analyzed: int
    plan_updated_count: int
    plan_unchanged_agent_count: int
    plan_unchanged_harness_count: int
    agent_plan_autonomy_pct: float
    handoff_chars: int
    handoff_lines: int
    handoff_repeats: int
    handoff_overflow_exists: bool
    human_input_decisions: dict[str, int]
    failure_types: dict[str, int]
    plugin_events: dict[str, int]
    token_spend_by_cycle: list[dict[str, Any]]
    total_tokens_spent: int
    daily_token_cap: int


def analyze_run(
    workspace: Path | str = "workspace",
    max_cycles: int = 30,
    log_file_override: Path | str | None = None,
) -> dict[str, Any]:
    ws = Path(workspace).resolve()
    state_dir = ws / "state"

    # Locate actions.jsonl
    if log_file_override:
        log_path = Path(log_file_override).resolve()
    elif (ws / "logs" / "actions.jsonl").exists():
        log_path = ws / "logs" / "actions.jsonl"
    elif (ws / "actions.jsonl").exists():
        log_path = ws / "actions.jsonl"
    else:
        log_path = ws / "logs" / "actions.jsonl"

    events: list[dict[str, Any]] = []
    if log_path.exists():
        for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line_str = line.strip()
            if line_str:
                try:
                    events.append(json.loads(line_str))
                except Exception:
                    continue

    # Filter events to target cycles (1..max_cycles)
    plan_updated = 0
    plan_unchanged_agent = 0
    plan_unchanged_harness = 0

    human_decisions: Counter[str] = Counter()
    failure_counts: Counter[str] = Counter()
    plugin_event_counts: Counter[str] = Counter()

    cycles_data: dict[int, CycleMetrics] = {}
    for c in range(1, max_cycles + 1):
        cycles_data[c] = CycleMetrics(cycle=c)

    max_observed_cycle = 0

    for ev in events:
        c_raw = ev.get("cycle")
        c = int(c_raw) if c_raw is not None else 0
        if c > max_observed_cycle:
            max_observed_cycle = c

        if c > max_cycles:
            continue

        evt_name = str(ev.get("event", ""))

        # 1. Plan activity
        if evt_name == "plan_updated":
            plan_updated += 1
            if c in cycles_data:
                cycles_data[c].plan_action = "updated"
                cycles_data[c].plan_source = "agent"
        elif evt_name == "plan_unchanged":
            source = str(ev.get("source", "harness_auto"))
            if source == "agent":
                plan_unchanged_agent += 1
            else:
                plan_unchanged_harness += 1
            if c in cycles_data:
                cycles_data[c].plan_action = "unchanged"
                cycles_data[c].plan_source = source

        # 2. Human input decisions
        elif evt_name == "human_input_decision":
            dec = str(ev.get("decision", "unknown")).lower()
            human_decisions[dec] += 1

        # 3. Failures
        elif evt_name == "llm_call_failed":
            err_type = str(ev.get("error_type", ev.get("error", "llm_failure")))
            failure_counts[f"llm:{err_type}"] += 1
            if c in cycles_data:
                cycles_data[c].failures.append(f"llm:{err_type}")
        elif evt_name in {"tool_failed", "tool_result"}:
            if not ev.get("ok", True) or ev.get("error"):
                t_name = str(ev.get("tool", ev.get("name", "unknown_tool")))
                failure_counts[f"tool:{t_name}"] += 1
                if c in cycles_data:
                    cycles_data[c].failures.append(f"tool:{t_name}")
        elif evt_name == "action_denied":
            act = str(ev.get("action", "unknown_action"))
            lvl = str(ev.get("level", "L?"))
            failure_counts[f"denied:{act}({lvl})"] += 1
            if c in cycles_data:
                cycles_data[c].failures.append(f"denied:{act}")
        elif evt_name == "duplicate_action_blocked":
            t_name = str(ev.get("tool", "unknown_tool"))
            failure_counts[f"duplicate_blocked:{t_name}"] += 1

        # 4. Plugin events
        if evt_name.startswith("plugin_"):
            plugin_event_counts[evt_name] += 1

        # 5. Token spend
        in_tok = int(ev.get("input_tokens") or 0)
        out_tok = int(ev.get("output_tokens") or 0)
        tot_tok = int(ev.get("total_tokens") or (in_tok + out_tok))

        # Check tool actions from cycle_completed
        if evt_name == "cycle_completed":
            actions = ev.get("actions", [])
            if isinstance(actions, list) and c in cycles_data:
                for act in actions:
                    if isinstance(act, dict) and "name" in act:
                        cycles_data[c].tool_calls.append(act["name"])

        if c in cycles_data and tot_tok > 0:
            cycles_data[c].input_tokens += in_tok
            cycles_data[c].output_tokens += out_tok
            cycles_data[c].total_tokens += tot_tok

    # Cumulative tokens calculation
    cum = 0
    active_cycle_limit = min(max_cycles, max(max_observed_cycle, 1))
    token_cycle_list: list[dict[str, Any]] = []

    for c in range(1, active_cycle_limit + 1):
        m = cycles_data[c]
        cum += m.total_tokens
        m.cumulative_tokens = cum
        token_cycle_list.append({
            "cycle": c,
            "input_tokens": m.input_tokens,
            "output_tokens": m.output_tokens,
            "total_tokens": m.total_tokens,
            "cumulative_tokens": m.cumulative_tokens,
            "tool_calls_count": len(m.tool_calls),
            "tool_calls": m.tool_calls,
            "plan_action": m.plan_action or "omitted",
            "plan_source": m.plan_source or "none",
            "failures": m.failures,
        })

    # Handoff metrics
    handoff_file = state_dir / "handoff.json"
    handoff_chars = 0
    handoff_lines = 0
    handoff_repeats = 0
    if handoff_file.exists():
        raw_text = handoff_file.read_text(encoding="utf-8", errors="replace")
        handoff_chars = len(raw_text)
        handoff_lines = len(raw_text.splitlines())
        handoff_repeats = raw_text.count("Session complete after")

    handoff_overflow_exists = (state_dir / "handoff_overflow.json").exists()

    # Daily cap
    daily_cap = 200000
    token_budget_file = state_dir / "daily_token_budget.json"
    if token_budget_file.exists():
        try:
            tb_data = json.loads(token_budget_file.read_text(encoding="utf-8"))
            if "cap" in tb_data:
                daily_cap = int(tb_data["cap"])
        except Exception:
            pass

    # Autonomy ratio
    total_reviews = plan_updated + plan_unchanged_agent + plan_unchanged_harness
    agent_autonomy_pct = (
        round(((plan_updated + plan_unchanged_agent) / total_reviews) * 100.0, 1)
        if total_reviews > 0 else 0.0
    )

    result = {
        "workspace": str(ws),
        "log_path": str(log_path),
        "cycles_analyzed": active_cycle_limit,
        "plan_activity": {
            "plan_updated": plan_updated,
            "plan_unchanged_agent": plan_unchanged_agent,
            "plan_unchanged_harness_auto": plan_unchanged_harness,
            "total_reviews": total_reviews,
            "agent_autonomy_pct": agent_autonomy_pct,
        },
        "handoff": {
            "chars": handoff_chars,
            "lines": handoff_lines,
            "limit": 6000,
            "pct_of_limit": round((handoff_chars / 6000.0) * 100.0, 1),
            "repeats": handoff_repeats,
            "overflow_exists": handoff_overflow_exists,
        },
        "human_input_decisions": dict(human_decisions),
        "failure_types": dict(failure_counts),
        "plugin_events": dict(plugin_event_counts),
        "tokens": {
            "by_cycle": token_cycle_list,
            "total_spent": cum,
            "daily_cap": daily_cap,
            "pct_of_daily_cap": round((cum / float(daily_cap)) * 100.0, 2) if daily_cap > 0 else 0.0,
        },
    }
    return result


def print_report(res: dict[str, Any]) -> None:
    print("=" * 80)
    print("SELF 30-Cycle Run Log Analysis Report")
    print(f"Workspace: {res['workspace']}")
    print(f"Log Path : {res['log_path']}")
    print(f"Cycles Analyzed: {res['cycles_analyzed']}")
    print("=" * 80)

    # 1. Plan Activity
    pa = res["plan_activity"]
    print("\n1. Plan Activity Accounting")
    print(f"   - plan_updated (agent)          : {pa['plan_updated']}")
    print(f"   - plan_unchanged (agent)        : {pa['plan_unchanged_agent']}")
    print(f"   - plan_unchanged (harness_auto) : {pa['plan_unchanged_harness_auto']}")
    print(f"   - Agent Autonomy Ratio          : {pa['agent_autonomy_pct']}% of cycles")

    # 2. Handoff Growth
    ho = res["handoff"]
    print("\n2. Handoff Growth & Size Tracking")
    print(f"   - Current Length : {ho['chars']} chars ({ho['pct_of_limit']}% of 6,000 threshold, {ho['lines']} lines)")
    print(f"   - Repeats        : {ho['repeats']} 'Session complete after'")
    print(f"   - Overflow File  : {'Present (Archived)' if ho['overflow_exists'] else 'None (Under Cap)'}")

    # 3. Human Input Decisions
    hd = res["human_input_decisions"]
    print("\n3. Human Input Decisions")
    if hd:
        for dec, count in sorted(hd.items()):
            print(f"   - {dec:<12} : {count}")
    else:
        print("   - (No human_input_decision events recorded)")

    # 4. Failure Types
    ft = res["failure_types"]
    print("\n4. Failure Types & Denials")
    if ft:
        for ftype, count in sorted(ft.items(), key=lambda x: -x[1]):
            print(f"   - {ftype:<28} : {count}")
    else:
        print("   - 0 failures recorded across run.")

    # 5. Plugin Events
    pe = res["plugin_events"]
    print("\n5. Plugin Subsystem Events")
    if pe:
        for pname, count in sorted(pe.items()):
            print(f"   - {pname:<30} : {count}")
    else:
        print("   - (No plugin events recorded)")

    # 6. Token Spend Per Cycle
    tok = res["tokens"]
    print("\n6. Token Spend Per Cycle (Cycles 1..{})".format(res["cycles_analyzed"]))
    print("   " + "-" * 72)
    print(f"   {'Cycle':<7} | {'Input':<8} | {'Output':<8} | {'Total':<8} | {'Cumulative':<10} | {'Tools':<5} | {'Plan':<10}")
    print("   " + "-" * 72)
    for c_data in tok["by_cycle"]:
        print(f"   {c_data['cycle']:<7} | {c_data['input_tokens']:<8} | {c_data['output_tokens']:<8} | {c_data['total_tokens']:<8} | {c_data['cumulative_tokens']:<10} | {c_data['tool_calls_count']:<5} | {c_data['plan_action']:<10}")
    print("   " + "-" * 72)
    print(f"   Total Run Spend: {tok['total_spent']} tokens ({tok['pct_of_daily_cap']}% of daily cap {tok['daily_cap']})")
    print("=" * 80)


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze a 30-cycle autonomous run log.")
    parser.add_argument("--workspace", default="workspace", help="Path to workspace directory")
    parser.add_argument("--max-cycles", type=int, default=30, help="Maximum cycles to analyze (default: 30)")
    parser.add_argument("--log-file", help="Explicit path to actions.jsonl")
    parser.add_argument("--json", action="store_true", help="Output analysis result as JSON")

    args = parser.parse_args()

    try:
        res = analyze_run(args.workspace, max_cycles=args.max_cycles, log_file_override=args.log_file)
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            print_report(res)
        return 0
    except Exception as exc:
        print(f"Error analyzing run: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
