"""Paginated conversation history formatter for the /conversation view."""
from __future__ import annotations

from typing import Any

from agent.ui.formatting.rich_markup import escape_rich_markup


def format_conversation_history_view(
    messages: list[dict[str, Any]],
    page: int = 0,
    page_size: int = 20,
    entity_name: str = "SELF",
) -> str:
    """Format a paginated view of conversation history for the /conversation screen."""
    if not messages:
        return (
            "[b]Conversation History[/b]\n"
            "No recorded conversation messages yet.\n\n"
            "Type [bold]/back[/bold] to return to the main view."
        )

    total = len(messages)
    max_pages = max(1, (total + page_size - 1) // page_size)
    clamped_page = max(0, min(page, max_pages - 1))

    end_idx = max(0, total - clamped_page * page_size)
    start_idx = max(0, end_idx - page_size)
    page_messages = messages[start_idx:end_idx]

    lines = [
        "[b]Conversation History[/b]",
        f"Showing messages {start_idx + 1}–{end_idx} of {total}  (Page {clamped_page + 1} of {max_pages})",
        "Type [bold]/previous[/bold] for older messages, [bold]/back[/bold] to return, [bold]/conversation[/bold] for latest.",
        "",
    ]

    if clamped_page > 0 and start_idx == 0:
        lines.append("[dim]── Oldest recorded messages (beginning of history) ──[/dim]")
        lines.append("")

    for item in page_messages:
        role = str(item.get("role", "agent")).strip().lower()
        kind = str(item.get("kind", "chat")).strip().lower()
        text = escape_rich_markup(item.get("message", ""))
        ts = str(item.get("timestamp", "")).strip()
        ts_label = f" [dim]({ts[:19].replace('T', ' ')})[/dim]" if ts else ""

        if role == "human":
            badge = "[bold white on dark_orange] YOU [/bold white on dark_orange]"
            header = f"{badge} [bold #ffbd7a]Human[/bold #ffbd7a]{ts_label}"
        else:
            badge = f"[bold white on dark_blue] {escape_rich_markup(entity_name)} [/bold white on dark_blue]"
            header = f"{badge} [bold #8ed8ff]{escape_rich_markup(kind.title())}[/bold #8ed8ff]{ts_label}"

        lines.append(header)
        lines.append(text)
        lines.append("[dim]─" * 48 + "[/dim]")
        lines.append("")

    if clamped_page < max_pages - 1:
        lines.append("[dim]Type [bold]/previous[/bold] to view older messages.[/dim]")

    return "\n".join(lines)


__all__ = [
    "format_conversation_history_view",
]
