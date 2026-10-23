"""Management of about_human.md and human preferred name persistence."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

from agent.identity.store.constants import NAME_MAX_CHARS, now
from agent.identity.store.schema import safe_text
from agent.infra.event_log import EventLogger


def save_human_name(
    identity: dict[str, Any],
    human_path: Path,
    log_change_fn: Callable[[str, str, str], None],
    logger: EventLogger,
    redactor: Any,
    name: str,
    session_id: str = "",
) -> tuple[dict[str, Any], str]:
    """Validate and persist the human's explicitly supplied preferred name."""
    cleaned = safe_text(name, redactor, NAME_MAX_CHARS)
    if not cleaned or len(cleaned) > NAME_MAX_CHARS:
        raise ValueError(f"Your name must contain 1-{NAME_MAX_CHARS} visible characters.")
    previous = identity.get("human_name")
    identity["human_name"] = cleaned

    human_path.parent.mkdir(parents=True, exist_ok=True)
    with human_path.open("a", encoding="utf-8") as f:
        f.write(f"- {now()}: Human's preferred name: {cleaned}\n")

    log_change_fn(
        f"Saved the human's preferred name as {cleaned}.",
        "The human supplied a preferred name for conversation.",
        session_id,
    )
    logger.log(
        "human_name_saved",
        previous=previous or "unknown",
        session_id=safe_text(session_id, redactor, 120),
    )
    return identity, cleaned


def append_human_answer(
    human_path: Path,
    init_human_file_fn: Callable[[], None],
    logger: EventLogger,
    redactor: Any,
    text: str,
    session_id: str = "",
) -> bool:
    """Persist a voluntarily supplied first-meeting answer with no inference."""
    answer = safe_text(text, redactor, 3_000)
    if not answer:
        return False
    init_human_file_fn()
    human_path.parent.mkdir(parents=True, exist_ok=True)
    with human_path.open("a", encoding="utf-8") as f:
        f.write(f"- {now()}: {answer}\n")
    logger.log(
        "about_human_recorded",
        chars=len(answer),
        session_id=safe_text(session_id, redactor, 120),
    )
    return True


def read_about_human_text(human_path: Path, redactor: Any, limit: int = 6_000) -> str:
    """Return the identity's human-facing context from about_human.md."""
    try:
        content = human_path.read_text(encoding="utf-8", errors="replace")[-max(1, limit):]
        return redactor.text(content) if hasattr(redactor, "text") else content
    except OSError:
        return "No volunteered information is stored about the human yet."


def delete_about_human_line(
    human_path: Path,
    log_change_fn: Callable[[str, str, str], None],
    logger: EventLogger,
    redactor: Any,
    line_number: int,
    session_id: str = "",
) -> str:
    """Remove one line of human context while preserving the audit trail."""
    if line_number < 1:
        raise ValueError("Line number must be positive.")
    try:
        lines = human_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        raise FileNotFoundError("There is no about_human.md to edit.") from exc
    if line_number > len(lines):
        raise ValueError(f"Line {line_number} does not exist.")
    removed = lines.pop(line_number - 1)
    temporary = human_path.with_suffix(".tmp")
    temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(temporary, human_path)
    log_change_fn(
        f"Removed line {line_number} from about_human.md.",
        "The human requested deletion of stored information about them.",
        session_id,
    )
    logger.log(
        "about_human_line_deleted",
        line_number=line_number,
        removed_chars=len(safe_text(removed, redactor)),
    )
    return f"Removed line {line_number} from about_human.md."
