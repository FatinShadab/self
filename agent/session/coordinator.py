"""Headless wake session coordinator and session lifecycle management."""
from __future__ import annotations

import asyncio
from collections import deque
import json
import os
import platform
import re
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from agent.body.base import Body
from agent.body.container import ContainerBody
from agent.helper_models.model_decisions import ModelDecisions
from agent.identity.identity import IdentityStore
from agent.infra.event_log import EventLogger
from agent.infra.file_lock import locked_file
from agent.infra.hardening import DailyTokenLedger
from agent.infra.permission_broker import PermissionBroker
from agent.infra.audit_trail import AuditTrail
from agent.infra.stop_watcher import StopWatcher
from agent.learning.exploration_coverage import CoverageSummary, build_coverage
from agent.learning.learning import LearningStore
from agent.learning.plan import PlanStore
from agent.llm.llm import BudgetedLLM, LLMClient, response_truncated
from agent.runtime.loop import AgentConfig, AgentLoop, STANDING_GOAL
from agent.session.conversation import ConversationManager
from agent.session.reflection import ReflectionManager
from agent.session.session import HumanInbox, SessionStore, default_plan
from agent.session.version_check import verify_startup_code_version
from agent.tools.base_tools import ToolRunner

COMPLETED_PLAN_STATUSES = frozenset({
    "done", "complete", "completed", "achieved", "finished", "closed",
    "cancelled", "canceled", "dropped",
})


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


def visible_plan_items(plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return only active plan items for the live panel."""
    return [
        item for item in plan
        if isinstance(item, dict)
        and str(item.get("status", "todo")).strip().lower() not in COMPLETED_PLAN_STATUSES
    ]


def normalized_plan(plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only actionable plan entries in durable state."""
    active = visible_plan_items(plan)
    for it in active:
        g = str(it.get("goal") or it.get("step", "")).strip()
        it["goal"] = g
        it["step"] = g
    return active if active else default_plan()


def format_starting_plan(starting_plan: list[dict[str, Any]], session_id: str = "") -> str:
    """Render the session starting plan as clean markdown."""
    if not starting_plan:
        return "No starting plan recorded for this session yet."

    session_label = f" (Session `{session_id[:12]}`)" if session_id else ""
    lines = [
        f"**Starting Plan / Targets{session_label}**",
        "",
        "*This was the plan when this session started:*",
        "",
    ]
    for idx, item in enumerate(starting_plan, 1):
        if not isinstance(item, dict):
            continue
        step = str(item.get("goal") or item.get("step", "")).strip()
        status = str(item.get("status", "todo")).strip().lower()
        lines.append(f"{idx}. ({status}) {step}")
        why = str(item.get("why", "")).strip()
        if why:
            lines.append(f"   *Why:* {why}")
    return "\n".join(lines)


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
    """Live, non-secret runtime facts used by the presence panel."""

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
        configured_wall_clock = max_wall_clock_seconds if max_wall_clock_seconds is not None else int(os.getenv("SELF_MAX_WALL_CLOCK_SECONDS", "0"))
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
            self.workspace, self.logger, self.daily_ledger, llm_client,
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

    def _checkpoint_cycle(self, cycle: int, report: str, tokens: int) -> None:
        self.status.iteration, self.status.tokens_used = cycle, tokens
        with self.lock:
            self.plan_store.load()
            if self.plan_store.items:
                self.plan = list(self.plan_store.items)
        if cycle % 10 == 0 or time.monotonic() - self._last_checkpoint >= 300:
            self.sessions.checkpoint(self.status.session_id, self._make_handoff(report, "checkpoint"), cycle, tokens)
            self._last_checkpoint = time.monotonic()

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
        elif event in {"plan_updated", "plan_unchanged"}:
            with self.lock:
                self.plan_store.load()
                self.plan = list(self.plan_store.items)
            diff = str(record.get("diff", "")).strip()
            if diff:
                activity = f"goal: {diff}"
        elif event == "cycle_completed":
            with self.lock:
                self.plan_store.load()
                if self.plan_store.items:
                    self.plan = list(self.plan_store.items)
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

    def _pending_human_inputs(self) -> list[str]:
        pending: list[str] = []
        for name in ("capability_requests.md", "key_requests.md", "HUMAN_REQUEST.md", "HUMAN_INPUT.md"):
            path = self.workspace / "state" / name if name not in {"HUMAN_REQUEST.md", "HUMAN_INPUT.md"} else self.workspace / name
            try:
                text = path.read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                continue
            if text:
                pending.append(f"{name}: {text.splitlines()[0][:300]}")
        return pending

    _pending_requests = _pending_human_inputs

    def _tool_list(self) -> list[str]:
        result = []
        tools_dir = self.workspace / "tools"
        if tools_dir.exists():
            for meta in tools_dir.glob("*/meta.json"):
                data = _read_json(meta)
                if data.get("registered"):
                    result.append(str(data.get("name", meta.parent.name)))
        return sorted(result)

    def handle_plugins_command(self, command: str) -> str:
        """Handle human-only /plugins commands for listing, enabling, and disabling plugins."""
        cmd = command.strip()
        if cmd in {"/plugins", "/plugins list"}:
            self.plugins.discover()
            cfg = self.plugins.read_config().get("plugins", {})
            if not self.plugins.discovered:
                return "No plugins discovered in image /opt/agent/plugins or workspace/plugins/."
            lines = ["**Discovered Plugins:**\n"]
            for name, p in sorted(self.plugins.discovered.items()):
                entry = cfg.get(name, {})
                status = "ENABLED" if entry.get("enabled") else "DISABLED"
                source = "shipped" if p.is_shipped else "workspace"
                h = entry.get("hash", "")
                h_str = f" [hash: {h[:12]}...]" if h else ""
                lines.append(f"- **{name}** (v{p.manifest.version}, {p.manifest.kind}, {source}): [{status}]{h_str}")
                lines.append(f"  {p.manifest.description}")
                if p.manifest.tools:
                    tool_names = [f"{name}.{t['name']}" for t in p.manifest.tools]
                    lines.append(f"  Tools: {', '.join(tool_names)}")
            return "\n".join(lines)

        if cmd.startswith("/plugins enable "):
            name = cmd.removeprefix("/plugins enable ").strip()
            if not name:
                return "Usage: /plugins enable <name>"
            try:
                res = self.plugins.enable_by_human(name)
                return f"Plugin '{name}' enabled (hash: {res['hash'][:12]}...). Takes effect at the next cycle boundary."
            except PermissionError:
                return f"Cannot enable plugin '{name}': /config/plugins.json is mounted read-only (human host config). Please edit ./config/plugins.json on host."
            except Exception as exc:
                return f"Could not enable plugin '{name}': {exc}"

        if cmd.startswith("/plugins disable "):
            name = cmd.removeprefix("/plugins disable ").strip()
            if not name:
                return "Usage: /plugins disable <name>"
            try:
                self.plugins.disable_by_human(name)
                return f"Plugin '{name}' disabled. Takes effect at the next cycle boundary."
            except PermissionError:
                return f"Cannot disable plugin '{name}': /config/plugins.json is mounted read-only. Please edit ./config/plugins.json on host."
            except Exception as exc:
                return f"Could not disable plugin '{name}': {exc}"

        if cmd.startswith("/plugins promote "):
            name = cmd.removeprefix("/plugins promote ").strip()
            if not name:
                return "Usage: /plugins promote <name>"
            from agent.plugins.self_dev import PluginDevManager
            dev = PluginDevManager(self.workspace, self.logger)
            res = dev.promote_draft_by_human(name)
            if not res.get("ok"):
                return f"Could not promote plugin '{name}': {res.get('error')}"
            diff_summary = res.get("diff", "")
            perm_summary = res.get("permission_summary", {})
            return (
                f"Plugin '{name}' promoted to workspace/plugins/{name} as DISABLED.\n"
                f"Permission requests: {json.dumps(perm_summary, indent=2)}\n"
                f"Review diff:\n{diff_summary[:2000]}\n\n"
                f"To enable this plugin, run: /plugins enable {name}"
            )

        return "Unknown plugins command. Usage: /plugins list, /plugins enable <name>, /plugins disable <name>, /plugins promote <name>"

    def handle_proposals_command(self, command: str = "/proposals") -> str:
        """Display plugin proposals from state/plugin_proposals.jsonl or record comments."""
        cmd = command.strip()
        parts = cmd.split(maxsplit=3)
        from agent.plugins.self_dev import PluginDevManager
        dev = PluginDevManager(self.workspace, self.logger)

        if len(parts) >= 4 and parts[1] == "comment":
            target_name = parts[2]
            comment_text = parts[3]
            self.receive_human_input(f"[Proposal comment on '{target_name}'] {comment_text}", kind="proposal_comment")
            return f"Comment on proposal '{target_name}' submitted to agent inbox as advice to weigh."

        proposals = dev.list_proposals()
        if not proposals:
            return "No plugin proposals recorded in state/plugin_proposals.jsonl."

        lines = ["**Plugin Proposals:**\n"]
        for p in proposals:
            p_name = p.get("name", "unknown")
            status = p.get("status", "proposed")
            need = p.get("need", "")
            est = p.get("estimate", {})
            tokens_range = est.get("tokens", {})
            cycles_range = est.get("cycles", {})
            lines.append(f"- **{p_name}** [{status}] (tokens: {tokens_range}, cycles: {cycles_range})")
            lines.append(f"  Need: {need}")
            lines.append(f"  Derivation: {est.get('derivation', '')}")
            lines.append(f"  Expected benefit: {p.get('expected_benefit', '')}")
        lines.append("\nTo comment on a proposal: /proposals comment <name> <your comment>")
        return "\n".join(lines)

    def handle_slash_command(self, text: str) -> str | None:
        """Dispatch a human-facing slash command to active plugins."""
        if hasattr(self, "plugins") and self.plugins is not None:
            return self.plugins.handle_slash_command(text)
        return None

    def _orientation_changes(self) -> list[str]:
        sense_data = self.body.sense()
        changes = sense_data.get("orientation_changes")
        if isinstance(changes, list) and changes:
            return changes
        if hasattr(self.body, "orientation_changes"):
            return self.body.orientation_changes()
        return ["no tracked workspace, tool, credential-presence, or uptime change"]

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
        verify_startup_code_version(self.logger)
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.learning.initialize()
        self.plan_store.initialize(default_step=(self.plan[0].get("step") if self.plan else ""))
        if self.plan_store.items:
            self.plan = self.plan_store.items
        ledger = self.daily_ledger
        daily = ledger._read()
        with self.lock:
            self.telemetry.daily_used = int(daily.get("used_tokens", 0) or 0)
            self.telemetry.daily_reserved = int(daily.get("reserved_tokens", 0) or 0)
            self.telemetry.daily_cap = ledger.cap
        if (self.workspace / "STOP").exists():
            message = "I am paused because STOP was requested earlier. Remove workspace/STOP or use /restart, then I can wake again."
            self.logger.narrate(message)
            return message
        if hasattr(self, "stop_watcher") and self.stop_watcher is not None:
            self.stop_watcher.start()
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
        self.plan = normalized_plan(list(old.get("plan") or default_plan()))
        self._recover_budget_blocked_plan()
        self.handoff["plan"] = self.plan
        with self.lock:
            self.starting_plan = [dict(it) for it in self.plan]
            self.starting_session_id = self.status.session_id
        changes = self._orientation_changes()
        checks = self._spot_check_map()
        crash = self._session_info.get("crash")
        prior_summary = old.get("summary", "I have no prior handoff in my state files.")
        prior_plan = (self.plan[0].get("step") if self.plan else "inspect state")
        pending = self._pending_human_inputs()
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
            greeting = "Pending human inputs to consider: " + " | ".join(pending) + "\n" + greeting
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
        with self.lock:
            self.starting_plan = [dict(it) for it in self.plan]
            self.starting_session_id = self.status.session_id

    def render_starting_plan(self) -> str:
        """Render the plan that was established when the current session started."""
        with self.lock:
            plan = list(self.starting_plan or self.plan)
            session_id = self.starting_session_id or self.status.session_id
        return format_starting_plan(plan, session_id=session_id)

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
            if str(item.get("status", "")).strip().lower().startswith("suspended"):
                retained.append(item)
                continue
            details = f"{item.get('step', '')} {item.get('why', '')}".lower()
            token_item = any(marker in details for marker in ("token", "budget", "limit"))
            package_item = "installed python packages" in details or "python package inventory" in details
            environment_item = "free disk" in details or "network reachability" in details

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
            "long_term_summary": self.handoff.get("long_term_summary", ""),
            "discoveries": discoveries,
            "tools_created": [f"{name}: registered reusable tool" for name in self._tool_list()],
            "failures_and_lessons": failures[-12:] or ["No new recorded harness failures."],
            "open_questions": ["Weigh pending human inputs before attempting capability expansions."],
            "plan": self.plan,
            "pending_human_inputs": self._pending_human_inputs(),
            "mood_of_run": "stuck" if reason in {"token_budget", "wall_clock_budget"} else "progressing" if report else "exploring",
        }

    def receive_human_input(self, text: str, kind: str = "goal") -> None:
        """Queue human input for the next safe agent turn."""
        self.inbox.add(text, kind=kind)
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
        self.plan_store.load()
        decisions = self.plan_store.human_input_decisions[-10:]
        if not decisions:
            return "No human input decisions recorded yet."
        lines = ["Recent human input decisions:"]
        for d in decisions:
            dec = d.get("decision", "unknown")
            inp = d.get("input", "")
            reason = d.get("reason", "")
            cycle = d.get("cycle", 0)
            p = d.get("priority")
            p_str = f" [priority {p}]" if p is not None else ""
            lines.append(f"- [{dec}]{p_str} '{inp}' (cycle {cycle}): {reason}")
        return "\n".join(lines)

    def conversation_context(self) -> str:
        """Build a bounded read-only snapshot for an independent conversation."""
        identity = self.identity.prompt_context()
        handoff = json.dumps(self.handoff, ensure_ascii=False)[:6_000]
        self.plan_store.load()
        active_plan = self.plan_store.top_items(limit=5)
        plan = json.dumps(active_plan if active_plan else visible_plan_items(self.plan)[:5], ensure_ascii=False)[:4_000]
        decisions = self.plan_store.human_input_decisions[-5:]
        decisions_summary = json.dumps(decisions, ensure_ascii=False)[:2_000] if decisions else "No decisions recorded yet."
        activity = "\n".join(list(self._activity)[-40:])[:6_000]
        summaries = "\n\n".join(list(self._cycle_summaries)[-6:])[:8_000]
        return (
            f"{identity}\n\nCurrent handoff:\n{handoff}\n\n"
            f"Active plan items:\n{plan}\n\n"
            f"Recent human input decisions:\n{decisions_summary}\n\n"
            f"Recent cycle summaries:\n{summaries}\n\n"
            f"Recent activity:\n{activity}"
        )

    def reflection_context(self) -> str:
        """Provide concise context for background reflection threads."""
        return self.conversation_context()

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
        greeting = self.boot() if not self._session_info else ""
        if (self.workspace / "STOP").exists():
            return None
        if self.max_iterations != 0:
            self.revise_plan()
        startup_context = ""
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
            startup_context = eval_instructions

        package_entry = self.learning._load_map().get("entries", {}).get("packages", {})
        package_value = package_entry.get("value")
        if package_value is None or package_value == "not yet inventoried":
            self.logger.narrate("Startup priority: I will immediately inventory installed Python packages before broader exploration.")
            package_instructions = self.body.initial_orientation_task()
            if startup_context:
                startup_context = f"{startup_context}\n\n{package_instructions}"
            else:
                startup_context = package_instructions

        checkpoint = _read_json(self.workspace / "state" / "run_checkpoint.json")
        initial_task_prefix = self.body.initial_orientation_task()[:40]
        stale_startup_task = (
            (bool(initial_task_prefix) and str(checkpoint.get("task", "")).startswith(initial_task_prefix)) or
            str(checkpoint.get("task", "")).startswith("Helper models needing evaluation")
        )

        resume_checkpoint_task = not stale_startup_task
        runner = ToolRunner(self.logger, self.workspace, body=self.body, broker=self.broker)
        runner.identity = self.identity
        runner.plan_store = self.plan_store
        runner.plugins = self.plugins
        loop = AgentLoop(
            AgentConfig(
                workspace=self.workspace,
                max_iterations=self.max_iterations,
                token_budget=self.token_budget,
                max_wall_clock_seconds=self.max_wall_clock_seconds,
                initial_context=startup_context,
                resume_checkpoint_task=resume_checkpoint_task,
                input_provider=self.inbox.consume,
                pause_provider=self.paused.is_set,
                on_cycle=self._checkpoint_cycle,
                identity_context_provider=self.identity.prompt_context,
                daily_ledger=self.daily_ledger,
                session_id=self.status.session_id,
                body=self.body,
                plugins=self.plugins,
                broker=self.broker,
                audit_trail=self.audit_trail,
                stop_watcher=self.stop_watcher,
            ),
            self.logger, self._llm, runner,
        )
        self.status.active_model, self.status.active_provider = getattr(loop.llm.client, "model", "unknown"), getattr(loop.llm.client, "provider", "unknown")
        try:
            summary = loop.run()
            if summary.iterations == 0:
                end_reason = "broker_panic" if summary.reason == "broker_panic" else "stop_file" if summary.reason in {"stop_file", "stop_watcher"} else "clean_shutdown" if self.stop_requested or summary.reason == "max_iterations" else "budget_exhausted" if summary.reason in {"token_budget", "wall_clock_budget"} else "provider_error" if summary.reason == "provider_error" else "clean_shutdown"
                self.sessions.finish(self.status.session_id, self.handoff, 0, summary.tokens_used, end_reason)
                self.logger.log("zero_cycle_session_preserved", session_id=self.status.session_id, end_reason=end_reason)
                self._session_info = {}
                return summary

            session_attempt = startup_context or STANDING_GOAL
            if self.stop_requested or summary.reason in {"stop_file", "stop_watcher", "broker_panic"}:
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
            end_reason = "broker_panic" if summary.reason == "broker_panic" else "stop_file" if summary.reason in {"stop_file", "stop_watcher"} else "clean_shutdown" if self.stop_requested or summary.reason == "max_iterations" else "budget_exhausted" if summary.reason in {"token_budget", "wall_clock_budget"} else "provider_error" if summary.reason == "provider_error" else "clean_shutdown"
            self.sessions.finish(self.status.session_id, handoff, summary.iterations, summary.tokens_used, end_reason)
            self._session_info = {}
            return summary
        except Exception:
            self.logger.log("session_unexpected_exception")
            raise


def run_headless(coordinator: WakeCoordinator) -> int:
    """Run a wake session without the terminal UI."""
    try:
        while True:
            try:
                result = coordinator.run()
            except Exception as exc:
                coordinator.logger.narrate(f"Wake coordinator failed: {type(exc).__name__}; retrying automatically.")
                time.sleep(3.0)
                continue
            if (coordinator.workspace / "STOP").exists() or coordinator.stop_requested or (hasattr(coordinator, "broker") and getattr(coordinator.broker, "in_panic", False)):
                break
            if (coordinator.workspace / "HUMAN_REQUEST.md").exists():
                coordinator.logger.narrate("Waiting for the human request to be resolved; the next session will start automatically afterward.")
                while (coordinator.workspace / "HUMAN_REQUEST.md").exists() and not (coordinator.workspace / "STOP").exists() and not coordinator.stop_requested:
                    time.sleep(2.0)
                continue
            delay = 3.0 if result is not None and getattr(result, "reason", "") == "provider_error" else 0.8
            coordinator.logger.narrate("Session ended; starting the next session automatically.")
            time.sleep(delay)
    finally:
        coordinator.close()
    return 0
