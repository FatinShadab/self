"""Safety filtering and validation of reflection responses."""
from __future__ import annotations

from typing import Any
from agent.infra.event_log import EventLogger

UNSUPPORTED_INNER_STATE_MARKERS = (
    "i feel", "i want", "i need", "i desire", "i experience",
    "my feelings", "my needs", "my desires", "sentient", "sentience", "consciousness",
    "i am conscious", "i am alive",
)


def validate_reflection_response(
    value: Any,
    cycle: int,
    logger: EventLogger,
) -> tuple[str, str] | None:
    """Validate structure, extract message/question, and reject unsafe claims.

    Returns (message, question) if valid and approved to post, else None.
    """
    if value is None:
        logger.log("reflection_skipped", cycle=cycle, reason="malformed_response")
        return None
    if not isinstance(value, dict) or not isinstance(value.get("post"), bool) or not value["post"]:
        logger.log("reflection_declined", cycle=cycle)
        return None
    if not isinstance(value.get("message"), str) or (value.get("question") is not None and not isinstance(value.get("question"), str)):
        logger.log("reflection_skipped", cycle=cycle, reason="invalid_response_shape")
        return None

    message = logger.redactor.text(value["message"].strip())[:700]
    raw_question = value.get("question")
    question = logger.redactor.text(raw_question.strip())[:300] if raw_question else ""
    if not message:
        logger.log("reflection_skipped", cycle=cycle, reason="empty_message")
        return None

    combined_text = f"{message}\n{question}".casefold()
    unsafe_claim = any(marker in combined_text for marker in UNSUPPORTED_INNER_STATE_MARKERS)
    if unsafe_claim:
        logger.log("reflection_skipped", cycle=cycle, reason="unsupported_inner_state_claim")
        return None

    return message, question
