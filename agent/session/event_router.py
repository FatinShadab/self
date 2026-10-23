"""Event routing, activity feed management, and cycle checkpointing."""
from __future__ import annotations

import time
from typing import Any


def handle_checkpoint_cycle(
    coordinator: Any,
    cycle: int,
    report: str,
    tokens: int,
) -> None:
    """Record cycle metrics, refresh active plan, and trigger periodic durable checkpoints."""
    coordinator.status.iteration, coordinator.status.tokens_used = cycle, tokens
    with coordinator.lock:
        coordinator.plan_store.load()
        if coordinator.plan_store.items:
            coordinator.plan = list(coordinator.plan_store.items)
    if cycle % 10 == 0 or time.monotonic() - coordinator._last_checkpoint >= 300:
        coordinator.sessions.checkpoint(
            coordinator.status.session_id,
            coordinator._make_handoff(report, "checkpoint"),
            cycle,
            tokens,
        )
        coordinator._last_checkpoint = time.monotonic()


def handle_session_event(
    coordinator: Any,
    record: dict[str, Any],
) -> None:
    """Process incoming logger events, route activities, and notify front-end callbacks."""
    coordinator._update_telemetry(record)
    event = str(record.get("event", ""))
    activity = ""
    if event == "command_started":
        activity = f"$ {record.get('command', '')}"
    elif event == "command_output":
        activity = "  " + str(record.get("output", "")).rstrip()
    elif event == "command_finished":
        status = "timeout" if record.get("timed_out") else f"exit {record.get('exit_code')}"
        activity = f"  [{status}]"
    elif event == "tool_call":
        activity = f"tool: {record.get('tool', '')}"
    elif event == "tool_result":
        activity = f"tool result: {record.get('tool', '')} · {'ok' if record.get('ok') else 'failed'}"
    elif event == "agent_step":
        activity = "step: " + str(record.get("message", ""))
    elif event == "narration":
        activity = str(record.get("message", ""))
    elif event in {"plan_updated", "plan_unchanged"}:
        with coordinator.lock:
            coordinator.plan_store.load()
            coordinator.plan = list(coordinator.plan_store.items)
        diff = str(record.get("diff", "")).strip()
        if diff:
            activity = f"goal: {diff}"
    elif event == "cycle_completed":
        with coordinator.lock:
            coordinator.plan_store.load()
            if coordinator.plan_store.items:
                coordinator.plan = list(coordinator.plan_store.items)
        summary = f"Cycle {record.get('cycle', '?')} summary\n{record.get('report', '')}".strip()
        coordinator._cycle_summaries.append(summary)
        if coordinator.on_chat and not coordinator.stop_requested and not (coordinator.workspace / "STOP").exists():
            coordinator.on_chat(summary, "cycle")
        coordinator._schedule_reflection(record)
    elif event == "session_summary":
        if coordinator.on_chat and not coordinator.stop_requested and not (coordinator.workspace / "STOP").exists():
            coordinator.on_chat(str(record.get("message", "")), "session")

    if activity:
        clean = coordinator.logger.redactor.text(activity).strip()
        if clean:
            with coordinator.lock:
                coordinator._activity.append(clean[:4_000])
                coordinator.telemetry.current_activity = clean[:500]
            if coordinator.on_activity:
                coordinator.on_activity(clean[:4_000])
            elif coordinator.on_narration:
                coordinator.on_narration(clean[:4_000], "activity")


__all__ = [
    "handle_checkpoint_cycle",
    "handle_session_event",
]
