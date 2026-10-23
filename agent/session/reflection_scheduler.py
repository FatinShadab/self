"""Reflection scheduling, trigger evaluation, and asynchronous reflection handling."""
from __future__ import annotations

from typing import Any, Callable


def reflection_triggers(actions: list[dict[str, Any]]) -> list[str]:
    """Inspect cycle actions for triggers that warrant an asynchronous reflection."""
    triggers: list[str] = []
    for action in actions:
        name = str(action.get("name", ""))
        ok = bool(action.get("ok", False))
        if not ok:
            triggers.append(f"tool failed: {name or 'unknown'}")
        elif name == "update_environment_map":
            triggers.append("verified environment map updated")
        elif name == "create_tool":
            triggers.append("tested tool created")
    return triggers


def schedule_reflection(
    reflections: Any,
    session_id: str,
    record: dict[str, Any],
    context_provider: Callable[[], str],
    on_result: Callable[[dict[str, Any]], None],
    stop_check: Callable[[], bool],
) -> None:
    """Submit a reflection candidate to the reflection manager if not stopped."""
    if stop_check():
        return
    raw_actions = record.get("actions")
    actions = [item for item in raw_actions if isinstance(item, dict)] if isinstance(raw_actions, list) else []
    triggers = reflection_triggers(actions)
    reflections.submit(
        session_id=session_id,
        cycle=int(record.get("cycle", 0) or 0),
        report=str(record.get("report", "")),
        actions=actions,
        triggers=triggers,
        context_provider=context_provider,
        on_result=on_result,
    )


def handle_reflection_ready(
    reflection: dict[str, Any],
    on_chat: Callable[[str, str], None] | None,
    logger: Any,
    stop_check: Callable[[], bool],
) -> None:
    """Deliver a completed background reflection to the chat stream or logger."""
    if stop_check():
        return
    message = str(reflection.get("message", "")).strip()
    if on_chat and message:
        on_chat(message, "reflection")
    elif message:
        logger.narrate("Reflection: " + message)


def accept_reflection_reply(
    reflections: Any,
    text: str,
    receive_input_fn: Callable[[str], None],
) -> dict[str, str] | None:
    """Persist a reply and inject it into the next safe autonomous turn."""
    reply = reflections.record_human_reply(text)
    if reply is None:
        return None
    receive_input_fn(
        f"Reply to SELF's reflection question ({reply['question']}): {reply['text']}"
    )
    return reply


__all__ = [
    "reflection_triggers",
    "schedule_reflection",
    "handle_reflection_ready",
    "accept_reflection_reply",
]
