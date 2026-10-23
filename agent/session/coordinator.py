"""Headless wake session coordinator and session lifecycle management facade."""
from __future__ import annotations

from collections import deque
import os
from pathlib import Path
import threading
import time
from typing import Any, Callable

from agent.body.base import Body
from agent.body.container import ContainerBody
from agent.identity.identity import IdentityStore
from agent.infra.audit_trail import AuditTrail
from agent.infra.event_log import EventLogger
from agent.infra.hardening import DailyTokenLedger
from agent.infra.permission_broker import PermissionBroker
from agent.infra.stop_watcher import StopWatcher
from agent.learning.learning import LearningStore
from agent.learning.plan import PlanStore
from agent.session.boot import (
    identity_observation,
    now_utc,
    orientation_changes,
    run_boot_sequence,
    spot_check_map,
)
from agent.session.conversation import ConversationManager
from agent.session.event_router import handle_checkpoint_cycle, handle_session_event
from agent.session.handoff_builder import (
    _read_json,
    make_handoff,
    pending_human_inputs,
    requests_text as _requests_text,
    tool_list,
)
from agent.session.headless import run_headless
from agent.session.human_input import (
    build_conversation_context,
    build_models_snapshot,
    format_recent_decisions,
    handle_receive_human_input,
    human_name_candidate,
)
from agent.session.plan_recovery import (
    COMPLETED_PLAN_STATUSES,
    format_starting_plan,
    normalized_plan,
    recover_budget_blocked_plan,
    revise_session_plan,
    visible_plan_items,
)
from agent.session.plugin_commands import (
    handle_plugins_command,
    handle_proposals_command,
    handle_slash_command,
)
from agent.session.reflection import ReflectionManager
from agent.session.reflection_scheduler import (
    accept_reflection_reply,
    handle_reflection_ready,
    reflection_triggers,
    schedule_reflection,
)
from agent.session.session import HumanInbox, SessionStore, default_plan
from agent.session.session_runner import run_session, run_session_with_lock
from agent.session.shutdown_reflection import run_session_reflection
from agent.session.telemetry import (
    RuntimeTelemetry,
    WakeStatus,
    build_runtime_snapshot,
    update_telemetry,
)


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, min(value, maximum))


class WakeCoordinator:
    """Coordinate wake sessions, headless execution, and the agent loop."""

    def __init__(
        self,
        workspace: str | Path = "/home/entity",
        *,
        max_iterations: int | None = None,
        token_budget: int | None = None,
        max_wall_clock_seconds: int | None = None,
        llm_client: Any | None = None,
        body: Body | None = None,
    ) -> None:
        self.workspace = Path(workspace)
        self.logger = EventLogger(self.workspace / "logs" / "actions.jsonl")
        if body is None:
            body = ContainerBody(
                workspace=self.workspace,
                logger=self.logger,
            )
        self.body = body
        self.learning = LearningStore(self.workspace, self.logger, body=self.body)
        self.sessions = SessionStore(self.workspace, self.logger)
        self.inbox = HumanInbox(self.workspace, self.logger)
        self.identity = IdentityStore(self.workspace, self.logger, body=self.body)
        self.plan_store = PlanStore(self.workspace, self.logger)

        if max_iterations is not None:
            self.max_iterations = max_iterations
        else:
            configured_iterations = int(os.getenv("SELF_MAX_ITERATIONS", "0"))
            self.max_iterations = configured_iterations if configured_iterations > 0 else None
        configured_budget = token_budget if token_budget is not None else int(os.getenv("SELF_TOKEN_BUDGET", "0"))
        self.token_budget = configured_budget if configured_budget > 0 else None
        self.daily_ledger = DailyTokenLedger(self.workspace, self.logger)
        configured_wall_clock = (
            max_wall_clock_seconds if max_wall_clock_seconds is not None else int(os.getenv("SELF_MAX_WALL_CLOCK_SECONDS", "0"))
        )
        self.max_wall_clock_seconds = configured_wall_clock if configured_wall_clock > 0 else None
        self.paused = threading.Event()
        self.stop_requested = False
        self.lock = threading.Lock()
        self.plan: list[dict[str, Any]] = default_plan()
        self.handoff: dict[str, Any] = {}
        self.starting_plan: list[dict[str, Any]] = []
        self.starting_session_id: str = ""
        self.status = WakeStatus(started_monotonic=time.monotonic(), last_human_input=time.monotonic())
        self.telemetry = RuntimeTelemetry()
        self._last_checkpoint = time.monotonic()
        self._session_start = ""
        self._session_info: dict[str, Any] = {}
        self._first_awakening_messages: list[str] = []
        self._llm: Any = llm_client
        self._activity: deque[str] = deque(maxlen=400)
        self._cycle_summaries: deque[str] = deque(maxlen=40)
        self.on_narration: Callable[[str, str], None] | None = None
        self.on_chat: Callable[[str, str], None] | None = None
        self.on_activity: Callable[[str], None] | None = None
        self.conversations = ConversationManager(
            self.workspace,
            self.logger,
            self.daily_ledger,
            llm_client,
            max_workers=int(os.getenv("SELF_MAX_CONVERSATION_WORKERS", "2")),
            body=self.body,
        )

        self.reflections = ReflectionManager(
            self.workspace,
            self.logger,
            self.daily_ledger,
            llm_client,
            enabled=os.getenv("SELF_REFLECTION_ENABLED", "1").lower() not in {"0", "false", "no", "off"},
            max_per_session=_env_int("SELF_REFLECTION_MAX_PER_SESSION", 3, 1, 20),
            min_cycles=_env_int("SELF_REFLECTION_MIN_CYCLES", 3, 1, 100),
            max_tokens=_env_int("SELF_REFLECTION_MAX_TOKENS", 384, 64, 1_024),
            stop_provider=lambda: self.stop_requested or (self.workspace / "STOP").exists(),
        )
        from agent.plugins.manager import PluginManager

        self.plugins = PluginManager(self.workspace, logger=self.logger)

        policy_path = Path("/config/permissions.json")
        if not policy_path.exists():
            policy_path = self.workspace / "config" / "permissions.json"
        if not policy_path.exists():
            policy_path = Path("config/permissions.json")

        self.audit_trail = AuditTrail(self.workspace / "state" / "audit_trail.jsonl", logger=self.logger)
        self.broker = PermissionBroker(
            policy_path=policy_path if policy_path.exists() else None,
            logger=self.logger,
            audit_trail=self.audit_trail,
        )
        self.body.broker = self.broker
        self.plugins.broker = self.broker
        self.stop_watcher = StopWatcher(
            workspace=self.workspace,
            body=self.body,
            broker=self.broker,
            logger=self.logger,
            install_signals=True,
        )
        self.logger.add_listener(self._event_listener)

    def _update_telemetry(self, record: dict[str, Any]) -> None:
        update_telemetry(self.telemetry, record, lock=self.lock)

    def runtime_snapshot(self) -> dict[str, Any]:
        """Return current runtime telemetry for the UI."""
        return build_runtime_snapshot(self.telemetry, self._activity, lock=self.lock)

    def _checkpoint_cycle(self, cycle: int, report: str, tokens: int) -> None:
        handle_checkpoint_cycle(self, cycle, report, tokens)

    def _event_listener(self, record: dict[str, Any]) -> None:
        handle_session_event(self, record)

    @staticmethod
    def _reflection_triggers(actions: list[dict[str, Any]]) -> list[str]:
        return reflection_triggers(actions)

    def _schedule_reflection(self, record: dict[str, Any]) -> None:
        schedule_reflection(
            self.reflections,
            self.status.session_id,
            record,
            context_provider=self.reflection_context,
            on_result=self._reflection_ready,
            stop_check=lambda: self.stop_requested or (self.workspace / "STOP").exists(),
        )

    def _reflection_ready(self, reflection: dict[str, Any]) -> None:
        handle_reflection_ready(
            reflection,
            self.on_chat,
            self.logger,
            stop_check=lambda: self.stop_requested or (self.workspace / "STOP").exists(),
        )

    def accept_reflection_reply(self, text: str) -> dict[str, str] | None:
        """Persist a reply and inject it into the next safe autonomous turn."""
        return accept_reflection_reply(self.reflections, text, self.receive_human_input)

    def _pending_human_inputs(self) -> list[str]:
        return pending_human_inputs(self.workspace)

    _pending_requests = _pending_human_inputs

    def _tool_list(self) -> list[str]:
        return tool_list(self.workspace)

    def handle_plugins_command(self, command: str) -> str:
        """Handle human-only /plugins commands for listing, enabling, and disabling plugins."""
        return handle_plugins_command(self.plugins, command)

    def handle_proposals_command(self, command: str = "/proposals") -> str:
        """Display plugin proposals from state/plugin_proposals.jsonl or record comments."""
        return handle_proposals_command(
            self.workspace,
            self.logger,
            command,
            receive_input_fn=self.receive_human_input,
        )

    def handle_slash_command(self, text: str) -> str | None:
        """Dispatch a human-facing slash command to active plugins."""
        return handle_slash_command(getattr(self, "plugins", None), text)

    def _orientation_changes(self) -> list[str]:
        return orientation_changes(self.body)

    def _spot_check_map(self) -> list[str]:
        return spot_check_map(self.learning, self.workspace)

    def _identity_observation(self) -> str:
        """Return only an evidence-backed observation for a later greeting."""
        return identity_observation(self.identity)

    def boot(self) -> str:
        """Load persistent state and prepare a new wake session."""
        return run_boot_sequence(self)

    def _reflection(self, purpose: str, extra: str = "") -> dict[str, Any]:
        """One bounded planning/reflection call; deterministic fallback preserves continuity."""
        return run_session_reflection(self, purpose, extra)

    def models_snapshot(self) -> dict[str, Any]:
        """Return model registry data and recent decisions."""
        return build_models_snapshot(self._llm, self.workspace, self.logger)

    def revise_plan(self) -> None:
        """Replace the active plan with validated, actionable entries."""
        revise_session_plan(self)

    def render_starting_plan(self) -> str:
        """Render the plan that was established when the current session started."""
        with self.lock:
            plan = list(self.starting_plan or self.plan)
            session_id = self.starting_session_id or self.status.session_id
        return format_starting_plan(plan, session_id=session_id)

    def _recover_budget_blocked_plan(self) -> None:
        """Clear stale budget blockers once the daily ledger has room again."""
        new_plan, _ = recover_budget_blocked_plan(
            self.plan,
            self.daily_ledger,
            self.learning,
            self.token_budget,
            self.logger,
        )
        self.plan = new_plan

    def _make_handoff(self, report: str, reason: str) -> dict[str, Any]:
        return make_handoff(
            self.workspace,
            self.learning,
            self.handoff,
            self.plan,
            report,
            reason,
        )

    def receive_human_input(self, text: str, kind: str = "goal") -> None:
        """Queue human input for the next safe agent turn."""
        handle_receive_human_input(self, text, kind=kind)

    def request_stop(self, reason: str = "requested") -> None:
        """Trigger an immediate hard stop via StopWatcher."""
        self.stop_requested = True
        if hasattr(self, "stop_watcher") and self.stop_watcher is not None:
            self.stop_watcher.request_stop(reason=reason)
        else:
            try:
                (self.workspace / "STOP").touch()
            except OSError:
                pass

    def pause(self) -> None:
        """Pause autonomous cycles."""
        self.paused.set()
        if hasattr(self, "stop_watcher") and self.stop_watcher is not None:
            self.stop_watcher.pause()

    def resume(self) -> None:
        """Resume autonomous cycles."""
        self.paused.clear()
        if hasattr(self, "stop_watcher") and self.stop_watcher is not None:
            self.stop_watcher.resume()

    def close(self) -> None:
        """Cleanly shut down background watchers and executors."""
        if hasattr(self, "stop_watcher") and self.stop_watcher is not None:
            self.stop_watcher.shutdown()
        if hasattr(self, "conversations") and self.conversations is not None:
            self.conversations.close()
        if hasattr(self, "reflections") and self.reflections is not None:
            self.reflections.close()

    def recent_decisions(self) -> str:
        """Return formatted recent human input decisions."""
        return format_recent_decisions(self.plan_store)

    def conversation_context(self) -> str:
        """Build a bounded read-only snapshot for an independent conversation."""
        return build_conversation_context(
            self.identity,
            self.handoff,
            self.plan_store,
            self.plan,
            self._activity,
            self._cycle_summaries,
        )

    def reflection_context(self) -> str:
        """Provide concise context for background reflection threads."""
        return self.conversation_context()

    def start_conversation(self, text: str, on_result: Callable[[str, str, str], None]) -> str:
        """Start an independent read-only conversation thread."""
        return self.conversations.submit(text, self.conversation_context, on_result)

    @staticmethod
    def _human_name_candidate(text: str) -> str | None:
        return human_name_candidate(text)

    def run(self) -> Any:
        """Run the current wake session within its configured limits."""
        return run_session_with_lock(self)

    def _run_session(self) -> Any:
        return run_session(self)


__all__ = [
    "COMPLETED_PLAN_STATUSES",
    "WakeCoordinator",
    "WakeStatus",
    "RuntimeTelemetry",
    "run_headless",
    "visible_plan_items",
    "normalized_plan",
    "format_starting_plan",
    "now_utc",
    "_requests_text",
    "_read_json",
    "_env_int",
]
