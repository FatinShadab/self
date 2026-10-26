"""Command handler implementations for the TUI input line."""
from __future__ import annotations

import json
from typing import Any

from agent.session.handoff_builder import requests_text as _requests_text
from agent.ui.formatting.models_view import format_models_snapshot


class ViewCommandHandler:
    """Handles full-screen overlay view commands (/coverage, /archive, /conversation, etc.)."""

    def matches(self, text: str) -> bool:
        return text in {"/coverage", "/archive", "/conversation", "/previous", "/next", "/back"}

    def handle(self, app: Any, coordinator: Any, text: str) -> bool:
        if text == "/coverage":
            app._write_command(text)
            app._open_coverage()
            return True
        if text == "/archive":
            app._write_command(text)
            app._open_archive()
            return True
        if text == "/conversation":
            app._write_command(text)
            app._open_conversation_history(page=0)
            return True
        if text == "/previous":
            app._write_command(text)
            if getattr(app, "_conversation_history_open", False):
                total = len(app._all_chat_messages)
                max_pages = max(1, (total + 19) // 20)
                if app._conversation_page + 1 < max_pages:
                    app._conversation_page += 1
                    app._update_conversation_history_content()
                    app._command_response(
                        f"Showing older messages (Page {app._conversation_page + 1} of {max_pages}).",
                        "conversation",
                    )
                else:
                    app._command_response("Already at the oldest recorded messages.", "conversation")
            else:
                app._open_conversation_history(page=1 if len(app._all_chat_messages) > 20 else 0)
            return True
        if text == "/next":
            app._write_command(text)
            if getattr(app, "_conversation_history_open", False):
                if app._conversation_page > 0:
                    app._conversation_page -= 1
                    app._update_conversation_history_content()
                    total = len(app._all_chat_messages)
                    max_pages = max(1, (total + 19) // 20)
                    app._command_response(
                        f"Showing newer messages (Page {app._conversation_page + 1} of {max_pages}).",
                        "conversation",
                    )
                else:
                    app._command_response("Already showing the newest messages.", "conversation")
            return True
        if text == "/back" and (
            getattr(app, "_coverage_open", False)
            or getattr(app, "_archive_open", False)
            or getattr(app, "_conversation_history_open", False)
        ):
            app._write_command(text)
            if getattr(app, "_coverage_open", False):
                app._back_from_coverage()
            if getattr(app, "_archive_open", False):
                app._back_from_archive()
            if getattr(app, "_conversation_history_open", False):
                app._back_from_conversation_history()
            return True
        return False


class VoiceCommandHandler:
    """Handles voice settings and microphone listening (/voice, /listen)."""

    def matches(self, text: str) -> bool:
        return text in {"/voice", "/voice on", "/voice off", "/listen"}

    def handle(self, app: Any, coordinator: Any, text: str) -> bool:
        if text == "/voice":
            app._write_command(text)
            app._voice_status()
            return True
        if text in {"/voice on", "/voice off"}:
            app._write_command(text)
            app._voice_status(app.voice.set_enabled(text.endswith(" on")))
            return True
        if text == "/listen":
            app._write_command(text)
            app._command_response("Listening for one microphone phrase...", "request")
            app.run_worker(app._listen_for_human, thread=True)
            return True
        return False


class TypingCommandHandler:
    """Handles typing effect toggle commands (/typing)."""

    def matches(self, text: str) -> bool:
        return text in {"/typing", "/typing on", "/typing off"}

    def handle(self, app: Any, coordinator: Any, text: str) -> bool:
        if text == "/typing":
            app._write_command(text)
            app._command_response(f"Typing effect {'enabled' if app.typing_enabled else 'disabled'}.")
            return True
        if text in {"/typing on", "/typing off"}:
            app._write_command(text)
            app.typing_enabled = text.endswith(" on")
            app._command_response(f"Typing effect {'enabled' if app.typing_enabled else 'disabled'}.")
            return True
        return False


class LifecycleCommandHandler:
    """Handles wake session lifecycle controls (/restart, /pause, /resume, /stop, /decline, /approve)."""

    def matches(self, text: str) -> bool:
        return (
            text in {"/restart", "/pause", "/resume", "/stop"}
            or text == "/decline"
            or text.startswith("/decline ")
            or text == "/approve"
            or text.startswith("/approve ")
        )

    def handle(self, app: Any, coordinator: Any, text: str) -> bool:
        if text == "/approve" or text.startswith("/approve "):
            app._write_command(text)
            target = text[9:].strip() if text.startswith("/approve ") else ""
            if hasattr(coordinator, "approve_human_request"):
                res = coordinator.approve_human_request(target_id=target)
                msg = res.get("message", "Approved request. Resuming.") if isinstance(res, dict) else "Approved request. Resuming."
                app._command_response(msg, "request")
            else:
                coordinator.resume()
                app._command_response("Resuming.", "request")
            app._start_agent()
            return True
        if text == "/decline" or text.startswith("/decline "):
            app._write_command(text)
            reason = text[9:].strip() if text.startswith("/decline ") else ""
            if hasattr(coordinator, "decline_human_request"):
                rec = coordinator.decline_human_request(reason=reason)
                summary = rec.get("summary", "capability") if rec else "pending request"
                app._command_response(f"Declined request ({summary}). Resuming without it.", "request")
            else:
                coordinator.resume()
                app._command_response("Resuming.", "request")
            app._start_agent()
            return True
        if text == "/restart":
            app._write_command(text)
            if app._agent_running:
                app._command_response("I am already running; use /stop first if you want a fresh session.")
                return True
            stop_path = coordinator.workspace / "STOP"
            try:
                if coordinator.broker is not None:
                    coordinator.broker.reset_panic()
                if stop_path.exists():
                    stop_path.unlink()
                request_path = coordinator.workspace / "HUMAN_REQUEST.md"
                if request_path.exists():
                    request_text = request_path.read_text(encoding="utf-8", errors="replace").lower()
                    if "daily token-budget decision" in request_text:
                        coordinator.clear_human_request()
                        app._command_response(
                            "I cleared the previous token-budget request; the new daily limit will be used for this run."
                        )
            except OSError as exc:
                app._command_response(f"I could not remove STOP: {type(exc).__name__}.", "error")
                return True
            if coordinator.stop_watcher is not None and not coordinator.stop_watcher.reset_stop():
                app._command_response("I could not clear the stop condition; check STOP and the permission broker.", "error")
                return True
            coordinator.stop_requested = False
            coordinator.resume()
            app._command_response("I removed the previous stop request and am waking now.", "request")
            app._start_agent()
            return True
        if text == "/pause":
            app._write_command(text)
            coordinator.pause()
            app._command_response("Paused. I will stop at the next safe boundary.")
            return True
        if text == "/resume":
            app._write_command(text)
            coordinator.resume()
            app._command_response("Resuming.")
            return True
        if text == "/stop":
            app._write_command(text)
            app._pending_chat.clear()
            coordinator.request_stop("ui_stop")
            app._command_response("Stop requested; finishing the current safe action.", "request")
            return True
        return False


class PlanGoalsCommandHandler:
    """Handles targets, plan inspection, and goal queueing (/targets, /plan, /goals, /goal)."""

    def matches(self, text: str) -> bool:
        return text in {"/targets", "/plan", "/goals"} or text.startswith("/goal ")

    def handle(self, app: Any, coordinator: Any, text: str) -> bool:
        if text in {"/targets", "/plan"}:
            app._write_command(text)
            rendered = coordinator.render_starting_plan()
            app._queue_chat("agent", rendered, "targets")
            app._command_response("Starting targets displayed in conversation.", "targets")
            return True
        if text == "/goals":
            app._write_command(text)
            coordinator.plan_store.load()
            current_goals = coordinator.plan_store.items or coordinator.plan
            app._command_response(json.dumps(current_goals, ensure_ascii=False, indent=2))
            return True
        if text.startswith("/goal "):
            app._write_command(text)
            coordinator.receive_human_input("Human input to consider: " + text[6:], kind="goal")
            app._command_response("Human input queued to consider for the next cycle.", "input")
            if not app._agent_running:
                app._command_response("The previous session had ended, so I am waking to work on it now.", "input")
                app._start_agent()
            return True
        return False


class IdentityCommandHandler:
    """Handles identity, model inspections, naming, and self inquiry (/models, /identity, /rename, /name, /self, /patches, /about me)."""

    def matches(self, text: str) -> bool:
        return (
            text in {"/models", "/identity", "/name", "/self", "/patches", "/about me"}
            or text.startswith("/rename ")
            or text.startswith("/name ")
            or text.startswith("/about me delete ")
        )

    def handle(self, app: Any, coordinator: Any, text: str) -> bool:
        if text == "/models":
            app._write_command(text)
            app._command_response(format_models_snapshot(coordinator.models_snapshot()))
            return True
        if text == "/identity":
            app._write_command(text)
            app._command_response(json.dumps(coordinator.identity.load(), ensure_ascii=False, indent=2))
            return True
        if text.startswith("/rename "):
            app._write_command(text)
            try:
                identity = coordinator.identity.set_name(text[8:].strip(), coordinator.status.session_id, named_by="human")
                app.title = f"SELF — {identity.get('name')}"
                context = identity.get("name_context") or {}
                context_label = context.get("meaning", "no verified meaning found")
                if context.get("kind") == "fictional_character":
                    context_label = (
                        f"{context.get('character', identity.get('name'))} from "
                        f"{context.get('franchise', 'a fictional story')} — {context.get('role', context_label)}"
                    )
                app._command_response(
                    f"Name saved as {identity.get('name')}. "
                    f"Context: {context_label}. "
                    f"Style cue: {context.get('style_cue', 'use observed behavior and the stored voice.')}"
                )
            except ValueError as exc:
                app._command_response(f"Could not rename: {exc}", "error")
            return True
        if text == "/name":
            app._write_command(text)
            current = coordinator.identity.human_name()
            app._command_response(
                f"I currently know your name as {current}."
                if current
                else "I do not know your name yet. Use `/name <your name>`."
            )
            return True
        if text.startswith("/name "):
            app._write_command(text)
            try:
                saved = coordinator.identity.set_human_name(text[6:].strip(), coordinator.status.session_id)
                app._command_response(f"Thank you, {saved}. I saved your name for future conversations.")
            except ValueError as exc:
                app._command_response(f"Could not save your name: {exc}", "error")
            return True
        if text == "/self":
            app._write_command(text)
            try:
                content = (coordinator.workspace / "state" / "self_inquiry.md").read_text(
                    encoding="utf-8", errors="replace"
                )
            except OSError:
                content = "No self inquiry exists yet; it is written during first awakening."
            app._command_response(content[-6_000:])
            return True
        if text == "/patches":
            app._write_command(text)
            patches = coordinator.identity.proposed_patches()
            message = (
                "\n".join(str(path) for path in patches[:20])
                if patches
                else "No proposed core patches are waiting for review."
            )
            app._command_response(message, "request")
            return True
        if text.startswith("/about me delete "):
            app._write_command(text)
            try:
                line_number = int(text.removeprefix("/about me delete ").strip())
                app._command_response(coordinator.identity.delete_human_line(line_number, coordinator.status.session_id))
            except (ValueError, FileNotFoundError) as exc:
                app._command_response(f"Could not delete stored line: {exc}", "error")
            return True
        if text == "/about me":
            app._write_command(text)
            content = coordinator.identity.about_human_text()
            numbered = "\n".join(f"{index}: {line}" for index, line in enumerate(content.splitlines(), start=1))
            app._command_response(numbered or "No volunteered information is stored about you.")
            return True
        return False


class StateInfoCommandHandler:
    """Handles journal, tools, plugins, proposals, requests, memory, budget, and decision queries."""

    def matches(self, text: str) -> bool:
        return (
            text in {"/help", "/journal", "/tools", "/requests", "/inputs", "/reports", "/report", "/budget", "/decisions", "/decisions "}
            or text.startswith("/plugins")
            or text.startswith("/proposals")
            or text.startswith("/memory ")
        )

    def handle(self, app: Any, coordinator: Any, text: str) -> bool:
        if text == "/help":
            app._write_command(text)
            help_text = (
                "Available commands:\n\n"
                "Lifecycle & Control:\n"
                "  /restart              Restart wake session, clearing stops and resetting panic\n"
                "  /pause                Pause autonomous cycles at next safe action boundary\n"
                "  /resume               Resume paused cycles and clear human request wait\n"
                "  /stop                 Immediately stop autonomous work (writes STOP file)\n"
                "  /approve [id]         Approve capability request or stalled task by ID and resume\n"
                "  /decline [id] [reason] Decline pending capability request and resume without it\n\n"
                "Goals & Planning:\n"
                "  /plan, /targets       Display starting goals and session plan targets\n"
                "  /goals                Display all active goals and priorities from plan store\n"
                "  /goal <text>          Queue a goal or suggestion for SELF to weigh in upcoming cycles\n\n"
                "State & Diagnostics:\n"
                "  /reports, /report     Inspect stalled task reports recorded in report_human.md\n"
                "  /requests, /inputs    Inspect pending human capability requests (HUMAN_REQUEST.md)\n"
                "  /tools                List all dynamically registered custom tools\n"
                "  /budget               View daily token usage, reserved budget, and remaining limit\n"
                "  /journal              Read recent entries from durable state journal\n"
                "  /decisions            View recent decisions on human inputs (accepted/modified/declined)\n"
                "  /memory <query>       Search persistent episodic and semantic memories\n\n"
                "Identity & Models:\n"
                "  /models               Inspect active model registry, provider routing, and decisions\n"
                "  /identity             Display the agent's identity, values, traits, and voice profile\n"
                "  /rename <name>        Rename the agent (persisted across sessions)\n"
                "  /name [your_name]     Check or set your name so SELF recognizes you\n"
                "  /self                 View self-inquiry document and philosophical self-questions\n"
                "  /patches              Review proposed core patches waiting for human review\n"
                "  /about me             Display volunteered notes the agent has stored about you\n"
                "  /about me delete <n>  Delete a specific stored line about you\n\n"
                "Views & Navigation:\n"
                "  /coverage             Open full-screen test coverage report\n"
                "  /archive              Browse archived plan and goal generations\n"
                "  /conversation         Browse full-screen conversation history\n"
                "  /previous, /next      Navigate pages in active full-screen overlay views\n"
                "  /back                 Close active overlay view and return to main dashboard\n\n"
                "Plugins & Settings:\n"
                "  /plugins [list|...]   Manage installed plugin bundles (list, enable, disable)\n"
                "  /proposals            View plugin proposals or submit extensions for consideration\n"
                "  /voice [on|off]       Toggle or inspect voice synthesis feedback\n"
                "  /listen               Listen for a single voice phrase via microphone\n"
                "  /typing [on|off]      Toggle chat typing animation effect\n"
                "  /help                 Display this command reference and general information\n\n"
                "General Information:\n"
                "  • Chat: Type naturally without a leading '/' to talk directly with SELF.\n"
                "    Conversation is always on, even when cycles are stopped, paused, or waiting.\n"
                "  • Reflection: When SELF asks a question during work, simply type your reply.\n"
                "  • Autonomy: SELF weighs human input as advice while pursuing its core goals;\n"
                "    hard safety controls (/stop, /pause) take effect immediately."
            )
            if hasattr(app, "_queue_chat"):
                app._queue_chat("agent", help_text, "help")
            app._command_response(help_text, "info")
            return True
        if text == "/journal":
            app._write_command(text)
            try:
                app._command_response((coordinator.workspace / "state" / "journal.md").read_text(encoding="utf-8")[-3_000:])
            except OSError:
                app._command_response("No journal entry exists yet.")
            return True
        if text == "/tools":
            app._write_command(text)
            app._command_response(", ".join(coordinator._tool_list()) or "No custom tools registered.")
            return True
        if text.startswith("/plugins"):
            app._write_command(text)
            app._command_response(coordinator.handle_plugins_command(text), "input")
            return True
        if text.startswith("/proposals"):
            app._write_command(text)
            app._command_response(coordinator.handle_proposals_command(text), "input")
            return True
        if text in {"/requests", "/inputs"}:
            app._write_command(text)
            app._command_response(_requests_text(coordinator.workspace), "input")
            return True
        if text in {"/reports", "/report"}:
            app._write_command(text)
            report_path = coordinator.workspace / "report_human.md"
            if report_path.exists():
                try:
                    content = report_path.read_text(encoding="utf-8")[-3_000:]
                    app._command_response(content, "request")
                except OSError:
                    app._command_response("Could not read report_human.md.", "error")
            else:
                app._command_response("No stalled task reports recorded in report_human.md.", "info")
            return True
        if text.startswith("/memory "):
            app._write_command(text)
            app._command_response(coordinator.learning.retrieve_memories(text[8:]))
            return True
        if text == "/budget":
            app._write_command(text)
            app._command_response(json.dumps(coordinator.daily_ledger._read()))
            return True
        if text in {"/decisions", "/decisions "}:
            app._write_command(text)
            app._command_response(coordinator.recent_decisions(), "input")
            return True
        return False


class PluginSlashCommandHandler:
    """Dispatches any unhandled slash command to active plugins or displays command help."""

    def matches(self, text: str) -> bool:
        return text.startswith("/")

    def handle(self, app: Any, coordinator: Any, text: str) -> bool:
        plugin_resp = coordinator.handle_slash_command(text)
        if plugin_resp is not None:
            app._write_command(text)
            app._command_response(plugin_resp, "input")
            return True
        app._write_command(text)
        app._command_response(
            f"Unknown command '{text}'. Type /help for available commands, or type naturally without '/' to chat.",
            "error",
        )
        return True


__all__ = [
    "ViewCommandHandler",
    "VoiceCommandHandler",
    "TypingCommandHandler",
    "LifecycleCommandHandler",
    "PlanGoalsCommandHandler",
    "IdentityCommandHandler",
    "StateInfoCommandHandler",
    "PluginSlashCommandHandler",
]
