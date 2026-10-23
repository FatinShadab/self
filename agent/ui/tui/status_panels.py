"""Formatters for TUI side panels: Identity, Activity, Session, Usage, Container, and Plan."""
from __future__ import annotations

import time
from typing import Any

from agent.ui.formatting.goals_panel import format_goals_panel
from agent.ui.formatting.rich_markup import escape_rich_markup


def build_identity_panel(coordinator: Any) -> str:
    """Format the Identity panel text."""
    identity = coordinator.identity.load()
    return (
        "[b]Identity[/b]\n"
        f"Agent: {escape_rich_markup(identity.get('name') or 'unnamed')}\n"
        f"Human: {escape_rich_markup(identity.get('human_name') or 'not yet known')}"
    )


def build_activity_panel(telemetry: dict[str, Any]) -> str:
    """Format the Activity presence panel text."""
    return (
        "[b]Activity[/b]\n"
        f"Presence: {escape_rich_markup(telemetry['state'])}\n"
        f"AI: {escape_rich_markup(telemetry['current_ai'])}"
    )


def build_session_panel(coordinator: Any, active_provider: str, active_model: str) -> str:
    """Format the Session panel text."""
    uptime = int(time.monotonic() - coordinator.status.started_monotonic)
    since_human = int(time.monotonic() - coordinator.status.last_human_input)
    return (
        "[b]Session[/b]\n"
        f"ID: {escape_rich_markup(coordinator.status.session_id[:12] or 'starting')}\n"
        f"Iteration: {escape_rich_markup(coordinator.status.iteration)}\n"
        f"Model: {escape_rich_markup(active_provider)}/{escape_rich_markup(active_model)}\n"
        f"Tools: {len(coordinator._tool_list())}\n"
        f"Uptime: {uptime}s\n"
        f"Since human input: {since_human}s"
    )


def build_usage_panel(coordinator: Any, telemetry: dict[str, Any], calls: str, model_calls: str) -> str:
    """Format the Usage token/call budget panel text."""
    run_tokens = telemetry["run_tokens_used"] or coordinator.status.tokens_used
    run_budget = telemetry["run_budget"] or coordinator.daily_ledger.cap
    budget_label = "daily-only" if coordinator.token_budget is None else str(run_budget)
    daily_remaining = (
        max(0, telemetry["daily_cap"] - telemetry["daily_used"] - telemetry["daily_reserved"])
        if telemetry["daily_cap"]
        else "unknown"
    )
    usage = (
        "[b]Usage[/b]\n"
        f"Tokens: {run_tokens} ({budget_label})\n"
        f"Calls: {telemetry['total_calls']} total | {telemetry['completed_calls']} completed | {telemetry['failed_calls']} failed\n"
        f"Daily tokens: {telemetry['daily_used']}/{telemetry['daily_cap'] or '?'} (remaining {daily_remaining})\n"
        f"AI call counts this session:\n{calls}\n"
        f"Per-model calls recorded:\n{model_calls}"
    )
    if telemetry.get("daily_blocked"):
        usage += "\n\nACTION NEEDED: daily limit reached; see HUMAN_REQUEST.md"
    return usage


def build_container_panel(container_metrics: Any) -> str:
    """Format the Container resource metrics panel text."""
    metrics = container_metrics.snapshot()
    return (
        "[b]Container[/b]\n"
        f"CPU: {escape_rich_markup(metrics['cpu'])}\n"
        f"RAM: {escape_rich_markup(metrics['ram'])}\n"
        f"Network: {escape_rich_markup(metrics['network'])}\n"
        f"Disk read: {escape_rich_markup(metrics['disk_read'])}"
    )


def refresh_all_status_panels(app: Any, coordinator: Any) -> None:
    """Refresh all TUI status panels from live coordinator and container state."""
    try:
        from textual.widgets import Static
    except ImportError:
        return

    telemetry = coordinator.runtime_snapshot()
    active_client = coordinator._llm
    active_provider = getattr(active_client, "provider", coordinator.status.active_provider)
    active_model = getattr(active_client, "model", coordinator.status.active_model)
    ai_counts = telemetry["calls_by_ai"]
    calls = (
        "\n".join(
            f"{escape_rich_markup(name)}: {escape_rich_markup(count)}"
            for name, count in sorted(ai_counts.items())
        )
        or "No AI calls yet"
    )
    registered_models = coordinator.models_snapshot().get("registry", {}).get("models", [])
    model_calls = (
        "\n".join(
            f"{escape_rich_markup(entry.get('name', 'unknown'))}: "
            f"{escape_rich_markup((entry.get('measured_stats') or {}).get('calls', 0))}"
            for entry in registered_models
        )
        or "No model data yet"
    )
    try:
        plan_file = coordinator.workspace / "state" / "plan.json"
        if plan_file.exists():
            mtime = plan_file.stat().st_mtime
            if mtime != app._last_plan_mtime:
                app._last_plan_mtime = mtime
                coordinator.plan_store.load()
                with coordinator.lock:
                    coordinator.plan = list(coordinator.plan_store.items)
    except OSError:
        pass

    goals_list = coordinator.plan_store.items or coordinator.plan
    current_activity = " ".join(str(telemetry.get("current_activity", "")).split())[:220]
    current_cycle = coordinator.status.iteration or 1
    plan_panel = format_goals_panel(goals_list, current_activity=current_activity, current_cycle=current_cycle)

    identity_panel = build_identity_panel(coordinator)
    activity_panel = build_activity_panel(telemetry)
    session_panel = build_session_panel(coordinator, active_provider, active_model)
    usage_panel = build_usage_panel(coordinator, telemetry, calls, model_calls)
    container_panel = build_container_panel(app._container_metrics)

    app.query_one("#identity", Static).update(identity_panel)
    app.query_one("#activity", Static).update(activity_panel)
    app.query_one("#plan", Static).update(plan_panel)
    app.query_one("#session", Static).update(session_panel)
    app.query_one("#usage", Static).update(usage_panel)
    app.query_one("#container", Static).update(container_panel)


__all__ = [
    "build_identity_panel",
    "build_activity_panel",
    "build_session_panel",
    "build_usage_panel",
    "build_container_panel",
    "refresh_all_status_panels",
]
