"""Boot sequence, environment spot checks, orientation diffs, and greeting composition."""
from __future__ import annotations

import os
import platform
import shutil
from pathlib import Path
from typing import Any

from agent.session.handoff_builder import pending_human_inputs
from agent.session.plan_recovery import normalized_plan
from agent.session.session import default_plan
from agent.session.version_check import verify_startup_code_version


def now_utc() -> str:
    """Return the current UTC timestamp."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def orientation_changes(body: Any) -> list[str]:
    """Query the body for sensor/environment changes since last session."""
    sense_data = body.sense()
    changes = sense_data.get("orientation_changes")
    if isinstance(changes, list) and changes:
        return changes
    if hasattr(body, "orientation_changes"):
        return body.orientation_changes()
    return ["no tracked workspace, tool, credential-presence, or uptime change"]


def spot_check_map(learning_store: Any, workspace: Path) -> list[str]:
    """Spot-check durable environment map facts against live OS and disk values."""
    entries = learning_store._load_map().get("entries", {})
    results: list[str] = []
    checks: list[tuple[str, Any, str]] = [
        ("os", platform.system(), "command: platform.system()"),
        ("cpu", {"logical_cpus": os.cpu_count() or 0}, "command: os.cpu_count()"),
        ("disk", {"free_bytes": shutil.disk_usage(workspace).free}, f"command: shutil.disk_usage('{workspace}')"),
    ]
    for key, actual, source in checks:
        if key not in entries:
            continue
        expected = entries[key].get("value")
        if key == "disk" and isinstance(expected, dict):
            matches = int(expected.get("free_bytes", -1)) == actual["free_bytes"]
        elif key == "os" and isinstance(expected, dict):
            matches = expected.get("system") == actual
        else:
            matches = expected == actual
        results.append(f"{key} {'matches' if matches else 'changed'} ({source})")
    return results


def identity_observation(identity_store: Any) -> str:
    """Return only an evidence-backed observation for a later greeting."""
    traits = identity_store.load().get("traits", [])
    if not traits:
        return "I have no evidence-backed personality observation yet."
    latest = traits[-1]
    return f"One evidence-backed self-observation: {latest.get('trait')}; {latest.get('evidence')}"


def check_and_record_opencode_status(workspace: Path, learning_store: Any, logger: Any) -> None:
    """Check opencode availability and record in startup memory."""
    try:
        from agent.opencode.wrapper import OpencodeDelegator
        opencode = OpencodeDelegator(workspace=workspace)
        op_st = opencode.status()
        if not op_st.get("installed", True):
            st_msg = "Opencode is not installed."
        else:
            usable_str = "usable" if op_st.get("usable") else "unusable"
            st_msg = f"Opencode status at wake-up: {usable_str} ({op_st.get('reason', '')})."
            if not opencode._read_delegations():
                st_msg += " Opencode has never been used; I may choose to run one trivial delegation to learn how it behaves."
        learning_store.append_memory(
            what_was_tried="wake-up opencode status check",
            outcome=st_msg,
            lesson="Opencode status noted at wake-up",
            tags=["startup", "opencode"],
        )
        logger.narrate(st_msg)
    except Exception as exc:
        logger.narrate(f"Opencode wake-up check skipped: {exc}")


def compose_greeting(
    identity_store: Any,
    first_awakening_messages: list[str],
    prior_summary: str,
    prior_plan: str,
    changes: list[str],
    checks: list[str],
    crash_note: str,
    open_question: dict[str, Any] | None,
    pending: list[str],
) -> str:
    """Compose the multi-paragraph conversational greeting for the wake session."""
    identity = identity_store.load()
    name = identity.get("name") or "unnamed"
    if first_awakening_messages:
        greeting = (
            f"I am {name}. My stored voice is: {identity.get('voice', '')} "
            f"I am starting from persisted files rather than claiming a past. "
            f"My first plan is: {prior_plan}. {crash_note}"
        )
    else:
        greeting = (
            f"{name} is awake. {identity.get('voice', '')} "
            f"Last handoff: {prior_summary[:500]} My plan was: {prior_plan}. "
            f"Since then I notice: {'; '.join(changes)}. Spot checks: {'; '.join(checks) or 'no map facts to check'}. "
            f"{identity_observation(identity_store)} Today I intend to: {prior_plan}. {crash_note}"
        )
    if identity.get("name") is None:
        greeting += " I am still unnamed; use /rename <name> whenever you want to choose one."
    if identity.get("human_name"):
        greeting += f" I remember that you prefer to be called {identity.get('human_name')}."
    else:
        greeting += " I do not know your name yet. What should I call you? Say `My name is ...` or use `/name <name>` and I will save it for future conversations."
    if open_question:
        greeting += f" I still have an open reflection question: {open_question['question']}"
    if pending:
        greeting = "Pending human inputs to consider: " + " | ".join(pending) + "\n" + greeting
    return greeting


def run_boot_sequence(coordinator: Any) -> str:
    """Execute the full wake boot sequence and return the initial greeting."""
    verify_startup_code_version(coordinator.logger)
    coordinator.workspace.mkdir(parents=True, exist_ok=True)
    coordinator.learning.initialize()
    coordinator.plan_store.initialize(default_step=(coordinator.plan[0].get("step") if coordinator.plan else ""))
    if coordinator.plan_store.items:
        coordinator.plan = coordinator.plan_store.items
    daily = coordinator.daily_ledger._read()
    with coordinator.lock:
        coordinator.telemetry.daily_used = int(daily.get("used_tokens", 0) or 0)
        coordinator.telemetry.daily_reserved = int(daily.get("reserved_tokens", 0) or 0)
        coordinator.telemetry.daily_cap = coordinator.daily_ledger.cap
    if (coordinator.workspace / "STOP").exists():
        message = "I am paused because STOP was requested earlier. Remove workspace/STOP or use /restart, then I can wake again."
        coordinator.logger.narrate(message)
        return message
    if hasattr(coordinator, "stop_watcher") and coordinator.stop_watcher is not None:
        coordinator.stop_watcher.start()
    coordinator._session_info = coordinator.sessions.start()
    coordinator.status.session_id = coordinator._session_info["session_id"]
    coordinator.reflections.begin_session(coordinator.status.session_id)
    coordinator._session_start = now_utc()
    coordinator.identity.ensure_editable_layer()
    coordinator._first_awakening_messages = coordinator.identity.run_first_awakening(coordinator.status.session_id)
    for message in coordinator._first_awakening_messages:
        coordinator.logger.narrate(message)

    check_and_record_opencode_status(coordinator.workspace, coordinator.learning, coordinator.logger)

    old = coordinator._session_info.get("handoff", {})
    coordinator.handoff = old
    coordinator.plan = normalized_plan(list(old.get("plan") or default_plan()))
    coordinator._recover_budget_blocked_plan()
    coordinator.handoff["plan"] = coordinator.plan
    with coordinator.lock:
        coordinator.starting_plan = [dict(it) for it in coordinator.plan]
        coordinator.starting_session_id = coordinator.status.session_id
    changes = orientation_changes(coordinator.body)
    checks = spot_check_map(coordinator.learning, coordinator.workspace)
    crash = coordinator._session_info.get("crash")
    prior_summary = old.get("summary", "I have no prior handoff in my state files.")
    prior_plan = (coordinator.plan[0].get("step") if coordinator.plan else "inspect state")
    pending = pending_human_inputs(coordinator.workspace)
    if crash:
        crash_note = "I detected that the prior session ended unexpectedly and reconstructed from its checkpoint."
    elif coordinator._session_info.get("handoff_recovered"):
        crash_note = "The latest handoff was corrupt, so I recovered the last good checkpoint."
    else:
        crash_note = "The previous session ended cleanly according to available state."

    open_question = coordinator.reflections.open_question()
    greeting = compose_greeting(
        identity_store=coordinator.identity,
        first_awakening_messages=coordinator._first_awakening_messages,
        prior_summary=prior_summary,
        prior_plan=prior_plan,
        changes=changes,
        checks=checks,
        crash_note=crash_note,
        open_question=open_question,
        pending=pending,
    )
    coordinator.logger.narrate(greeting)
    return greeting


__all__ = [
    "now_utc",
    "orientation_changes",
    "spot_check_map",
    "identity_observation",
    "check_and_record_opencode_status",
    "compose_greeting",
    "run_boot_sequence",
]
