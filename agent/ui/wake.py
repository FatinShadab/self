"""SELF's wake-up coordinator and optional Textual terminal interface facade."""
from __future__ import annotations

from typing import Any

from agent.learning.plan_statuses import COMPLETED_PLAN_STATUSES
from agent.session.coordinator import (
    RuntimeTelemetry,
    WakeCoordinator as _SessionWakeCoordinator,
    WakeStatus,
    _requests_text,
    format_starting_plan,
    normalized_plan,
    now_utc,
    run_headless,
    visible_plan_items,
)
from agent.ui.cardiac_monitor import (
    CARDIAC_MONITOR_BEAT_INTERVAL,
    CARDIAC_MONITOR_WIDTH,
    MONITOR_IDLE,
    MONITOR_STOPPED,
    MONITOR_THINKING,
    MONITOR_WORKING,
    CardiacMonitorIntensity,
    brain_art,
    cardiac_monitor_frame,
    cardiac_monitor_intensity,
)
from agent.ui.cli import main
from agent.ui.formatting.archive_view import build_archive_views
from agent.ui.formatting.conversation_view import format_conversation_history_view
from agent.ui.formatting.goals_panel import (
    PLAN_MIN_HEIGHT,
    PLAN_RESIZER_HEIGHT,
    WORKLOG_MIN_HEIGHT,
    clamped_plan_height,
    format_goals_panel,
)
from agent.ui.formatting.models_view import format_models_snapshot
from agent.ui.formatting.rich_markup import escape_rich_markup
from agent.ui.tui.app import run_tui

KNOWN_CREDENTIAL_ENV = (
    "OLLAMA_API_KEYS", "OLLAMA_API_KEY", "OLLAM_API_KEYS", "OLLAM_API_KEY",
    "ANTHROPIC_API_KEYS", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "GROQ_API_KEY",
    "OPENROUTER_API_KEY", "MISTRAL_API_KEY", "CEREBRAS_API_KEY", "HF_TOKEN",
    "CLOUDFLARE_API_TOKEN",
)

BUILTIN_SLASH_COMMANDS = (
    "/stop", "/pause", "/resume", "/kill", "/status", "/rename", "/name",
    "/plugin", "/plugins", "/proposal", "/proposals", "/help", "/quit", "/exit",
    "/goal", "/goals", "/reflect", "/decide", "/decisions", "/targets", "/plan",
    "/self", "/patches", "/about", "/journal", "/tools", "/requests", "/inputs",
    "/memory", "/budget", "/models", "/identity",
    "/archive", "/back", "/conversation", "/coverage", "/listen", "/next",
    "/previous", "/restart", "/typing", "/voice",
)


class WakeCoordinator(_SessionWakeCoordinator):
    """Textual UI compatible WakeCoordinator front-end."""
    pass


if __name__ == "__main__":
    raise SystemExit(main())

__all__ = [
    "WakeCoordinator",
    "WakeStatus",
    "RuntimeTelemetry",
    "run_headless",
    "run_tui",
    "main",
    "brain_art",
    "cardiac_monitor_intensity",
    "cardiac_monitor_frame",
    "CardiacMonitorIntensity",
    "CARDIAC_MONITOR_WIDTH",
    "CARDIAC_MONITOR_BEAT_INTERVAL",
    "MONITOR_STOPPED",
    "MONITOR_THINKING",
    "MONITOR_WORKING",
    "MONITOR_IDLE",
    "escape_rich_markup",
    "visible_plan_items",
    "normalized_plan",
    "clamped_plan_height",
    "format_goals_panel",
    "format_starting_plan",
    "build_archive_views",
    "format_conversation_history_view",
    "format_models_snapshot",
    "COMPLETED_PLAN_STATUSES",
    "PLAN_MIN_HEIGHT",
    "WORKLOG_MIN_HEIGHT",
    "PLAN_RESIZER_HEIGHT",
    "KNOWN_CREDENTIAL_ENV",
    "BUILTIN_SLASH_COMMANDS",
    "_requests_text",
    "now_utc",
]
