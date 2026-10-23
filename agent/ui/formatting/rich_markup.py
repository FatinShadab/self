"""Escaping untrusted text for safe interpolation into Rich markup."""
from __future__ import annotations

from typing import Any


def escape_rich_markup(value: Any) -> str:
    """Return untrusted text that is safe to interpolate into Rich markup.

    The TUI uses a few Rich tags for its own headings. Plan entries, identity
    fields, provider labels, and telemetry, however, can originate with an LLM
    or command output. Escape every literal ``[`` (rather than just known tag
    shapes) so arbitrary bracketed text cannot become Rich markup and make the
    entire Textual screen fail to reflow.
    """
    return str(value).replace("\\", "\\\\").replace("[", "\\[")


__all__ = [
    "escape_rich_markup",
]
