"""Stop file, pause condition, and daily token budget reset control."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from agent.infra.event_log import EventLogger
from agent.infra.hardening import DailyTokenLedger


def check_is_stopped(
    watcher: Any,
    broker: Any,
    stop_file: Path,
    logger: EventLogger,
) -> bool:
    """Check whether any graceful stop condition is triggered."""
    if watcher is not None and watcher.is_stopped():
        logger.narrate("Stop requested via watcher; halting cleanly.")
        logger.log("run_stopped", reason="stop_watcher")
        return True
    if broker is not None and getattr(broker, "in_panic", False):
        logger.narrate("Permission broker panic detected; halting cleanly.")
        logger.log("run_stopped", reason="broker_panic")
        return True
    if stop_file.exists():
        logger.narrate("STOP file detected; halting cleanly.")
        logger.log("run_stopped", reason="stop_file")
        return True
    return False


def wait_while_paused(
    pause_provider: Callable[[], bool] | None,
    is_stopped_fn: Callable[[], bool],
    logger: EventLogger,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> bool:
    """Pause only at safe boundaries; STOP condition still takes priority."""
    announced = False
    while pause_provider is not None and pause_provider():
        if is_stopped_fn():
            return False
        if not announced:
            logger.narrate("Paused by the human; waiting for /resume.")
            announced = True
        sleep_fn(0.2)
    if announced:
        logger.narrate("Resumed by the human.")
    return True


def request_daily_budget_action(workspace: Path, logger: EventLogger) -> None:
    """Pause safely and write HUMAN_REQUEST.md asking for a budget decision."""
    request = workspace / "HUMAN_REQUEST.md"
    if not request.exists():
        request.write_text(
            "\n".join(
                [
                    "# SELF needs a daily token-budget decision",
                    "",
                    "SELF reached the local daily token limit and paused before another AI call.",
                    "",
                    "Choose one host-side action:",
                    "1. Increase `SELF_MAX_TOKENS_PER_DAY` in `.env`, then recreate the container.",
                    "2. If the provider itself is rate-limited or unavailable, add another value to `OLLAMA_API_KEYS` or add a backup provider key such as `ANTHROPIC_API_KEYS` to `.env` and configure that provider.",
                    "",
                    "Never paste an API key into the chat or this file. Edit the host-side `.env` yourself, then remove this file; SELF will resume automatically. Recreate the container only if the changed environment variable is not visible to the running process.",
                    "A backup API key does not bypass SELF's own daily ledger; it is for provider-side failures or quota limits.",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        logger.log("daily_budget_human_request_created", path=str(request))


def pause_until_daily_reset(
    daily_ledger: DailyTokenLedger | None,
    session_id: str,
    workspace: Path,
    human_request: Path,
    is_stopped_fn: Callable[[], bool],
    logger: EventLogger,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> None:
    """Pause execution until the daily ledger resets to a new day or is manually increased."""
    if daily_ledger is None:
        return
    request_daily_budget_action(workspace, logger)
    logger.narrate("I reached today's daily token limit. Pausing until daily reset or limit increase.")
    logger.log("daily_token_limit_paused", session_id=session_id)
    initial_data = daily_ledger._read()
    initial_date = initial_data.get("date")
    initial_available = daily_ledger.available_tokens()

    while not is_stopped_fn():
        current_data = daily_ledger._read()
        current_date = current_data.get("date")
        current_available = daily_ledger.available_tokens()
        if (current_date != initial_date or current_available > initial_available) and current_available > 0:
            logger.narrate("Daily token limit reset or increased. Resuming.")
            logger.log("daily_token_limit_resumed", session_id=session_id)
            if human_request.exists():
                try:
                    text = human_request.read_text(encoding="utf-8", errors="replace")
                    if "daily token-budget decision" in text.lower():
                        human_request.unlink(missing_ok=True)
                except OSError:
                    pass
            return
        sleep_fn(1.0)
