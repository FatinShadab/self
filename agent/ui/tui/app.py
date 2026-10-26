"""Textual application implementation for the interactive wake session interface."""
from __future__ import annotations

import os
from typing import Any, Callable

from agent.body.container import ContainerMetrics
from agent.session.coordinator import run_headless
from agent.ui.cardiac_monitor import (
    ENTITY_FACE,
    brain_art,
    cardiac_monitor_frame,
    cardiac_monitor_intensity,
    entity_art,
    robot_art,
)
from agent.ui.formatting.goals_panel import clamped_plan_height
from agent.ui.tui.activity_log import drain_activity, queue_activity
from agent.ui.tui.chat_pipeline import (
    drain_chat,
    load_conversation_history,
    populate_initial_chat,
    queue_chat,
)
from agent.ui.tui.commands.registry import CommandRegistry
from agent.ui.tui.status_panels import refresh_all_status_panels
from agent.ui.tui.views.archive import (
    archive_error,
    back_from_archive,
    load_archive,
    open_archive,
    show_archive,
)
from agent.ui.tui.views.base import restore_main_scroll
from agent.ui.tui.views.conversation_history import (
    back_from_conversation_history,
    open_conversation_history,
    update_conversation_history_content,
)
from agent.ui.tui.views.coverage import (
    back_from_coverage,
    coverage_error,
    load_coverage,
    open_coverage,
    show_coverage,
)
from agent.ui.tui.widgets import PlanResizeHandle
from agent.ui.voice import VoiceController

try:
    from textual.app import App, ComposeResult
    from textual.containers import Horizontal, Vertical, VerticalScroll
    from textual.css.query import NoMatches
    from textual.widgets import Footer, Header, Input, Static
except ImportError:
    App = object  # type: ignore[assignment, misc]
    ComposeResult = Any  # type: ignore[assignment, misc]
    NoMatches = Exception  # type: ignore[assignment, misc]


class SelfApp(App[None]):
    """Main Textual application for interactive wake monitoring and steering."""

    CSS = """
    #body { height: 1fr; }
    #coverage { height: 1fr; border: solid $primary; padding: 0 1; scrollbar-gutter: stable; display: none; }
    #coverage-content { width: 100%; }
    #archive { height: 1fr; display: none; }
    #archive-plans-pane { width: 1fr; height: 100%; border: solid $primary; padding: 1; scrollbar-gutter: stable; }
    #archive-goals-pane { width: 1fr; height: 100%; border: solid $secondary; padding: 1; scrollbar-gutter: stable; }
    #archive-plans-content { width: 100%; }
    #archive-goals-content { width: 100%; }
    #conversation-history { height: 1fr; border: solid $primary; padding: 0 1; scrollbar-gutter: stable; display: none; }
    #conversation-history-content { width: 100%; }
    #conversation-pane { width: 2fr; border: solid $primary; }
    #work-pane { width: 1.5fr; border: solid $secondary; }
    #conversation-top { height: 6; }
    #entity-art { width: 9; height: 6; color: $accent; content-align: center middle; text-style: dim; }
    #entity-art.monitor-thinking { color: $accent; }
    #entity-art.monitor-working { color: $accent; text-style: bold; }
    #entity-monitor { width: 1fr; height: 6; color: $text-muted; content-align: left middle; text-style: dim; }
    #entity-monitor.monitor-thinking { color: $accent; }
    #entity-monitor.monitor-working { color: $accent; text-style: bold; }
    #conversation { height: 1fr; padding: 0 1; scrollbar-gutter: stable; }
    #plan-scroll { height: 10; min-height: 5; padding: 1; scrollbar-gutter: stable; }
    #plan { width: 100%; }
    #plan-resizer { height: 1; min-height: 1; max-height: 1; content-align: center middle; color: $text-muted; background: $panel; text-style: dim; }
    #plan-resizer:hover { color: $accent; background: $boost; text-style: bold; }
    #worklog { height: 1fr; min-height: 5; padding: 0 1; scrollbar-gutter: stable; }
    .activity-entry { width: 100%; margin: 0 0 1 0; padding: 0 1; }
    .message { width: 100%; margin: 0 0 1 0; padding: 1; }
    .agent-message { border-left: thick $primary; background: $panel; }
    .reflection-message { border-left: thick $success; background: $boost; }
    .human-message { border-left: thick $accent; background: $boost; }
    .typing-message { border-left: thick $secondary; background: $panel; color: $text-muted; }
    #side { width: 1fr; scrollbar-gutter: stable; }
    #identity, #activity, #session, #usage, #container { border: solid $secondary; padding: 1; }
    #identity, #activity, #session, #usage, #container { height: auto; min-height: 5; }
    #identity, #activity { min-height: 7; }
    #chat { dock: bottom; }
    """

    def __init__(self, coordinator: Any | None = None, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if coordinator is None:
            from agent.session.coordinator import WakeCoordinator
            coordinator = WakeCoordinator()
        self.coordinator = coordinator
        self.voice = VoiceController()
        self.typing_enabled = False
        self.typing_delay = max(0.001, min(float(os.getenv("SELF_TUI_TYPING_DELAY", "0.018")), 0.2))
        self._pending_chat: list[tuple[str, str, str]] = []
        self._pending_activity: list[str] = []
        self._all_chat_messages: list[dict[str, Any]] = []
        self._draining_chat = False
        self._draining_activity = False
        self._agent_running = False
        self._monitor_tick = 0
        self._container_metrics = ContainerMetrics()
        self._coverage_open = False
        self._coverage_generation = 0
        self._archive_open = False
        self._archive_generation = 0
        self._conversation_history_open = False
        self._conversation_page = 0
        self._last_plan_mtime = 0.0
        self._main_scroll_positions: tuple[float, float] | None = None
        self._main_chat_placeholder = "Talk to SELF; /targets /conversation /archive /coverage /restart; /stop pauses safely"
        self._command_registry = CommandRegistry()

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="body"):
            with Vertical(id="conversation-pane"):
                with Horizontal(id="conversation-top"):
                    yield Static(robot_art(), id="entity-art", markup=False)
                    yield Static(cardiac_monitor_frame(0), id="entity-monitor", markup=False)
                yield VerticalScroll(id="conversation")
            with Vertical(id="work-pane"):
                with VerticalScroll(id="plan-scroll"):
                    yield Static("Goals loading...", id="plan", markup=True)
                yield PlanResizeHandle(self._resize_plan)
                yield VerticalScroll(id="worklog")
            with VerticalScroll(id="side"):
                yield Static("Identity loading...", id="identity", markup=True)
                yield Static("Activity loading...", id="activity", markup=True)
                yield Static("Session loading...", id="session", markup=True)
                yield Static("Usage loading...", id="usage", markup=True)
                yield Static("Container loading...", id="container", markup=True)
        with VerticalScroll(id="coverage"):
            yield Static("", id="coverage-content", markup=True)
        with Horizontal(id="archive"):
            with VerticalScroll(id="archive-plans-pane"):
                yield Static("", id="archive-plans-content", markup=True)
            with VerticalScroll(id="archive-goals-pane"):
                yield Static("", id="archive-goals-content", markup=True)
        with VerticalScroll(id="conversation-history"):
            yield Static("", id="conversation-history-content", markup=True)
        yield Input(placeholder=self._main_chat_placeholder, id="chat")
        yield Footer()

    def on_mount(self) -> None:
        self.title = f"SELF — {self.coordinator.identity.display_name()}"
        self._load_conversation_history()
        self.coordinator.on_activity = lambda message: self.call_from_thread(self._queue_activity, message)
        self.coordinator.on_chat = lambda message, kind: self.call_from_thread(self._queue_chat, "agent", message, kind)
        self._refresh()
        self.set_interval(1.0, self._refresh)
        self.set_interval(0.25, self._animate_activity)
        self.call_after_refresh(self._populate_initial_chat)
        self.call_after_refresh(self._start_agent)

    def _start_agent(self) -> bool:
        """Start one wake session, including after a clean session end."""
        if self._agent_running:
            return False
        self._agent_running = True
        self.run_worker(self._run_agent, thread=True)
        return True

    def _resize_plan(self, pointer_screen_y: int) -> None:
        """Resize Plan, leaving the remaining middle-column space to worklog."""
        plan = self.query_one("#plan-scroll", VerticalScroll)
        work_pane = self.query_one("#work-pane", Vertical)
        requested = pointer_screen_y - plan.region.y + 1
        plan.styles.height = clamped_plan_height(requested, work_pane.size.height)

    def _animate_activity(self) -> None:
        self._monitor_tick += 1
        try:
            monitor = self.query_one("#entity-monitor", Static)
        except NoMatches:
            return
        try:
            art = self.query_one("#entity-art", Static)
        except NoMatches:
            art = None
        stopped = (
            self.coordinator.stop_requested
            or self.coordinator.paused.is_set()
            or (self.coordinator.workspace / "STOP").exists()
        )
        snapshot = self.coordinator.runtime_snapshot()
        state = str(snapshot.get("state", "IDLE"))
        effort_level = snapshot.get("effort_level")
        intensity = cardiac_monitor_intensity(state, stopped=stopped, effort_level=effort_level)
        for mode in ("stopped", "thinking", "working", "idle"):
            monitor.set_class(mode == intensity.name, f"monitor-{mode}")
            if art is not None:
                art.set_class(mode == intensity.name, f"monitor-{mode}")
        if art is not None:
            new_art = robot_art(intensity.name)
            if getattr(self, "_last_robot_art", None) != new_art:
                art.update(new_art)
                self._last_robot_art = new_art
        frame = (self._monitor_tick // intensity.tick_divisor) * intensity.tick_stride
        monitor_frame = cardiac_monitor_frame(
            frame,
            monitor.size.width,
            beat_interval=intensity.beat_interval,
            pulse_height=intensity.pulse_height,
            effort_level=intensity.effort_level,
            state=intensity.name,
        )
        if monitor_frame != getattr(self, "_last_monitor_frame", None):
            monitor.update(monitor_frame)
            self._last_monitor_frame = monitor_frame
        active = self._agent_running or self._draining_activity or self._draining_chat
        if not active:
            return
        frames = ("[>   ]", "[>>  ]", "[>>> ]", "[ >>>]", "[  >>]", "[   >]")
        self.title = (
            f"SELF — {self.coordinator.identity.display_name()} {frames[self._monitor_tick % len(frames)]} {state.lower()}"
        )

    def _queue_chat(self, role: str, message: str, kind: str) -> None:
        queue_chat(self, self.coordinator, role, message, kind)

    def _queue_activity(self, message: str) -> None:
        queue_activity(self, message)

    def _load_conversation_history(self) -> None:
        self._all_chat_messages = load_conversation_history(self.coordinator.workspace)

    def _populate_initial_chat(self) -> None:
        populate_initial_chat(self, self.coordinator)

    def _write_command(self, message: str) -> None:
        self._queue_activity(f"human command: {message}")

    def _open_coverage(self) -> None:
        open_coverage(self, self.coordinator)

    def _load_coverage(self, generation: int) -> None:
        load_coverage(self, self.coordinator, generation)

    def _coverage_error(self, generation: int, error: str) -> None:
        coverage_error(self, generation, error)

    def _show_coverage(self, generation: int, summary: Any) -> None:
        show_coverage(self, generation, summary)

    def _back_from_coverage(self) -> None:
        back_from_coverage(self)

    def _open_archive(self) -> None:
        open_archive(self, self.coordinator)

    def _load_archive(self, generation: int) -> None:
        load_archive(self, self.coordinator, generation)

    def _archive_error(self, generation: int, error: str) -> None:
        archive_error(self, generation, error)

    def _show_archive(self, generation: int, plans_text: str, goals_text: str) -> None:
        show_archive(self, generation, plans_text, goals_text)

    def _back_from_archive(self) -> None:
        back_from_archive(self)

    def _open_conversation_history(self, page: int = 0) -> None:
        open_conversation_history(self, self.coordinator, page=page)

    def _update_conversation_history_content(self) -> None:
        update_conversation_history_content(self, self.coordinator)

    def _back_from_conversation_history(self) -> None:
        back_from_conversation_history(self)

    def _restore_main_scroll(self, positions: tuple[float, float]) -> None:
        restore_main_scroll(self, positions)

    def _voice_status(self, message: str | None = None) -> None:
        self._queue_activity(message or self.voice.status_text())

    def _command_response(self, message: str, kind: str = "info") -> None:
        self._queue_activity(f"[{kind}] {message}")

    def _conversation_result(self, thread_id: str, message: str, kind: str) -> None:
        self.call_from_thread(self._queue_chat, "agent", message, "conversation" if kind == "assistant" else "error")

    def _ordinary_human_message(self, text: str) -> None:
        """Route the next ordinary response to an open reflection first and start conversation."""
        self._queue_chat("human", text, "human")
        reply = self.coordinator.accept_reflection_reply(text)
        if reply is not None:
            self._command_response("Reflection reply recorded; I will also consider it at the next work step.", "request")
        else:
            self.coordinator.receive_human_input(f"Human said: {text}", kind="chat")

        if (self.coordinator.workspace / "STOP").exists() or self.coordinator.stop_requested:
            status_msg = "Conversation thread started. Autonomous cycles are stopped (use /restart to resume)."
        elif self.coordinator.has_pending_human_request():
            status_msg = "Conversation thread started. Autonomous cycles are waiting for HUMAN_REQUEST.md."
        elif self.coordinator.paused.is_set():
            status_msg = "Conversation thread started. Autonomous cycles are paused (use /resume to continue)."
        elif self._agent_running:
            status_msg = "Conversation thread started; autonomous work continues in background."
        else:
            status_msg = "Conversation thread started."
        self._command_response(status_msg)
        self.coordinator.start_conversation(text, self._conversation_result)

    def _watch_human_request(self) -> None:
        if (self.coordinator.workspace / "STOP").exists():
            return
        if self.coordinator.has_pending_human_request():
            if not (self.coordinator.workspace / "HUMAN_REQUEST.md").exists():
                self.coordinator.clear_human_request()
                self._start_agent()
            elif hasattr(self.coordinator, "has_runnable_goals") and self.coordinator.has_runnable_goals():
                self._start_agent()
            else:
                self.set_timer(2.0, self._watch_human_request)
        else:
            self._start_agent()

    def _finish_agent_turn(self, final_message: str | None, restart_delay: float | None) -> None:
        if final_message:
            self._command_response(
                final_message,
                "request" if any(word in final_message.lower() for word in ("paused", "waiting", "human action")) else "session",
            )
        if (self.coordinator.workspace / "STOP").exists():
            return
        if restart_delay is not None and restart_delay < 0:
            return
        if (
            self.coordinator.has_pending_human_request()
            and hasattr(self.coordinator, "has_runnable_goals")
            and not self.coordinator.has_runnable_goals()
        ):
            self.set_timer(2.0, self._watch_human_request)
        else:
            self.set_timer(restart_delay if restart_delay is not None else 0.8, self._start_agent)

    def _run_agent(self) -> None:
        final_message: str | None = None
        restart_delay: float | None = None
        try:
            result = self.coordinator.run()
            if not (result is None and (self.coordinator.workspace / "STOP").exists()):
                if getattr(result, "reason", "") == "broker_panic":
                    final_message = "I paused because the permission broker blocked repeated tool actions. Check the recent action_denied events; /restart resumes after the cause is resolved."
                    restart_delay = -1.0
                elif getattr(result, "reason", "") == "no_progress":
                    final_message = "I paused after repeating the same result with plan and map writes unavailable. Review config/permissions.json or choose another goal, then use /restart."
                    restart_delay = -1.0
                elif (
                    (self.coordinator.workspace / "STOP").exists()
                    or self.coordinator.stop_requested
                    or getattr(result, "reason", "") in {"stop_file", "stop_watcher"}
                ):
                    final_message = "I am paused because STOP was requested. Remove workspace/STOP or use /restart when you want me to continue."
                    restart_delay = -1.0
                elif self.coordinator.has_pending_human_request():
                    if hasattr(self.coordinator, "has_runnable_goals") and self.coordinator.has_runnable_goals():
                        final_message = "A human request is pending for a paused task; continuing autonomous work on other goals."
                        restart_delay = 0.8
                    else:
                        final_message = "I am waiting for your decision in HUMAN_REQUEST.md. Use /approve, /decline, or /resume; I will wake automatically."
                        restart_delay = -1.0
                elif getattr(result, "iterations", 0) == 0:
                    final_message = f"Session completed 0 cycles with reason '{getattr(result, 'reason', 'unknown')}'. Use /restart when ready."
                    restart_delay = -1.0
                else:
                    final_message = "This session ended; I will start the next session automatically."
                    restart_delay = 0.8 if result is None or getattr(result, "reason", "") != "provider_error" else 3.0
        except Exception as exc:
            self.coordinator.logger.narrate(f"Wake coordinator failed: {type(exc).__name__}")
            final_message = f"This session failed with {type(exc).__name__}; I will retry automatically unless you stop me."
            restart_delay = 3.0
        finally:
            self._agent_running = False
            self.call_from_thread(self._finish_agent_turn, final_message, restart_delay)

    def _refresh(self) -> None:
        refresh_all_status_panels(self, self.coordinator)

    def on_input_submitted(self, event: Any) -> None:
        text = str(event.value).strip()
        event.input.value = ""
        if not text:
            return
        if self._command_registry.dispatch(self, self.coordinator, text):
            return
        self._ordinary_human_message(text)

    def _listen_for_human(self) -> None:
        text, error = self.voice.listen()
        if error:
            self.call_from_thread(self._command_response, error, "error")
            return
        if text:
            self.call_from_thread(self._ordinary_human_message, text)


def run_tui(coordinator: Any) -> int:
    """Run a wake session with the terminal UI, falling back to headless if Textual is unavailable."""
    try:
        from textual.app import App
    except ImportError:
        coordinator.logger.narrate("Textual is unavailable; falling back to --headless mode.")
        return run_headless(coordinator)

    SelfApp(coordinator=coordinator).run()
    return 0


__all__ = [
    "SelfApp",
    "run_tui",
]
