"""Chat message queuing, typing animation, history persistence, and bubble rendering."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from agent.session.boot import now_utc


def render_message(
    coordinator: Any,
    role: str,
    message: str,
    kind: str,
    *,
    typing: bool = False,
) -> Any:
    """Render a styled chat message bubble with badge and markdown body."""
    from rich.console import Group
    from rich.markdown import Markdown
    from rich.text import Text

    if role == "human":
        badge, badge_style, label_style = " YOU ", "bold white on dark_orange", "bold #ffbd7a"
    else:
        badge = f" {coordinator.identity.display_name()} "
        badge_style, label_style = "bold white on dark_blue", "bold #8ed8ff"
    header = Text()
    header.append(badge, style=badge_style)
    header.append("  " + ("typing..." if typing else kind.title()), style=label_style)
    return Group(header, Markdown(message))


def record_chat_message(
    coordinator: Any,
    all_chat_messages: list[dict[str, Any]],
    role: str,
    message: str,
    kind: str,
) -> None:
    """Append a chat record to in-memory list and write to conversation_history.jsonl."""
    record = {
        "timestamp": now_utc(),
        "role": role,
        "message": message,
        "kind": kind,
    }
    all_chat_messages.append(record)
    history_file = coordinator.workspace / "state" / "conversation_history.jsonl"
    try:
        history_file.parent.mkdir(parents=True, exist_ok=True)
        with history_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass


def load_conversation_history(workspace: Path) -> list[dict[str, Any]]:
    """Load persisted chat messages from conversation_history.jsonl or fallback threads."""
    messages: list[dict[str, Any]] = []
    history_file = workspace / "state" / "conversation_history.jsonl"
    if history_file.exists():
        try:
            for line in history_file.read_text(encoding="utf-8", errors="replace").splitlines():
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                    if isinstance(item, dict):
                        messages.append(item)
                except json.JSONDecodeError:
                    continue
        except OSError:
            pass
    if not messages:
        threads_file = workspace / "state" / "conversation_threads.jsonl"
        if threads_file.exists():
            try:
                for line in threads_file.read_text(encoding="utf-8", errors="replace").splitlines():
                    if not line.strip():
                        continue
                    try:
                        item = json.loads(line)
                        if isinstance(item, dict):
                            messages.append({
                                "timestamp": item.get("timestamp", ""),
                                "role": item.get("role", "human"),
                                "message": item.get("text", ""),
                                "kind": "chat",
                            })
                    except json.JSONDecodeError:
                        continue
            except OSError:
                pass
    return messages


def queue_chat(app: Any, coordinator: Any, role: str, message: str, kind: str) -> None:
    """Queue a chat message, dropping late autonomous messages if stopped."""
    if role == "agent" and (coordinator.stop_requested or (coordinator.workspace / "STOP").exists()):
        return
    app._pending_chat.append((role, message, kind))
    if not app._draining_chat:
        app._draining_chat = True
        app.run_worker(drain_chat(app, coordinator), exclusive=False)


async def drain_chat(app: Any, coordinator: Any) -> None:
    """Drain queued chat bubbles, animating agent typing when enabled."""
    try:
        from textual.containers import VerticalScroll
        from textual.widgets import Static
    except ImportError:
        return

    conversation = app.query_one("#conversation", VerticalScroll)
    try:
        while app._pending_chat:
            role, message, kind = app._pending_chat.pop(0)
            if role == "agent" and (coordinator.stop_requested or (coordinator.workspace / "STOP").exists()):
                continue
            record_chat_message(coordinator, app._all_chat_messages, role, message, kind)
            follow = conversation.scroll_y >= conversation.max_scroll_y - 1
            message_class = "human" if role == "human" else "reflection" if kind == "reflection" else "agent"
            bubble = Static(
                render_message(
                    coordinator,
                    role,
                    "" if role == "agent" and app.typing_enabled else message,
                    kind,
                    typing=role == "agent" and app.typing_enabled,
                ),
                classes=f"message {message_class}-message",
            )
            await conversation.mount(bubble)
            while len(conversation.children) > 20:
                await conversation.children[0].remove()
            if getattr(app, "_conversation_history_open", False) and getattr(app, "_conversation_page", 0) == 0:
                app._update_conversation_history_content()
            if follow:
                conversation.scroll_end(animate=False)
            if role == "agent" and app.typing_enabled:
                # Markdown parsing and widget layout are proportional to the
                # whole visible message. Keep the optional effect bounded.
                step = max(1, (len(message) + 23) // 24)
                for index in range(step, len(message) + step, step):
                    if coordinator.stop_requested or (coordinator.workspace / "STOP").exists():
                        break
                    visible = message[:index]
                    if len(visible) >= len(message):
                        visible = message
                    bubble.update(render_message(coordinator, role, visible, kind))
                    if follow:
                        conversation.scroll_end(animate=False)
                    if len(visible) < len(message):
                        await asyncio.sleep(app.typing_delay)
            if role == "agent" and kind in {"conversation", "cycle", "session"}:
                app.voice.speak(message)
    finally:
        app._draining_chat = False
        if app._pending_chat:
            app._draining_chat = True
            app.run_worker(drain_chat(app, coordinator), exclusive=False)


def populate_initial_chat(app: Any, coordinator: Any) -> None:
    """Populate recent conversation bubbles on app start."""
    try:
        from textual.containers import VerticalScroll
        from textual.widgets import Static
        from textual.css.query import NoMatches
    except ImportError:
        return

    try:
        conversation = app.query_one("#conversation", VerticalScroll)
    except NoMatches:
        return
    recent = app._all_chat_messages[-20:]
    for item in recent:
        role = str(item.get("role", "agent"))
        msg = str(item.get("message", ""))
        kind = str(item.get("kind", "chat"))
        message_class = "human" if role == "human" else "reflection" if kind == "reflection" else "agent"
        bubble = Static(
            render_message(coordinator, role, msg, kind, typing=False),
            classes=f"message {message_class}-message",
        )
        conversation.mount(bubble)
    if recent:
        app.call_after_refresh(lambda: conversation.scroll_end(animate=False))


__all__ = [
    "render_message",
    "record_chat_message",
    "load_conversation_history",
    "queue_chat",
    "drain_chat",
    "populate_initial_chat",
]
