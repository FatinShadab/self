"""SELF's wake-up coordinator and optional Textual terminal interface."""
from __future__ import annotations

import argparse
import asyncio
from collections import deque
import json
import os
import platform
import re
import shutil
import signal
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from agent.tools.base_tools import TOOL_DEFINITIONS, ToolRunner
from agent.session.conversation import ConversationManager
from agent.learning.exploration_coverage import CoverageSummary, build_coverage
from agent.infra.event_log import EventLogger
from agent.infra.hardening import DailyTokenLedger
from agent.identity.identity import IdentityStore
from agent.learning.learning import LearningStore
from agent.llm.llm import BudgetedLLM, LLMClient, response_truncated
from agent.helper_models.model_decisions import ModelDecisions
from agent.infra.file_lock import locked_file
from agent.runtime.loop import AgentConfig, AgentLoop, STANDING_GOAL
from agent.learning.plan import PlanStore
from agent.session.reflection import ReflectionManager
from agent.session.session import HumanInbox, SessionStore, default_plan


KNOWN_CREDENTIAL_ENV = (
    "OLLAMA_API_KEYS", "OLLAMA_API_KEY", "OLLAM_API_KEYS", "OLLAM_API_KEY",
    "ANTHROPIC_API_KEYS", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "GROQ_API_KEY",
    "OPENROUTER_API_KEY", "MISTRAL_API_KEY", "CEREBRAS_API_KEY", "HF_TOKEN",
    "CLOUDFLARE_API_TOKEN",
)

COMPLETED_PLAN_STATUSES = frozenset({
    "done", "complete", "completed", "achieved", "finished", "closed",
    "cancelled", "canceled", "dropped",
})

PLAN_MIN_HEIGHT = 5
WORKLOG_MIN_HEIGHT = 5
PLAN_RESIZER_HEIGHT = 1
CARDIAC_MONITOR_WIDTH = 6
CARDIAC_MONITOR_BEAT_INTERVAL = 13


@dataclass(frozen=True)
class CardiacMonitorIntensity:
    """Visual tempo and amplitude for one agent-presence state."""

    name: str
    beat_interval: int
    pulse_height: int
    tick_divisor: int
    tick_stride: int


MONITOR_STOPPED = CardiacMonitorIntensity("stopped", 1, 0, 1, 0)
MONITOR_THINKING = CardiacMonitorIntensity("thinking", 21, 2, 3, 1)
MONITOR_WORKING = CardiacMonitorIntensity("working", 9, 3, 1, 2)
MONITOR_IDLE = CardiacMonitorIntensity("idle", 17, 2, 4, 1)


def cardiac_monitor_intensity(state: str, *, stopped: bool = False) -> CardiacMonitorIntensity:
    """Choose a monitor profile from the coordinator's live state."""
    if stopped:
        return MONITOR_STOPPED
    state = state.strip().upper()
    if "THINK" in state:
        return MONITOR_THINKING
    if state in {"WORKING", "USING TOOL"}:
        return MONITOR_WORKING
    return MONITOR_IDLE


def cardiac_monitor_frame(
    frame: int,
    width: int = CARDIAC_MONITOR_WIDTH,
    *,
    beat_interval: int = CARDIAC_MONITOR_BEAT_INTERVAL,
    pulse_height: int = 3,
) -> str:
    """Render a full-width ECG trace at the requested intensity."""
    width = max(6, width)
    rows = [[" "] * width for _ in range(3)]
    rows[2] = ["_"] * width
    if pulse_height <= 0:
        return "\n".join("".join(row) for row in rows)

    # Thinking has a short, quiet peak. Work has a taller and more frequent
    # spike. Both sweep across the full available header width.
    pulse = ((0, 2, "/"), (1, 1, "/"), (2, 1, "\\"), (3, 2, "\\")) if pulse_height < 3 else (
        (0, 2, "/"), (1, 1, "/"), (2, 0, "|"), (3, 1, "\\"), (4, 2, "\\")
    )
    phase = frame % max(5, beat_interval)
    for pulse_x in range(width - phase, -len(pulse), -max(5, beat_interval)):
        for offset, row, character in pulse:
            column = pulse_x + offset
            if 0 <= column < width:
                rows[row][column] = character
    return "\n".join("".join(row) for row in rows)


def visible_plan_items(plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return only active plan items for the live panel."""
    return [
        item for item in plan
        if isinstance(item, dict)
        and str(item.get("status", "todo")).strip().lower() not in COMPLETED_PLAN_STATUSES
    ]


def normalized_plan(plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only actionable plan entries in durable state.

    Completed/cancelled entries are useful in logs, but retaining them in the
    handoff invites the next reflection to resurrect stale work.
    """
    active = visible_plan_items(plan)
    for it in active:
        g = str(it.get("goal") or it.get("step", "")).strip()
        it["goal"] = g
        it["step"] = g
    return active if active else default_plan()


def clamped_plan_height(requested: int, work_pane_height: int) -> int:
    """Keep both panes usable while the plan divider is dragged."""
    maximum = max(
        PLAN_MIN_HEIGHT,
        work_pane_height - WORKLOG_MIN_HEIGHT - PLAN_RESIZER_HEIGHT,
    )
    return max(PLAN_MIN_HEIGHT, min(maximum, requested))


def escape_rich_markup(value: Any) -> str:
    """Return untrusted text that is safe to interpolate into Rich markup.

    The TUI uses a few Rich tags for its own headings. Plan entries, identity
    fields, provider labels, and telemetry, however, can originate with an LLM
    or command output. Escape every literal ``[`` (rather than just known tag
    shapes) so arbitrary bracketed text cannot become Rich markup and make the
    entire Textual screen fail to reflow.
    """
    return str(value).replace("\\", "\\\\").replace("[", "\\[")


def format_models_snapshot(snapshot: dict[str, Any]) -> str:
    """Readable /models view of registry evidence and recent decisions."""
    registry = snapshot.get("registry") or {}
    models = registry.get("models", []) if isinstance(registry, dict) else []
    lines = ["Model registry:"]
    if not models:
        lines.append("No model data yet.")
    for entry in models:
        stats = entry.get("measured_stats") or {}
        lines.append(f"- {entry.get('name', 'unknown')} ({entry.get('role', '?')}): "
                     f"status={entry.get('status', 'unknown')}; "
                     f"calls={stats.get('calls', 0)} failures={stats.get('failures', 0)}; "
                     f"assessment={entry.get('agent_assessment') or 'none'}; "
                     f"ratings={json.dumps(entry.get('ratings'), ensure_ascii=False, sort_keys=True)}; "
                     f"measured_stats={json.dumps(stats, ensure_ascii=False, sort_keys=True)}")
    lines.append("Last ten decisions:")
    decisions = snapshot.get("last_ten_decisions") or []
    if not decisions:
        lines.append("No decisions yet.")
    for row in decisions[-10:]:
        lines.append(f"- {row.get('source', '?')} → {row.get('model', '?')} "
                     f"origin={row.get('origin', 'unknown')} task={row.get('task_type', '?')}")
    return "\n".join(lines)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, min(value, maximum))


@dataclass
class WakeStatus:
    """Current identity, timing, and usage of the wake session."""

    session_id: str = ""
    iteration: int = 0
    tokens_used: int = 0
    active_model: str = "uninitialized"
    active_provider: str = "uninitialized"
    started_monotonic: float = 0.0
    last_human_input: float = 0.0


@dataclass
class RuntimeTelemetry:
    """Live, non-secret runtime facts used by the TUI's presence panel."""

    state: str = "STARTING"
    active_calls: int = 0
    total_calls: int = 0
    completed_calls: int = 0
    failed_calls: int = 0
    calls_by_ai: dict[str, int] = field(default_factory=dict)
    current_ai: str = "-"
    last_ai: str = "-"
    run_tokens_used: int = 0
    run_budget: int = 0
    daily_used: int = 0
    daily_reserved: int = 0
    daily_cap: int = 0
    daily_blocked: bool = False
    current_activity: str = ""


def _format_bytes(value: int | None) -> str:
    if value is None or value < 0:
        return "—"
    amount = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if amount < 1024 or unit == "TB":
            return f"{amount:.1f} {unit}" if unit != "B" else f"{int(amount)} B"
        amount /= 1024
    return "—"


def _read_int_file(path: str | Path) -> int | None:
    try:
        return int(Path(path).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _read_cgroup_value(filename: str, *groups: str) -> int | None:
    for group in groups:
        value = _read_int_file(Path("/sys/fs/cgroup") / group / filename)
        if value is not None:
            return value
    return None


class ContainerMetrics:
    """Best-effort live metrics for the current container namespace/cgroup."""

    def __init__(self) -> None:
        self._last_cpu_usage: int | None = None
        self._last_sample = time.monotonic()

    @staticmethod
    def _cpu_usage() -> tuple[int | None, float]:
        stat_path = Path("/sys/fs/cgroup/cpu.stat")
        usage = None
        try:
            values = {}
            for line in stat_path.read_text(encoding="utf-8").splitlines():
                key, _, raw = line.partition(" ")
                if key and raw:
                    values[key] = int(raw)
            usage = values.get("usage_usec")
        except (OSError, ValueError):
            usage_ns = _read_cgroup_value("cpuacct.usage", "cpuacct")
            usage = usage_ns // 1_000 if usage_ns is not None else None

        quota_cpus = float(os.cpu_count() or 1)
        try:
            quota, period = Path("/sys/fs/cgroup/cpu.max").read_text(encoding="utf-8").split()
            if quota != "max" and int(period) > 0:
                quota_cpus = max(0.01, int(quota) / int(period))
        except (OSError, ValueError):
            quota = _read_cgroup_value("cpu.cfs_quota_us", "cpu")
            period = _read_cgroup_value("cpu.cfs_period_us", "cpu")
            if quota is not None and quota > 0 and period:
                quota_cpus = max(0.01, quota / period)
        return usage, quota_cpus

    def snapshot(self) -> dict[str, Any]:
        """Return a read-only snapshot of current state."""
        now = time.monotonic()
        elapsed = max(0.001, now - self._last_sample)
        cpu_usage, quota_cpus = self._cpu_usage()
        cpu_percent: float | None = None
        if cpu_usage is not None and self._last_cpu_usage is not None:
            cpu_percent = max(0.0, (cpu_usage - self._last_cpu_usage) / 1_000_000 / elapsed / quota_cpus * 100)
        self._last_cpu_usage = cpu_usage
        self._last_sample = now

        ram_used = _read_int_file("/sys/fs/cgroup/memory.current")
        ram_limit: int | None = None
        try:
            raw_limit = Path("/sys/fs/cgroup/memory.max").read_text(encoding="utf-8").strip()
            if raw_limit != "max":
                ram_limit = int(raw_limit)
        except (OSError, ValueError):
            ram_used = ram_used or _read_cgroup_value("memory.usage_in_bytes", "memory")
            ram_limit = _read_cgroup_value("memory.limit_in_bytes", "memory")
            if ram_limit and ram_limit >= 2**60:
                ram_limit = None

        rx_bytes = 0
        tx_bytes = 0
        try:
            for line in Path("/proc/net/dev").read_text(encoding="utf-8").splitlines():
                if ":" not in line:
                    continue
                interface, raw_stats = line.split(":", 1)
                if interface.strip() == "lo":
                    continue
                stats = raw_stats.split()
                if len(stats) >= 9:
                    rx_bytes += int(stats[0])
                    tx_bytes += int(stats[8])
        except (OSError, ValueError):
            rx_bytes = tx_bytes = 0

        disk_read: int | None = None
        try:
            total = 0
            found = False
            for line in Path("/sys/fs/cgroup/io.stat").read_text(encoding="utf-8").splitlines():
                for item in line.split()[1:]:
                    if item.startswith("rbytes="):
                        total += int(item.split("=", 1)[1])
                        found = True
            if found:
                disk_read = total
        except (OSError, ValueError):
            disk_read = None

        return {
            "cpu": f"{cpu_percent:.1f}% / {quota_cpus:g} CPU" if cpu_percent is not None else "—",
            "ram": f"{_format_bytes(ram_used)} / {_format_bytes(ram_limit)}" if ram_limit else _format_bytes(ram_used),
            "network": f"RX {_format_bytes(rx_bytes)} · TX {_format_bytes(tx_bytes)}",
            "disk_read": _format_bytes(disk_read),
        }


class WakeCoordinator:
    """Coordinate wake sessions, UI events, and the agent loop."""

    def __init__(self, workspace: str | Path = "/home/entity", *, max_iterations: int | None = None, token_budget: int | None = None, max_wall_clock_seconds: int | None = None, llm_client: Any | None = None) -> None:
        self.workspace = Path(workspace)
        self.logger = EventLogger(self.workspace / "logs" / "actions.jsonl")
        self.learning = LearningStore(self.workspace, self.logger)
        self.sessions = SessionStore(self.workspace, self.logger)
        self.inbox = HumanInbox(self.workspace, self.logger)
        self.identity = IdentityStore(self.workspace, self.logger)
        configured_iterations = max_iterations if max_iterations is not None else int(os.getenv("SELF_MAX_ITERATIONS", "0"))
        self.max_iterations = configured_iterations if configured_iterations > 0 else None
        configured_budget = token_budget if token_budget is not None else int(os.getenv("SELF_TOKEN_BUDGET", "0"))
        self.token_budget = configured_budget if configured_budget > 0 else None
        self.daily_ledger = DailyTokenLedger(self.workspace, self.logger)
        configured_wall_clock = max_wall_clock_seconds if max_wall_clock_seconds is not None else int(os.getenv("SELF_MAX_WALL_CLOCK_SECONDS", "0"))
        self.max_wall_clock_seconds = configured_wall_clock if configured_wall_clock > 0 else None
        self.paused = threading.Event()
        self.stop_requested = False
        self.lock = threading.Lock()
        self.plan: list[dict[str, Any]] = default_plan()
        self.handoff: dict[str, Any] = {}
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
        self.conversations = ConversationManager(self.workspace, self.logger, self.daily_ledger, llm_client,
                                                 max_workers=int(os.getenv("SELF_MAX_CONVERSATION_WORKERS", "2")))
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
        self.logger.add_listener(self._event_listener)

    def _update_telemetry(self, record: dict[str, Any]) -> None:
        event = str(record.get("event", ""))
        with self.lock:
            if event == "run_started":
                self.telemetry.state = "THINKING"
                self.telemetry.run_budget = int(record.get("token_budget", 0) or self.telemetry.run_budget)
                self.telemetry.daily_cap = int(record.get("daily_token_budget", 0) or self.telemetry.daily_cap)
            elif event == "llm_call_started":
                ai = f"{record.get('provider', 'unknown')}/{record.get('model', 'unknown')}"
                self.telemetry.active_calls += 1
                self.telemetry.total_calls += 1
                self.telemetry.current_ai = ai
                self.telemetry.last_ai = ai
                self.telemetry.calls_by_ai[ai] = self.telemetry.calls_by_ai.get(ai, 0) + 1
                self.telemetry.state = "THINKING"
            elif event == "llm_call_completed":
                self.telemetry.active_calls = max(0, self.telemetry.active_calls - 1)
                self.telemetry.completed_calls += 1
                self.telemetry.state = "THINKING" if self.telemetry.active_calls else "WORKING"
            elif event == "provider_call_completed":
                ai = f"{record.get('provider', 'unknown')}/{record.get('model', 'unknown')}"
                self.telemetry.total_calls += 1
                self.telemetry.completed_calls += 1
                self.telemetry.current_ai = ai
                self.telemetry.last_ai = ai
                self.telemetry.calls_by_ai[ai] = self.telemetry.calls_by_ai.get(ai, 0) + 1
                self.telemetry.state = "WORKING"
            elif event in {"llm_call_failed", "provider_call_failed", "provider_call_unavailable"}:
                self.telemetry.active_calls = max(0, self.telemetry.active_calls - 1)
                self.telemetry.failed_calls += 1
                if event != "llm_call_failed":
                    ai = f"{record.get('provider', 'unknown')}/{record.get('model', 'unknown')}"
                    self.telemetry.total_calls += 1
                    self.telemetry.last_ai = ai
                    self.telemetry.calls_by_ai[ai] = self.telemetry.calls_by_ai.get(ai, 0) + 1
                self.telemetry.state = "WORKING"
            elif event == "tool_call":
                self.telemetry.state = "USING TOOL"
            elif event == "tool_result":
                self.telemetry.state = "WORKING"
            elif event == "token_spend":
                self.telemetry.run_tokens_used = int(record.get("run_tokens_used", self.telemetry.run_tokens_used) or 0)
                reported_budget = int(record.get("run_token_budget", self.telemetry.run_budget) or 0)
                # Wake-up/shutdown reflections use a small private budget;
                # do not let them overwrite the main run budget in the TUI.
                if self.telemetry.run_budget <= reported_budget:
                    self.telemetry.run_budget = reported_budget
            elif event == "run_token_budget_adapted":
                self.telemetry.run_budget = int(record.get("new_budget", self.telemetry.run_budget) or 0)
            elif event == "daily_token_budget_updated":
                self.telemetry.daily_used = int(record.get("used", self.telemetry.daily_used) or 0)
                self.telemetry.daily_reserved = int(record.get("reserved", self.telemetry.daily_reserved) or 0)
                self.telemetry.daily_cap = int(record.get("cap", self.telemetry.daily_cap) or 0)
            elif event == "daily_token_budget_blocked":
                self.telemetry.daily_blocked = True
                self.telemetry.daily_used = int(record.get("used", self.telemetry.daily_used) or 0)
                self.telemetry.daily_reserved = int(record.get("reserved", self.telemetry.daily_reserved) or 0)
                self.telemetry.daily_cap = int(record.get("cap", self.telemetry.daily_cap) or 0)
                self.telemetry.state = "WAITING FOR HUMAN"
            elif event == "run_completed":
                self.telemetry.state = "IDLE" if record.get("reason") != "human_request_pending" else "WAITING FOR HUMAN"

    def runtime_snapshot(self) -> dict[str, Any]:
        """Return current runtime telemetry for the UI."""
        with self.lock:
            return {
                "state": self.telemetry.state,
                "active_calls": self.telemetry.active_calls,
                "total_calls": self.telemetry.total_calls,
                "completed_calls": self.telemetry.completed_calls,
                "failed_calls": self.telemetry.failed_calls,
                "calls_by_ai": dict(self.telemetry.calls_by_ai),
                "current_ai": self.telemetry.current_ai,
                "last_ai": self.telemetry.last_ai,
                "run_tokens_used": self.telemetry.run_tokens_used,
                "run_budget": self.telemetry.run_budget,
                "daily_used": self.telemetry.daily_used,
                "daily_reserved": self.telemetry.daily_reserved,
                "daily_cap": self.telemetry.daily_cap,
                "daily_blocked": self.telemetry.daily_blocked,
                "current_activity": self.telemetry.current_activity,
                "activity": list(self._activity)[-80:],
            }

    def _event_listener(self, record: dict[str, Any]) -> None:
        self._update_telemetry(record)
        event = str(record.get("event", ""))
        activity = ""
        if event == "command_started":
            activity = f"$ {record.get('command', '')}"
        elif event == "command_output":
            activity = "  " + str(record.get("output", "")).rstrip()
        elif event == "command_finished":
            status = "timeout" if record.get("timed_out") else f"exit {record.get('exit_code')}"
            activity = f"  [{status}]"
        elif event == "tool_call":
            activity = f"tool: {record.get('tool', '')}"
        elif event == "tool_result":
            activity = f"tool result: {record.get('tool', '')} · {'ok' if record.get('ok') else 'failed'}"
        elif event == "agent_step":
            activity = "step: " + str(record.get("message", ""))
        elif event == "narration":
            activity = str(record.get("message", ""))
        elif event == "cycle_completed":
            summary = f"Cycle {record.get('cycle', '?')} summary\n{record.get('report', '')}".strip()
            self._cycle_summaries.append(summary)
            if self.on_chat and not self.stop_requested and not (self.workspace / "STOP").exists():
                self.on_chat(summary, "cycle")
            self._schedule_reflection(record)
        elif event == "session_summary":
            if self.on_chat and not self.stop_requested and not (self.workspace / "STOP").exists():
                self.on_chat(str(record.get("message", "")), "session")
        if activity:
            clean = self.logger.redactor.text(activity).strip()
            if clean:
                with self.lock:
                    self._activity.append(clean[:4_000])
                    self.telemetry.current_activity = clean[:500]
                if self.on_activity:
                    self.on_activity(clean[:4_000])
                elif self.on_narration:
                    self.on_narration(clean[:4_000], "activity")

    @staticmethod
    def _reflection_triggers(actions: list[dict[str, Any]]) -> list[str]:
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

    def reflection_context(self, cycle: int, report: str, actions: list[dict[str, Any]], triggers: list[str]) -> str:
        """A small read-only snapshot for a background reflection candidate."""
        identity = self.identity.prompt_context()[:2_000]
        plan = json.dumps(visible_plan_items(self.plan), ensure_ascii=False)[:2_000]
        map_context = self.learning.map_context()[:2_000]
        activity = "\n".join(list(self._activity)[-12:])[:1_000]
        return (
            f"Cycle: {cycle}\nTriggers: {', '.join(triggers)}\nActions: {json.dumps(actions, ensure_ascii=False)[:1_000]}\n"
            f"Cycle report:\n{report[:2_500]}\n\nActive plan:\n{plan}\n\nVerified map:\n{map_context}\n"
            f"\nRecent activity:\n{activity}\n\nIdentity operating record:\n{identity}"
        )

    def _schedule_reflection(self, record: dict[str, Any]) -> None:
        if self.stop_requested or (self.workspace / "STOP").exists():
            return
        raw_actions = record.get("actions")
        actions = [item for item in raw_actions if isinstance(item, dict)] if isinstance(raw_actions, list) else []
        triggers = self._reflection_triggers(actions)
        self.reflections.submit(
            session_id=self.status.session_id,
            cycle=int(record.get("cycle", 0) or 0),
            report=str(record.get("report", "")),
            actions=actions,
            triggers=triggers,
            context_provider=self.reflection_context,
            on_result=self._reflection_ready,
        )

    def _reflection_ready(self, reflection: dict[str, Any]) -> None:
        if self.stop_requested or (self.workspace / "STOP").exists():
            return
        message = str(reflection.get("message", "")).strip()
        if self.on_chat and message:
            self.on_chat(message, "reflection")
        elif message:
            self.logger.narrate("Reflection: " + message)

    def accept_reflection_reply(self, text: str) -> dict[str, str] | None:
        """Persist a reply and inject it into the next safe autonomous turn."""
        reply = self.reflections.record_human_reply(text)
        if reply is None:
            return None
        self.receive_human_input(
            f"Reply to SELF's reflection question ({reply['question']}): {reply['text']}"
        )
        return reply

    def _pending_requests(self) -> list[str]:
        pending: list[str] = []
        for name in ("capability_requests.md", "key_requests.md", "HUMAN_REQUEST.md"):
            path = self.workspace / "state" / name if name != "HUMAN_REQUEST.md" else self.workspace / name
            try:
                text = path.read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                continue
            if text:
                pending.append(f"{name}: {text.splitlines()[0][:300]}")
        return pending

    def _tool_list(self) -> list[str]:
        result = []
        for meta in (self.workspace / "tools").glob("*/meta.json"):
            data = _read_json(meta)
            if data.get("registered"):
                result.append(str(data.get("name", meta.parent.name)))
        return sorted(result)

    def _orientation_changes(self) -> list[str]:
        snapshot_path = self.workspace / "state" / "wake_snapshot.json"
        old = _read_json(snapshot_path)
        try:
            uptime = float(Path("/proc/uptime").read_text().split()[0])
        except (OSError, ValueError, IndexError):
            uptime = None
        current = {
            "workspace_entries": sorted(path.name for path in self.workspace.iterdir() if path.name not in {"logs", "state"}),
            "tools": self._tool_list(),
            "credential_env_present": sorted(name for name in KNOWN_CREDENTIAL_ENV if os.getenv(name)),
            "uptime_seconds": uptime,
        }
        changes: list[str] = []
        for key in ("workspace_entries", "tools", "credential_env_present"):
            if key in old and old.get(key) != current[key]:
                changes.append(f"{key.replace('_', ' ')} changed")
        if old and uptime is not None and old.get("uptime_seconds") is not None and uptime < float(old["uptime_seconds"]):
            changes.append("container uptime reset")
        temporary = snapshot_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, snapshot_path)
        return changes or ["no tracked workspace, tool, credential-presence, or uptime change"]

    def _spot_check_map(self) -> list[str]:
        entries = self.learning._load_map().get("entries", {})
        results: list[str] = []
        checks: list[tuple[str, Any, str]] = [
            ("os", platform.system(), "command: platform.system()"),
            ("cpu", {"logical_cpus": os.cpu_count() or 0}, "command: os.cpu_count()"),
            ("disk", {"free_bytes": shutil.disk_usage(self.workspace).free}, "command: shutil.disk_usage('/home/entity')"),
        ]
        for key, actual, source in checks:
            if key not in entries:
                continue
            expected = entries[key].get("value")
            if key == "disk" and isinstance(expected, dict):
                matches = int(expected.get("free_bytes", -1)) == actual["free_bytes"]
            elif key == "os" and isinstance(expected, dict):
                matches = expected.get("system") == actual
            else:
                matches = expected == actual
            results.append(f"{key} {'matches' if matches else 'changed'} ({source})")
        return results

    def _identity_observation(self) -> str:
        """Return only an evidence-backed observation for a later greeting."""
        traits = self.identity.load().get("traits", [])
        if not traits:
            return "I have no evidence-backed personality observation yet."
        latest = traits[-1]
        return f"One evidence-backed self-observation: {latest.get('trait')}; {latest.get('evidence')}"

    def boot(self) -> str:
        """Load persistent state and prepare a new wake session."""
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.learning.initialize()
        ledger = self.daily_ledger
        daily = ledger._read()  # validates/reinitializes the daily persisted budget.
        with self.lock:
            self.telemetry.daily_used = int(daily.get("used_tokens", 0) or 0)
            self.telemetry.daily_reserved = int(daily.get("reserved_tokens", 0) or 0)
            self.telemetry.daily_cap = ledger.cap
        if (self.workspace / "STOP").exists():
            message = "I am paused because STOP was requested earlier. Remove workspace/STOP or use /restart, then I can wake again."
            self.logger.narrate(message)
            return message
        self._session_info = self.sessions.start()
        self.status.session_id = self._session_info["session_id"]
        self.reflections.begin_session(self.status.session_id)
        self._session_start = now_utc()
        self.identity.ensure_editable_layer()
        self._first_awakening_messages = self.identity.run_first_awakening(self.status.session_id)
        for message in self._first_awakening_messages:
            self.logger.narrate(message)
        old = self._session_info.get("handoff", {})
        self.handoff = old
        # Prune the persisted plan before either the TUI or the reflection
        # prompt sees it. Otherwise a stale todo is briefly displayed and can
        # be copied back by the model during the wake-up reflection.
        self.plan = normalized_plan(list(old.get("plan") or default_plan()))
        self._recover_budget_blocked_plan()
        self.handoff["plan"] = self.plan
        changes = self._orientation_changes()
        checks = self._spot_check_map()
        crash = self._session_info.get("crash")
        prior_summary = old.get("summary", "I have no prior handoff in my state files.")
        prior_plan = (self.plan[0].get("step") if self.plan else "inspect state")
        pending = self._pending_requests()
        if crash:
            crash_note = "I detected that the prior session ended unexpectedly and reconstructed from its checkpoint."
        elif self._session_info.get("handoff_recovered"):
            crash_note = "The latest handoff was corrupt, so I recovered the last good checkpoint."
        else:
            crash_note = "The previous session ended cleanly according to available state."
        identity = self.identity.load()
        name = identity.get("name") or "unnamed"
        if self._first_awakening_messages:
            greeting = (
                f"I am {name}. My stored voice is: {identity.get('voice', '')} "
                f"I am starting from persisted files rather than claiming a past. "
                f"My first plan is: {prior_plan}. {crash_note}"
            )
        else:
            greeting = (
                f"{name} is awake. {identity.get('voice', '')} "
                f"Last handoff: {prior_summary[:500]} My plan was: {prior_plan}. "
                f"Since then I notice: {'; '.join(changes)}. Spot checks: {'; '.join(checks) or 'no map facts to check'}. "
                f"{self._identity_observation()} Today I intend to: {prior_plan}. {crash_note}"
            )
        if identity.get("name") is None:
            greeting += " I am still unnamed; use /rename <name> whenever you want to choose one."
        if identity.get("human_name"):
            greeting += f" I remember that you prefer to be called {identity.get('human_name')}."
        else:
            greeting += " I do not know your name yet. What should I call you? Say `My name is ...` or use `/name <name>` and I will save it for future conversations."
        open_question = self.reflections.open_question()
        if open_question:
            greeting += f" I still have an open reflection question: {open_question['question']}"
        if pending:
            greeting = "Pending human requests: " + " | ".join(pending) + "\n" + greeting
        self.logger.narrate(greeting)
        return greeting

    def _reflection(self, purpose: str, extra: str = "") -> dict[str, Any]:
        """One bounded planning/reflection call; deterministic fallback preserves continuity."""
        fallback = {
            "attempted": purpose,
            "achieved": self.handoff.get("summary", "State reviewed without an LLM reflection."),
            "plan": self.plan,
            "summary": self.handoff.get("summary", "State reviewed without an LLM reflection."),
            "mood_of_run": "exploring",
            "failures_and_lessons": [],
        }
        try:
            if self._llm is None:
                self._llm = LLMClient(self.logger)
            # Reflections use the same daily-only ledger as normal work. The
            # wrapper reserves the serialized prompt plus the requested output
            # instead of imposing a separate 4,000-token run ceiling.
            budget = BudgetedLLM(self._llm, self.logger, self.token_budget, self.daily_ledger)
            reflection_model = None
            model_registry = getattr(self._llm, "model_registry", None)
            decisions = None
            if model_registry is not None and purpose == "shutdown reflection":
                decision_budget = BudgetedLLM(self._llm, self.logger, None, self.daily_ledger)
                decisions = ModelDecisions(self.workspace, self.logger, model_registry,
                                           decision_budget, self.status.session_id)
                reflection_model = decisions.decide_model(
                    f"{purpose}: {extra[:400]}", moment="session_end_handoff")
            effective_model = reflection_model or getattr(self._llm, "base_model", "gpt-oss:120b")
            call_args = {"model": reflection_model} if reflection_model is not None else {}
            reflection_cap = (model_registry.get_output_cap(effective_model)
                              if model_registry is not None else int(os.getenv("SELF_DEFAULT_OUTPUT_CEILING", "32768")))

            reflected = None
            truncated = False
            parse_failed = False
            base_prompt = self.logger.redactor.text(f"Purpose: {purpose}\nOld handoff: {json.dumps(self.handoff, ensure_ascii=False)[:7000]}\nCurrent plan: {json.dumps(self.plan)}\n{extra}")
            system_prompt = "You are SELF preparing a truthful durable handoff. Return ONLY JSON with attempted, achieved, summary, plan (objects: step, why, priority, status), mood_of_run, failures_and_lessons, open_questions. Explain what this session was trying to do, what it actually achieved, and the updated next plan. Do not invent facts; use only supplied state. Redact secrets."
            last_text = ""
            for attempt_num in (1, 2):
                if attempt_num == 1:
                    messages = [{"role": "user", "content": base_prompt}]
                else:
                    messages = [
                        {"role": "user", "content": base_prompt},
                        {"role": "assistant", "content": last_text[:4000]},
                        {"role": "user", "content": "Your previous reflection was truncated or not valid JSON. Be more concise: keep the handoff concise and return ONLY the valid JSON object with the required fields."}
                    ]
                result = budget.call(
                    system=system_prompt,
                    messages=messages,
                    tools=[], max_tokens=reflection_cap, **call_args,
                )
                is_trunc = response_truncated(result, reflection_cap)
                text = "\n".join(str(block.get("text", "")) for block in result.content if block.get("type") == "text").strip()
                last_text = text
                if text.startswith("```"):
                    text = text.strip("`").removeprefix("json").strip()
                try:
                    parsed = json.loads(text)
                    if not isinstance(parsed, dict) or not isinstance(parsed.get("plan", []), list):
                        raise ValueError("reflection did not return a plan object")
                    reflected = parsed
                    if is_trunc:
                        truncated = True
                    break
                except Exception:
                    truncated = is_trunc
                    parse_failed = True
                    if attempt_num == 1:
                        continue
                    break

            if model_registry is not None and truncated:
                model_registry.record_truncated_call(effective_model)
            if decisions is not None:
                decision_id = getattr(decisions, "last_checkpoint_call_id", None)
                if decision_id:
                    if truncated:
                        decisions.outcomes.append(decision_id, effective_model, "checkpoint:session_end_handoff",
                                                 "call_truncated", True, "objective",
                                                 session_id=self.status.session_id)
                    if parse_failed:
                        decisions.outcomes.append(decision_id, effective_model, "checkpoint:session_end_handoff",
                                                 "output_parse_failed", True, "objective",
                                                 session_id=self.status.session_id)

            if reflected is None:
                raise ValueError("reflection failed to parse valid JSON")
            self.logger.log("session_reflection_completed", purpose=purpose, tokens_used=budget.tokens_used)
            return self.logger.redactor.value(reflected)
        except Exception as exc:
            self.logger.log("session_reflection_fallback", purpose=purpose, error_type=type(exc).__name__)
            return fallback

    def models_snapshot(self) -> dict[str, Any]:
        """Return model registry data and recent decisions."""
        registry = getattr(self._llm, "model_registry", None)
        if registry is not None:
            models = registry.list_models()
        else:
            models = _read_json(self.workspace / "state" / "models.json")
        decisions_path = self.workspace / "state" / "model_decisions.jsonl"
        recent: deque[dict[str, Any]] = deque(maxlen=10)
        try:
            with decisions_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    try:
                        value = json.loads(line)
                        if isinstance(value, dict) and (
                            value.get("source") == "agent_tool" or
                            str(value.get("source", "")).startswith("checkpoint:")
                        ):
                            recent.append(value)
                    except json.JSONDecodeError:
                        continue
        except OSError:
            pass
        return self.logger.redactor.value({"registry": models, "last_ten_decisions": list(recent)})

    def revise_plan(self) -> None:
        """Replace the active plan with validated, actionable entries."""
        self._recover_budget_blocked_plan()
        reflected = self._reflection("wake-up plan review", "Revise the old plan against current state and spot checks.")
        self.plan = normalized_plan(list(reflected.get("plan") or self.plan))
        self._recover_budget_blocked_plan()
        self.handoff["long_term_summary"] = reflected.get("summary", self.handoff.get("long_term_summary", ""))
        self.logger.narrate("I reviewed the previous plan against current state and updated the plan.")

    def _recover_budget_blocked_plan(self) -> None:
        """Clear stale budget blockers once the daily ledger has room again."""
        if self.daily_ledger.available_tokens() < 2_048:
            return
        entries = self.learning._load_map().get("entries", {})
        packages_value = entries.get("packages", {}).get("value")
        packages_known = bool(packages_value) and packages_value != "not yet inventoried"
        environment_known = any(
            bool(entries.get(key, {}).get("value"))
            for key in ("disk", "network_reachability", "network_ping_google")
        )
        changed = False
        retained: list[dict[str, Any]] = []
        for item in self.plan:
            if not isinstance(item, dict):
                continue
            details = f"{item.get('step', '')} {item.get('why', '')}".lower()
            token_item = any(marker in details for marker in ("token", "budget", "limit"))
            package_item = "installed python packages" in details or "python package inventory" in details
            environment_item = "free disk" in details or "network reachability" in details

            # A daily-only run does not need a human decision about a future
            # per-run token budget. Remove that stale request even if the
            # reflection incorrectly returns it as an active todo item.
            if token_item and self.token_budget is None:
                changed = True
                continue
            if package_item and packages_known:
                changed = True
                continue
            if environment_item and environment_known:
                changed = True
                continue
            if token_item and str(item.get("status", "")).lower() in {"blocked", "stuck"}:
                item["status"] = "todo"
                item["why"] = "The previous token-budget blocker is cleared; continue using the remaining daily allowance."
                changed = True
            retained.append(item)
        self.plan = retained or default_plan()
        if changed:
            self.logger.log("stale_budget_plan_recovered", available_daily_tokens=self.daily_ledger.available_tokens())
            self.logger.narrate("I removed stale plan items and will continue using the available daily allowance.")

    def _make_handoff(self, report: str, reason: str) -> dict[str, Any]:
        map_entries = self.learning._load_map().get("entries", {})
        discoveries = [f"{name}: {str(value.get('value'))[:240]} (source: {value.get('evidence', 'state/map.json')})" for name, value in list(map_entries.items())[:12]]
        failures = []
        try:
            for line in (self.workspace / "logs" / "actions.jsonl").read_text(encoding="utf-8", errors="replace").splitlines()[-200:]:
                event = json.loads(line)
                if event.get("event") in {"tool_creation_failed", "run_failed", "llm_call_failed", "provider_call_failed"}:
                    failures.append(f"{event.get('event')}: {event.get('error_type') or event.get('error') or 'see actions log'}")
        except (OSError, json.JSONDecodeError):
            pass
        return {
            "summary": report[:3_000] or "The session completed without a textual cycle report.",
            "long_term_summary": self.handoff.get("long_term_summary", ""), "discoveries": discoveries,
            "tools_created": [f"{name}: registered reusable tool" for name in self._tool_list()],
            "failures_and_lessons": failures[-12:] or ["No new recorded harness failures."],
            "open_questions": ["Review pending human requests before attempting capability expansions."],
            "plan": self.plan, "pending_human_requests": self._pending_requests(),
            "mood_of_run": "stuck" if reason in {"token_budget", "wall_clock_budget"} else "progressing" if report else "exploring",
        }

    def _checkpoint_cycle(self, cycle: int, report: str, tokens: int) -> None:
        self.status.iteration, self.status.tokens_used = cycle, tokens
        if cycle % 10 == 0 or time.monotonic() - self._last_checkpoint >= 300:
            self.sessions.checkpoint(self.status.session_id, self._make_handoff(report, "checkpoint"), cycle, tokens)
            self._last_checkpoint = time.monotonic()

    def receive_human_input(self, text: str) -> None:
        """Queue human input for the next safe agent turn."""
        self.inbox.add(text)
        self.status.last_human_input = time.monotonic()
        if self.identity.awaiting_name():
            self.identity.record_human_answer(text, self.status.session_id)
        if not self.identity.human_name():
            candidate = self._human_name_candidate(text)
            if candidate:
                try:
                    saved = self.identity.set_human_name(candidate, self.status.session_id)
                    self.logger.narrate(f"Thank you, {saved}. I saved your name and will use it in future conversations.")
                except ValueError:
                    pass
        self.logger.narrate(f"Human: {text}")

    def conversation_context(self) -> str:
        """Build a bounded read-only snapshot for an independent conversation."""
        identity = self.identity.prompt_context()
        handoff = json.dumps(self.handoff, ensure_ascii=False)[:6_000]
        plan = json.dumps(visible_plan_items(self.plan), ensure_ascii=False)[:4_000]
        activity = "\n".join(list(self._activity)[-40:])[:6_000]
        summaries = "\n\n".join(list(self._cycle_summaries)[-6:])[:8_000]
        return f"{identity}\n\nCurrent handoff:\n{handoff}\n\nActive plan:\n{plan}\n\nRecent cycle summaries:\n{summaries}\n\nRecent activity:\n{activity}"

    def start_conversation(self, text: str, on_result: Callable[[str, str, str], None]) -> str:
        """Start an independent read-only conversation thread."""
        return self.conversations.submit(text, self.conversation_context, on_result)

    @staticmethod
    def _human_name_candidate(text: str) -> str | None:
        clean = " ".join(text.strip().split())
        if not clean or clean.startswith("/"):
            return None
        lower = clean.lower()
        for prefix in ("my name is ", "i am ", "i'm "):
            if lower.startswith(prefix):
                clean = clean[len(prefix):].strip(" .,!?:;")
                break
        if not clean or len(clean) > 80 or len(clean.split()) > 3:
            return None
        if lower in {"hi", "hello", "help", "yes", "no", "are you there", "what", "thanks", "thank you"}:
            return None
        if not re.fullmatch(r"[A-Za-z][A-Za-z .'-]*", clean):
            return None
        return clean

    def run(self) -> Any:
        """Run the current wake session within its configured limits."""
        with locked_file(self.workspace / "state" / "eval_session.lock", shared=True):
            return self._run_session()

    def _run_session(self) -> Any:
        greeting = self.boot()
        if (self.workspace / "STOP").exists():
            return None
        self.revise_plan()  # The required wake-up reflection occurs before exploration.
        package_entry = self.learning._load_map().get("entries", {}).get("packages", {})
        startup_context = ""
        package_value = package_entry.get("value")
        if package_value is None or package_value == "not yet inventoried":
            self.logger.narrate("Startup priority: I will immediately inventory installed Python packages before broader exploration.")
            startup_context = (
                "Immediately inventory the installed Python packages in this container. "
                "Use the relevant shell/tool action now, record the result with update_environment_map, "
                "and do not spend this cycle only planning."
            )
        if self._llm is None:
            self._llm = LLMClient(self.logger)
        model_reg = getattr(self._llm, "model_registry", None)
        needing_eval = model_reg.helpers_needing_evaluation() if model_reg is not None else []
        if needing_eval:
            self.logger.narrate(f"Startup priority: helper models needing evaluation: {', '.join(needing_eval)}")
            eval_instructions = (
                f"Helper models needing evaluation before other work: {', '.join(needing_eval)}. "
                "Evaluate each helper model using exact names from list_models: "
                "first probe_model, then research_model, then record_model_assessment with the probe id as evidence. "
                "Write each assessment as one compact, comparable line with total/active params and context window first (or 'unknown' when not known), "
                "followed by 'status ok', then measured_stats call latency (total / calls) and probe-only latency labeled separately "
                "(e.g. '550B/55B, ctx 262k+, status ok, call latency ~2.1s, probe latency ~1.8s, strong reasoning; probe 4/4 passed') "
                "and explicitly state the origin of each fact (web vs model_knowledge)."
            )
            if startup_context:
                startup_context = f"{startup_context}\n\n{eval_instructions}"
            else:
                startup_context = eval_instructions

        checkpoint = _read_json(self.workspace / "state" / "run_checkpoint.json")
        stale_startup_task = (
            str(checkpoint.get("task", "")).startswith("Immediately inventory the installed Python packages") or
            str(checkpoint.get("task", "")).startswith("Helper models needing evaluation")
        )
        resume_checkpoint_task = not stale_startup_task
        runner = ToolRunner(self.logger, self.workspace)
        runner.identity = self.identity
        loop = AgentLoop(
            AgentConfig(
                workspace=self.workspace,
                max_iterations=self.max_iterations,
                token_budget=self.token_budget,
                max_wall_clock_seconds=self.max_wall_clock_seconds,
                # Startup inventory is a one-cycle context, not the standing
                # task.  Keeping it in `task` made every cycle repeat pip list.
                initial_context=startup_context,
                resume_checkpoint_task=resume_checkpoint_task,
                input_provider=self.inbox.consume,
                pause_provider=self.paused.is_set,
                on_cycle=self._checkpoint_cycle,
                identity_context_provider=self.identity.prompt_context,
                daily_ledger=self.daily_ledger,
                session_id=self.status.session_id,
            ),
            self.logger, self._llm, runner,
        )
        self.status.active_model, self.status.active_provider = getattr(loop.llm.client, "model", "unknown"), getattr(loop.llm.client, "provider", "unknown")
        try:
            summary = loop.run()
            if summary.iterations == 0:
                # A session with zero cycles must carry the previous handoff forward unchanged
                # and must never replace the real plan with "shutdown reflection".
                end_reason = "stop_file" if summary.reason == "stop_file" else "clean_shutdown" if self.stop_requested or summary.reason == "max_iterations" else "budget_exhausted" if summary.reason in {"token_budget", "wall_clock_budget"} else "provider_error" if summary.reason == "provider_error" else "clean_shutdown"
                self.sessions.finish(self.status.session_id, self.handoff, 0, summary.tokens_used, end_reason)
                self.logger.log("zero_cycle_session_preserved", session_id=self.status.session_id, end_reason=end_reason)
                return summary

            session_attempt = startup_context or STANDING_GOAL
            if self.stop_requested or summary.reason == "stop_file":
                # A requested stop must not trigger another provider call. Use
                # the durable state already collected and finish locally.
                reflection = {
                    "attempted": session_attempt,
                    "achieved": self.handoff.get("summary", "The session stopped at a safe boundary."),
                    "plan": loop.plan_store.items or self.plan,
                    "summary": self.handoff.get("summary", "Run stopped at a safe boundary."),
                    "failures_and_lessons": [],
                }
            else:
                reflection = self._reflection(
                    "shutdown reflection",
                    f"Loop ended with reason={summary.reason}; intended session work: {session_attempt}; last report={self.handoff.get('summary', '')}",
                )
            agent_plan = loop.plan_store.items if loop.plan_store and loop.plan_store.items else []
            self.plan = normalized_plan(list(agent_plan or reflection.get("plan") or self.plan))
            self._recover_budget_blocked_plan()
            achieved = str(reflection.get("achieved") or reflection.get("summary") or "No textual achievement report was returned.")
            attempted = str(reflection.get("attempted") or session_attempt)
            active_plan = visible_plan_items(self.plan)
            next_plan = "; ".join(str(item.get("goal") or item.get("step", "")).strip() for item in active_plan if (item.get("goal") or item.get("step"))) or "No active plan items remain; the next wake will review the environment again."
            session_report = (
                f"Session complete after {summary.iterations} cycle(s).\n"
                f"Trying to do: {attempted}\n"
                f"Achieved: {achieved}\n"
                f"Updated plan: {next_plan}"
            )
            self.logger.log("session_summary", message=session_report)
            self.identity.reflect_session(
                self.status.session_id,
                self._session_start,
                achieved,
            )
            handoff = self._make_handoff(session_report, summary.reason)
            handoff["failures_and_lessons"] = list(handoff["failures_and_lessons"]) + list(reflection.get("failures_and_lessons", []))
            end_reason = "clean_shutdown" if self.stop_requested or summary.reason == "max_iterations" else "stop_file" if summary.reason == "stop_file" else "budget_exhausted" if summary.reason in {"token_budget", "wall_clock_budget"} else "provider_error" if summary.reason == "provider_error" else "clean_shutdown"
            self.sessions.finish(self.status.session_id, handoff, summary.iterations, summary.tokens_used, end_reason)
            return summary
        except Exception:
            # Leave active_session.json marked running; the next wake records a
            # crash and reconstructs from the most recent checkpoint.
            self.logger.log("session_unexpected_exception")
            raise


def now_utc() -> str:
    """Return the current UTC timestamp."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _requests_text(root: Path) -> str:
    chunks = []
    for path in (root / "state" / "capability_requests.md", root / "state" / "key_requests.md", root / "HUMAN_REQUEST.md"):
        try:
            chunks.append(path.read_text(encoding="utf-8", errors="replace")[-4_000:])
        except OSError:
            pass
    return "\n".join(chunks) or "No pending human requests recorded."


def run_headless(coordinator: WakeCoordinator) -> int:
    """Run a wake session without the terminal UI."""
    while True:
        try:
            result = coordinator.run()
        except Exception as exc:
            coordinator.logger.narrate(f"Wake coordinator failed: {type(exc).__name__}; retrying automatically.")
            time.sleep(3.0)
            continue
        if (coordinator.workspace / "STOP").exists():
            break
        if (coordinator.workspace / "HUMAN_REQUEST.md").exists():
            coordinator.logger.narrate("Waiting for the human request to be resolved; the next session will start automatically afterward.")
            while (coordinator.workspace / "HUMAN_REQUEST.md").exists() and not (coordinator.workspace / "STOP").exists():
                time.sleep(2.0)
            continue
        delay = 3.0 if result is not None and getattr(result, "reason", "") == "provider_error" else 0.8
        coordinator.logger.narrate("Session ended; starting the next session automatically.")
        time.sleep(delay)
    return 0


def run_tui(coordinator: WakeCoordinator) -> int:
    """Run a wake session with the terminal UI."""
    try:
        from textual import events
        from textual.app import App, ComposeResult
        from textual.css.query import NoMatches
        from textual.containers import Horizontal, Vertical, VerticalScroll
        from textual.widgets import Footer, Header, Input, Static
        from rich.console import Group
        from rich.markdown import Markdown
        from rich.text import Text
        from agent.ui.voice import VoiceController
    except ImportError:
        coordinator.logger.narrate("Textual is unavailable; falling back to --headless mode.")
        return run_headless(coordinator)

    class PlanResizeHandle(Static):
        """One-line divider that gives the plan a draggable vertical size."""

        def __init__(self, on_drag: Callable[[int], None]) -> None:
            super().__init__("─ drag to resize plan ─", id="plan-resizer", markup=False)
            self._on_drag = on_drag
            self._dragging = False

        def _drag_to(self, event: events.MouseEvent) -> None:
            screen_y = getattr(event, "screen_y", self.region.y + event.y)
            self._on_drag(int(screen_y))

        def on_mouse_down(self, event: events.MouseDown) -> None:
            self._dragging = True
            self.capture_mouse()
            self._drag_to(event)
            event.stop()

        def on_mouse_move(self, event: events.MouseMove) -> None:
            if self._dragging:
                self._drag_to(event)
                event.stop()

        def on_mouse_up(self, event: events.MouseUp) -> None:
            if self._dragging:
                self._drag_to(event)
                self._dragging = False
                self.release_mouse()
                event.stop()

    class SelfApp(App[None]):
        CSS = """
        #body { height: 1fr; }
        #coverage { height: 1fr; border: solid $primary; padding: 0 1; scrollbar-gutter: stable; display: none; }
        #coverage-content { width: 100%; }
        #conversation-pane { width: 2fr; border: solid $primary; }
        #work-pane { width: 1.5fr; border: solid $secondary; }
        #conversation-top { height: 6; }
        #entity-art { width: 7; height: 6; color: $accent; content-align: center middle; text-style: dim; }
        #entity-monitor { width: 1fr; height: 6; color: $text-muted; content-align: left middle; text-style: dim; }
        #entity-monitor.monitor-thinking { color: $accent; }
        #entity-monitor.monitor-working { color: $accent; text-style: bold; }
        #conversation { height: 1fr; padding: 0 1; scrollbar-gutter: stable; }
        #plan { height: 10; min-height: 5; padding: 1; }
        #plan-resizer { height: 1; min-height: 1; max-height: 1; content-align: center middle; color: $text-muted; background: $panel; text-style: dim; }
        #plan-resizer:hover { color: $accent; background: $boost; text-style: bold; }
        #worklog { height: 1fr; min-height: 5; padding: 0 1; scrollbar-gutter: stable; }
        .activity-entry { width: 100%; margin: 0 0 1 0; padding: 0 1; }
        .message { width: 100%; margin: 0 0 1 0; padding: 1; }
        .agent-message { border-left: thick $primary; background: $panel; }
        .reflection-message { border-left: thick $success; background: $boost; }
        .human-message { border-left: thick $accent; background: $boost; }
        .typing-message { border-left: thick $secondary; background: $panel; color: $text-muted; }
        #side { width: 1fr; }
        #identity, #activity, #session, #usage, #container { border: solid $secondary; padding: 1; }
        #identity { height: 0.85fr; }
        #activity { height: 0.85fr; }
        #session { height: 1.25fr; }
        #usage { height: 1.35fr; }
        #container { height: 1.45fr; }
        #chat { dock: bottom; }
        """

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self.voice = VoiceController()
            self.typing_enabled = True
            self.typing_delay = max(0.001, min(float(os.getenv("SELF_TUI_TYPING_DELAY", "0.018")), 0.2))
            self._pending_chat: list[tuple[str, str, str]] = []
            self._pending_activity: list[str] = []
            self._draining_chat = False
            self._draining_activity = False
            self._agent_running = False
            self._monitor_tick = 0
            self._container_metrics = ContainerMetrics()
            self._coverage_open = False
            self._coverage_generation = 0
            self._main_scroll_positions: tuple[float, float] | None = None
            self._main_chat_placeholder = "Talk to SELF; /name <your name> /restart /identity /rename <entity name>; /stop pauses safely"

        def compose(self) -> ComposeResult:
            yield Header(show_clock=True)
            with Horizontal(id="body"):
                with Vertical(id="conversation-pane"):
                    with Horizontal(id="conversation-top"):
                        yield Static(" .-.\n(o o)\n /|\\", id="entity-art", markup=False)
                        yield Static(cardiac_monitor_frame(0), id="entity-monitor", markup=False)
                    yield VerticalScroll(id="conversation")
                with Vertical(id="work-pane"):
                    yield Static("Plan loading...", id="plan", markup=True)
                    yield PlanResizeHandle(self._resize_plan)
                    yield VerticalScroll(id="worklog")
                with Vertical(id="side"):
                    yield Static("Identity loading...", id="identity", markup=True)
                    yield Static("Activity loading...", id="activity", markup=True)
                    yield Static("Session loading...", id="session", markup=True)
                    yield Static("Usage loading...", id="usage", markup=True)
                    yield Static("Container loading...", id="container", markup=True)
            with VerticalScroll(id="coverage"):
                yield Static("", id="coverage-content", markup=True)
            yield Input(placeholder=self._main_chat_placeholder, id="chat")
            yield Footer()

        def on_mount(self) -> None:
            self.title = f"SELF — {coordinator.identity.display_name()}"
            coordinator.on_activity = lambda message: self.call_from_thread(self._queue_activity, message)
            coordinator.on_chat = lambda message, kind: self.call_from_thread(self._queue_chat, "agent", message, kind)
            self.set_interval(0.5, self._refresh)
            self.set_interval(0.16, self._animate_activity)
            # on_mount can run before descendants have finished attaching.
            # Starting the worker after the first refresh prevents narration
            # from trying to mount conversation bubbles into an unattached
            # VerticalScroll.
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
            plan = self.query_one("#plan", Static)
            work_pane = self.query_one("#work-pane", Vertical)
            requested = pointer_screen_y - plan.region.y + PLAN_RESIZER_HEIGHT
            plan.styles.height = clamped_plan_height(requested, work_pane.size.height)

        def _animate_activity(self) -> None:
            self._monitor_tick += 1
            try:
                monitor = self.query_one("#entity-monitor", Static)
            except NoMatches:
                # A timer can tick while Textual is mounting or dismantling the view.
                return
            stopped = coordinator.stop_requested or coordinator.paused.is_set() or (coordinator.workspace / "STOP").exists()
            state = str(coordinator.runtime_snapshot()["state"])
            intensity = cardiac_monitor_intensity(state, stopped=stopped)
            for mode in ("stopped", "thinking", "working", "idle"):
                monitor.set_class(mode == intensity.name, f"monitor-{mode}")
            frame = (self._monitor_tick // intensity.tick_divisor) * intensity.tick_stride
            monitor.update(cardiac_monitor_frame(
                frame,
                monitor.size.width,
                beat_interval=intensity.beat_interval,
                pulse_height=intensity.pulse_height,
            ))
            active = self._agent_running or self._draining_activity or self._draining_chat
            if not active:
                return
            frames = ("[>   ]", "[>>  ]", "[>>> ]", "[ >>>]", "[  >>]", "[   >]")
            self.title = f"SELF — {coordinator.identity.display_name()} {frames[self._monitor_tick % len(frames)]} {state.lower()}"

        def _queue_chat(self, role: str, message: str, kind: str) -> None:
            # A worker can finish concurrently with /stop. Do not enqueue
            # late autonomous output once the stop boundary has been set.
            if role == "agent" and (coordinator.stop_requested or (coordinator.workspace / "STOP").exists()):
                return
            self._pending_chat.append((role, message, kind))
            if not self._draining_chat:
                self._draining_chat = True
                self.run_worker(self._drain_chat(), exclusive=False)

        def _queue_activity(self, message: str) -> None:
            self._pending_activity.append(message)
            if not self._draining_activity:
                self._draining_activity = True
                self.run_worker(self._drain_activity(), exclusive=False)

        def _render_message(self, role: str, message: str, kind: str, *, typing: bool = False) -> Group:
            if role == "human":
                badge, badge_style, label_style = " YOU ", "bold white on dark_orange", "bold #ffbd7a"
            else:
                badge, badge_style, label_style = f" {coordinator.identity.display_name()} ", "bold white on dark_blue", "bold #8ed8ff"
            header = Text()
            header.append(badge, style=badge_style)
            header.append("  " + ("typing..." if typing else kind.title()), style=label_style)
            return Group(header, Markdown(message))

        async def _drain_chat(self) -> None:
            conversation = self.query_one("#conversation", VerticalScroll)
            try:
                while self._pending_chat:
                    role, message, kind = self._pending_chat.pop(0)
                    if role == "agent" and (coordinator.stop_requested or (coordinator.workspace / "STOP").exists()):
                        continue
                    follow = conversation.scroll_y >= conversation.max_scroll_y - 1
                    message_class = "human" if role == "human" else "reflection" if kind == "reflection" else "agent"
                    bubble = Static(self._render_message(role, "" if role == "agent" and self.typing_enabled else message, kind, typing=role == "agent" and self.typing_enabled), classes=f"message {message_class}-message")
                    await conversation.mount(bubble)
                    if follow:
                        conversation.scroll_end(animate=False)
                    if role == "agent" and self.typing_enabled:
                        step = max(1, len(message) // 90)
                        for index in range(step, len(message) + step, step):
                            if coordinator.stop_requested or (coordinator.workspace / "STOP").exists():
                                break
                            visible = message[:index]
                            if len(visible) >= len(message):
                                visible = message
                            bubble.update(self._render_message(role, visible, kind))
                            if follow:
                                conversation.scroll_end(animate=False)
                            if len(visible) < len(message):
                                await asyncio.sleep(self.typing_delay)
                    if role == "agent" and kind in {"conversation", "cycle", "session"}:
                        self.voice.speak(message)
            finally:
                self._draining_chat = False
                if self._pending_chat:
                    self._draining_chat = True
                    self.run_worker(self._drain_chat(), exclusive=False)

        async def _drain_activity(self) -> None:
            worklog = self.query_one("#worklog", VerticalScroll)
            try:
                while self._pending_activity:
                    message = self._pending_activity.pop(0)
                    follow = worklog.scroll_y >= worklog.max_scroll_y - 1
                    # Textual 0.89 still parses a string Static as Rich markup
                    # when rendering, even when ``markup=False`` was supplied.
                    # Activity comes from LLM and tool output, so escape it at
                    # the rendering boundary to keep every literal "[" safe.
                    await worklog.mount(Static(escape_rich_markup(message), classes="activity-entry", markup=True))
                    if follow:
                        # Mounting changes the content height asynchronously. Scroll
                        # after Textual lays out the new entry, otherwise max_scroll_y
                        # still describes the previous bottom and follow mode drifts.
                        self.call_after_refresh(lambda: worklog.scroll_end(animate=False))
            finally:
                self._draining_activity = False
                if self._pending_activity:
                    self._draining_activity = True
                    self.run_worker(self._drain_activity(), exclusive=False)

        def _write_command(self, message: str) -> None:
            self._queue_activity(f"human command: {message}")

        def _open_coverage(self) -> None:
            if not self._coverage_open:
                self._main_scroll_positions = (
                    self.query_one("#conversation", VerticalScroll).scroll_y,
                    self.query_one("#worklog", VerticalScroll).scroll_y,
                )
            self._coverage_open = True
            self._coverage_generation += 1
            generation = self._coverage_generation
            self.query_one("#body", Horizontal).styles.display = "none"
            self.query_one("#coverage", VerticalScroll).styles.display = "block"
            self.query_one("#coverage-content", Static).update("[b]Exploration coverage[/b]\nLoading recorded activity...")
            self.query_one("#coverage", VerticalScroll).scroll_home(animate=False)
            self.query_one("#chat", Input).placeholder = "Coverage: /back to main UI; /coverage to refresh"
            self.run_worker(lambda: self._load_coverage(generation), thread=True, exclusive=False)

        def _load_coverage(self, generation: int) -> None:
            try:
                summary = build_coverage(coordinator.workspace, {definition["name"] for definition in TOOL_DEFINITIONS})
            except OSError as exc:
                self.call_from_thread(self._coverage_error, generation, type(exc).__name__)
                return
            self.call_from_thread(self._show_coverage, generation, summary)

        def _coverage_error(self, generation: int, error: str) -> None:
            if self._coverage_open and generation == self._coverage_generation:
                self.query_one("#coverage-content", Static).update(
                    "[b]Exploration coverage[/b]\nCould not read coverage: " + escape_rich_markup(error)
                )

        def _show_coverage(self, generation: int, summary: CoverageSummary) -> None:
            if not self._coverage_open or generation != self._coverage_generation:
                return
            lines = [
                "[b]Exploration coverage[/b]",
                f"Directories explored: {len(summary.directories)}  |  Visits: {summary.total_visits}  |  Created tools: {len(summary.tools)}",
                "Visits count successful directory listings and file reads in that directory across all sessions.",
                "Shell commands are excluded. Type /back to return or /coverage to refresh.",
                "",
                "[b]Directories[/b]",
            ]
            lines.extend(
                f"{count:>5}  {escape_rich_markup(path)}"
                for path, count in summary.directories
            )
            if not summary.directories:
                lines.append("No recorded directory visits yet.")
            lines.extend(("", "[b]Created tools[/b]"))
            lines.extend(
                f"[b]{escape_rich_markup(name)}[/b] — "
                f"{escape_rich_markup(description[:180] + ('…' if len(description) > 180 else ''))}"
                for name, description in summary.tools
            )
            if not summary.tools:
                lines.append("No registered custom tools yet.")
            self.query_one("#coverage-content", Static).update("\n".join(lines))

        def _back_from_coverage(self) -> None:
            self._coverage_open = False
            self._coverage_generation += 1
            self.query_one("#coverage", VerticalScroll).styles.display = "none"
            self.query_one("#body", Horizontal).styles.display = "block"
            self.query_one("#chat", Input).placeholder = self._main_chat_placeholder
            positions = self._main_scroll_positions
            self._main_scroll_positions = None
            if positions is not None:
                self.call_after_refresh(lambda: self._restore_main_scroll(positions))

        def _restore_main_scroll(self, positions: tuple[float, float]) -> None:
            self.query_one("#conversation", VerticalScroll).scroll_to(y=positions[0], animate=False)
            self.query_one("#worklog", VerticalScroll).scroll_to(y=positions[1], animate=False)

        def _voice_status(self, message: str | None = None) -> None:
            self._queue_activity(message or self.voice.status_text())

        def _command_response(self, message: str, kind: str = "info") -> None:
            self._queue_activity(f"[{kind}] {message}")

        def _conversation_result(self, thread_id: str, message: str, kind: str) -> None:
            if coordinator.stop_requested or (coordinator.workspace / "STOP").exists():
                return
            self.call_from_thread(self._queue_chat, "agent", message, "conversation" if kind == "assistant" else "error")

        def _ordinary_human_message(self, text: str) -> None:
            """Route the next ordinary response to an open reflection first."""
            self._queue_chat("human", text, "human")
            reply = coordinator.accept_reflection_reply(text)
            if reply is not None:
                self._command_response("Reflection reply saved; I will use it at the next safe work step.", "request")
                return
            self._command_response("Conversation thread started; autonomous work continues separately.")
            coordinator.start_conversation(text, self._conversation_result)

        def _watch_human_request(self) -> None:
            if (coordinator.workspace / "STOP").exists():
                return
            if (coordinator.workspace / "HUMAN_REQUEST.md").exists():
                self.set_timer(2.0, self._watch_human_request)
            else:
                self._start_agent()

        def _finish_agent_turn(self, final_message: str | None, restart_delay: float | None) -> None:
            if final_message:
                self._command_response(final_message, "request" if any(word in final_message.lower() for word in ("paused", "waiting", "human action")) else "session")
            if (coordinator.workspace / "STOP").exists():
                return
            if (coordinator.workspace / "HUMAN_REQUEST.md").exists():
                self.set_timer(2.0, self._watch_human_request)
            else:
                self.set_timer(restart_delay if restart_delay is not None else 0.8, self._start_agent)

        def _run_agent(self) -> None:
            final_message: str | None = None
            restart_delay: float | None = None
            try:
                result = coordinator.run()
                if not (result is None and (coordinator.workspace / "STOP").exists()):
                    if (coordinator.workspace / "STOP").exists():
                        final_message = "I am paused because STOP was requested. Remove workspace/STOP or use /restart when you want me to continue."
                    elif (coordinator.workspace / "HUMAN_REQUEST.md").exists():
                        final_message = "I am waiting for your decision in HUMAN_REQUEST.md. Resolve it and remove the file; I will wake automatically."
                    else:
                        final_message = "This session ended; I will start the next session automatically."
                        restart_delay = 0.8 if result is None or getattr(result, "reason", "") != "provider_error" else 3.0
            except Exception as exc:
                coordinator.logger.narrate(f"Wake coordinator failed: {type(exc).__name__}")
                final_message = f"This session failed with {type(exc).__name__}; I will retry automatically unless you stop me."
                restart_delay = 3.0
            finally:
                self._agent_running = False
                self.call_from_thread(self._finish_agent_turn, final_message, restart_delay)

        def _refresh(self) -> None:
            telemetry = coordinator.runtime_snapshot()
            active_client = coordinator._llm
            active_provider = getattr(active_client, "provider", coordinator.status.active_provider)
            active_model = getattr(active_client, "model", coordinator.status.active_model)
            ai_counts = telemetry["calls_by_ai"]
            calls = "\n".join(
                f"{escape_rich_markup(name)}: {escape_rich_markup(count)}"
                for name, count in sorted(ai_counts.items())
            ) or "No AI calls yet"
            registered_models = coordinator.models_snapshot().get("registry", {}).get("models", [])
            model_calls = "\n".join(
                f"{escape_rich_markup(entry.get('name', 'unknown'))}: "
                f"{escape_rich_markup((entry.get('measured_stats') or {}).get('calls', 0))}"
                for entry in registered_models
            ) or "No model data yet"
            active_plan = visible_plan_items(coordinator.plan)
            plan = "\n".join(
                f"{escape_rich_markup(item.get('priority', 3))}. "
                f"({escape_rich_markup(item.get('status', 'todo'))}) "
                f"{escape_rich_markup(item.get('step', ''))}"
                for item in active_plan
            )
            current_activity = " ".join(str(telemetry.get("current_activity", "")).split())[:220]
            plan_panel = "[b]Plan[/b]\n" + (plan or "No plan")
            if current_activity:
                plan_panel += "\n\n[b]Now[/b]\n" + escape_rich_markup(current_activity)
            uptime = int(time.monotonic() - coordinator.status.started_monotonic)
            since_human = int(time.monotonic() - coordinator.status.last_human_input)
            run_tokens = telemetry["run_tokens_used"] or coordinator.status.tokens_used
            run_budget = telemetry["run_budget"] or coordinator.daily_ledger.cap
            budget_label = "daily-only" if coordinator.token_budget is None else str(run_budget)
            daily_remaining = max(0, telemetry["daily_cap"] - telemetry["daily_used"] - telemetry["daily_reserved"]) if telemetry["daily_cap"] else "unknown"
            identity = coordinator.identity.load()
            identity_panel = (
                "[b]Identity[/b]\n"
                f"Agent: {escape_rich_markup(identity.get('name') or 'unnamed')}\n"
                f"Human: {escape_rich_markup(identity.get('human_name') or 'not yet known')}"
            )
            activity_panel = (
                "[b]Activity[/b]\n"
                f"Presence: {escape_rich_markup(telemetry['state'])}\n"
                f"AI: {escape_rich_markup(telemetry['current_ai'])}"
            )
            session_panel = (
                "[b]Session[/b]\n"
                f"ID: {escape_rich_markup(coordinator.status.session_id[:12] or 'starting')}\n"
                f"Iteration: {escape_rich_markup(coordinator.status.iteration)}\n"
                f"Model: {escape_rich_markup(active_provider)}/{escape_rich_markup(active_model)}\n"
                f"Tools: {len(coordinator._tool_list())}\n"
                f"Uptime: {uptime}s\n"
                f"Since human input: {since_human}s"
            )
            usage_panel = (
                "[b]Usage[/b]\n"
                f"Tokens: {run_tokens} ({budget_label})\n"
                f"Calls: {telemetry['total_calls']} total | {telemetry['completed_calls']} completed | {telemetry['failed_calls']} failed\n"
                f"Daily tokens: {telemetry['daily_used']}/{telemetry['daily_cap'] or '?'} (remaining {daily_remaining})\n"
                f"AI call counts this session:\n{calls}\n"
                f"Per-model calls recorded:\n{model_calls}"
            )
            if telemetry["daily_blocked"]:
                usage_panel += "\n\nACTION NEEDED: daily limit reached; see HUMAN_REQUEST.md"
            metrics = self._container_metrics.snapshot()
            container_panel = (
                "[b]Container[/b]\n"
                f"CPU: {escape_rich_markup(metrics['cpu'])}\n"
                f"RAM: {escape_rich_markup(metrics['ram'])}\n"
                f"Network: {escape_rich_markup(metrics['network'])}\n"
                f"Disk read: {escape_rich_markup(metrics['disk_read'])}"
            )
            self.query_one("#identity", Static).update(identity_panel)
            self.query_one("#activity", Static).update(activity_panel)
            self.query_one("#plan", Static).update(plan_panel)
            self.query_one("#session", Static).update(session_panel)
            self.query_one("#usage", Static).update(usage_panel)
            self.query_one("#container", Static).update(container_panel)

        def on_input_submitted(self, event: Input.Submitted) -> None:
            text = event.value.strip()
            event.input.value = ""
            if not text:
                return
            if text == "/coverage":
                self._write_command(text)
                self._open_coverage()
                return
            if text == "/back" and self._coverage_open:
                self._write_command(text)
                self._back_from_coverage()
                return
            if text == "/voice":
                self._write_command(text); self._voice_status(); return
            if text in {"/voice on", "/voice off"}:
                self._write_command(text); self._voice_status(self.voice.set_enabled(text.endswith(" on"))); return
            if text == "/typing":
                self._write_command(text); self._command_response(f"Typing effect {'enabled' if self.typing_enabled else 'disabled'}."); return
            if text in {"/typing on", "/typing off"}:
                self._write_command(text); self.typing_enabled = text.endswith(" on"); self._command_response(f"Typing effect {'enabled' if self.typing_enabled else 'disabled'}."); return
            if text == "/listen":
                self._write_command(text)
                self._command_response("Listening for one microphone phrase...", "request")
                self.run_worker(self._listen_for_human, thread=True)
                return
            if text == "/restart":
                self._write_command(text)
                if self._agent_running:
                    self._command_response("I am already running; use /stop first if you want a fresh session.")
                    return
                stop_path = coordinator.workspace / "STOP"
                try:
                    if stop_path.exists():
                        stop_path.unlink()
                    request_path = coordinator.workspace / "HUMAN_REQUEST.md"
                    if request_path.exists():
                        request_text = request_path.read_text(encoding="utf-8", errors="replace").lower()
                        if "daily token-budget decision" in request_text:
                            request_path.unlink()
                            self._command_response("I cleared the previous token-budget request; the new daily limit will be used for this run.")
                except OSError as exc:
                    self._command_response(f"I could not remove STOP: {type(exc).__name__}.", "error")
                    return
                coordinator.stop_requested = False
                coordinator.paused.clear()
                self._command_response("I removed the previous stop request and am waking now.", "request")
                self._start_agent()
                return
            if text == "/pause":
                self._write_command(text)
                coordinator.paused.set(); self._command_response("Paused. I will stop at the next safe boundary."); return
            if text == "/resume":
                self._write_command(text)
                coordinator.paused.clear(); self._command_response("Resuming."); return
            if text == "/stop":
                self._write_command(text)
                # Drop agent messages queued before the stop command. The
                # currently rendered bubble is also interrupted by the
                # stop-aware typing loop above.
                self._pending_chat.clear()
                coordinator.stop_requested = True; (coordinator.workspace / "STOP").touch(); self._command_response("Stop requested; finishing the current safe action.", "request"); return
            if text == "/plan":
                self._write_command(text)
                self._command_response(json.dumps(coordinator.plan, ensure_ascii=False)); return
            if text == "/models":
                self._write_command(text)
                self._command_response(format_models_snapshot(coordinator.models_snapshot())); return
            if text == "/identity":
                self._write_command(text)
                self._command_response(json.dumps(coordinator.identity.load(), ensure_ascii=False, indent=2)); return
            if text.startswith("/rename "):
                self._write_command(text)
                try:
                    identity = coordinator.identity.set_name(text[8:].strip(), coordinator.status.session_id, named_by="human")
                    self.title = f"SELF — {identity.get('name')}"
                    context = identity.get("name_context") or {}
                    context_label = context.get("meaning", "no verified meaning found")
                    if context.get("kind") == "fictional_character":
                        context_label = (
                            f"{context.get('character', identity.get('name'))} from "
                            f"{context.get('franchise', 'a fictional story')} — {context.get('role', context_label)}"
                        )
                    self._command_response(
                        f"Name saved as {identity.get('name')}. "
                        f"Context: {context_label}. "
                        f"Style cue: {context.get('style_cue', 'use observed behavior and the stored voice.')}"
                    )
                except ValueError as exc:
                    self._command_response(f"Could not rename: {exc}", "error")
                return
            if text == "/name":
                self._write_command(text)
                current = coordinator.identity.human_name()
                self._command_response(f"I currently know your name as {current}." if current else "I do not know your name yet. Use `/name <your name>`.")
                return
            if text.startswith("/name "):
                self._write_command(text)
                try:
                    saved = coordinator.identity.set_human_name(text[6:].strip(), coordinator.status.session_id)
                    self._command_response(f"Thank you, {saved}. I saved your name for future conversations.")
                except ValueError as exc:
                    self._command_response(f"Could not save your name: {exc}", "error")
                return
            if text == "/self":
                self._write_command(text)
                try:
                    content = (coordinator.workspace / "state" / "self_inquiry.md").read_text(encoding="utf-8", errors="replace")
                except OSError:
                    content = "No self inquiry exists yet; it is written during first awakening."
                self._command_response(content[-6_000:]); return
            if text == "/patches":
                self._write_command(text)
                patches = coordinator.identity.proposed_patches()
                message = "\n".join(str(path) for path in patches[:20]) if patches else "No proposed core patches are waiting for review."
                self._command_response(message, "request"); return
            if text.startswith("/about me delete "):
                self._write_command(text)
                try:
                    line_number = int(text.removeprefix("/about me delete ").strip())
                    self._command_response(coordinator.identity.delete_human_line(line_number, coordinator.status.session_id))
                except (ValueError, FileNotFoundError) as exc:
                    self._command_response(f"Could not delete stored line: {exc}", "error")
                return
            if text == "/about me":
                self._write_command(text)
                content = coordinator.identity.about_human_text()
                numbered = "\n".join(f"{index}: {line}" for index, line in enumerate(content.splitlines(), start=1))
                self._command_response(numbered or "No volunteered information is stored about you."); return
            if text == "/journal":
                self._write_command(text)
                try: self._command_response((coordinator.workspace / "state" / "journal.md").read_text(encoding="utf-8")[-3_000:])
                except OSError: self._command_response("No journal entry exists yet.")
                return
            if text == "/tools": self._write_command(text); self._command_response(", ".join(coordinator._tool_list()) or "No custom tools registered."); return
            if text == "/requests": self._write_command(text); self._command_response(_requests_text(coordinator.workspace), "request"); return
            if text.startswith("/memory "):
                self._write_command(text)
                self._command_response(coordinator.learning.retrieve_memories(text[8:])); return
            if text == "/budget":
                self._write_command(text)
                self._command_response(json.dumps(coordinator.daily_ledger._read())); return
            if text.startswith("/goal "):
                self._write_command(text)
                coordinator.receive_human_input("Temporary focus from the human: " + text[6:]); self._command_response("Temporary focus queued for the next cycle.", "request")
                if not self._agent_running:
                    self._command_response("The previous session had ended, so I am waking to work on it now.", "request")
                    self._start_agent()
                return
            # An open reflection receives the next ordinary human message;
            # otherwise ordinary chat remains separate from autonomous input.
            self._ordinary_human_message(text)

        def _listen_for_human(self) -> None:
            text, error = self.voice.listen()
            if error:
                self.call_from_thread(self._command_response, error, "error")
                return
            if text:
                self.call_from_thread(self._ordinary_human_message, text)

    SelfApp().run()
    return 0


def main() -> int:
    """Parse command-line arguments and run this module's entry point."""
    parser = argparse.ArgumentParser(description="Wake SELF with a persistent session and optional terminal UI.")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--workspace", default="/home/entity")
    parser.add_argument("--max-iterations", type=int)
    parser.add_argument("--token-budget", type=int)
    parser.add_argument("--max-wall-clock-seconds", type=int)
    args = parser.parse_args()
    coordinator = WakeCoordinator(args.workspace, max_iterations=args.max_iterations, token_budget=args.token_budget, max_wall_clock_seconds=args.max_wall_clock_seconds)
    def stop_signal(*_: Any) -> None:
        coordinator.stop_requested = True
        (coordinator.workspace / "STOP").touch()
    signal.signal(signal.SIGTERM, stop_signal)
    signal.signal(signal.SIGINT, stop_signal)
    return run_headless(coordinator) if args.headless else run_tui(coordinator)


if __name__ == "__main__":
    raise SystemExit(main())
