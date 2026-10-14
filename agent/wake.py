"""SELF's wake-up coordinator and optional Textual terminal interface."""
from __future__ import annotations

import argparse
import asyncio
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

from base_tools import ToolRunner
from event_log import EventLogger
from hardening import DailyTokenLedger
from identity import IdentityStore
from learning import LearningStore
from llm import BudgetedLLM, LLMClient
from loop import AgentConfig, AgentLoop, STANDING_GOAL
from session import HumanInbox, SessionStore, default_plan


KNOWN_CREDENTIAL_ENV = (
    "OLLAMA_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "GROQ_API_KEY",
    "OPENROUTER_API_KEY", "MISTRAL_API_KEY", "CEREBRAS_API_KEY", "HF_TOKEN",
    "CLOUDFLARE_API_TOKEN",
)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


@dataclass
class WakeStatus:
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


class WakeCoordinator:
    def __init__(self, workspace: str | Path = "/home/entity", *, max_iterations: int | None = None, token_budget: int | None = None, max_wall_clock_seconds: int | None = None, llm_client: Any | None = None) -> None:
        self.workspace = Path(workspace)
        self.logger = EventLogger(self.workspace / "logs" / "actions.jsonl")
        self.learning = LearningStore(self.workspace, self.logger)
        self.sessions = SessionStore(self.workspace, self.logger)
        self.inbox = HumanInbox(self.workspace, self.logger)
        self.identity = IdentityStore(self.workspace, self.logger)
        self.max_iterations = max_iterations or int(os.getenv("SELF_MAX_ITERATIONS", "20"))
        self.token_budget = token_budget or int(os.getenv("SELF_TOKEN_BUDGET", "50000"))
        self.max_wall_clock_seconds = max_wall_clock_seconds or int(os.getenv("SELF_MAX_WALL_CLOCK_SECONDS", "1800"))
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
        self.on_narration: Callable[[str, str], None] | None = None
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
                self.telemetry.run_budget = int(record.get("run_token_budget", self.telemetry.run_budget) or 0)
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
            }

    def _event_listener(self, record: dict[str, Any]) -> None:
        self._update_telemetry(record)
        if record.get("event") == "narration" and self.on_narration:
            message = str(record.get("message", ""))
            if message.startswith("Human: "):
                self.on_narration(message[7:], "human")
                return
            lower = message.lower()
            kind = "request" if "request" in lower or "approval" in lower else "error" if any(word in lower for word in ("error", "failed", "stuck")) else "lesson" if "learn" in lower else "tool" if "tool" in lower or "writing" in lower else "explore"
            self.on_narration(message, kind)

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
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.learning.initialize()
        ledger = DailyTokenLedger(self.workspace, self.logger)
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
        self._session_start = now_utc()
        self.identity.ensure_editable_layer()
        self._first_awakening_messages = self.identity.run_first_awakening(self.status.session_id)
        for message in self._first_awakening_messages:
            self.logger.narrate(message)
        old = self._session_info.get("handoff", {})
        self.handoff = old
        self.plan = list(old.get("plan") or default_plan())
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
        if pending:
            greeting = "Pending human requests: " + " | ".join(pending) + "\n" + greeting
        self.logger.narrate(greeting)
        return greeting

    def _reflection(self, purpose: str, extra: str = "") -> dict[str, Any]:
        """One bounded planning/reflection call; deterministic fallback preserves continuity."""
        fallback = {"plan": self.plan, "summary": self.handoff.get("summary", "State reviewed without an LLM reflection."), "mood_of_run": "exploring", "failures_and_lessons": []}
        try:
            if self._llm is None:
                self._llm = LLMClient(self.logger)
            budget = BudgetedLLM(self._llm, self.logger, min(4_000, self.token_budget), DailyTokenLedger(self.workspace, self.logger))
            result = budget.call(
                system="You are SELF preparing a truthful durable handoff. Return ONLY JSON with summary, plan (objects: step, why, priority, status), mood_of_run, failures_and_lessons, open_questions. Do not invent facts; use only supplied state. Redact secrets.",
                messages=[{"role": "user", "content": self.logger.redactor.text(f"Purpose: {purpose}\nOld handoff: {json.dumps(self.handoff, ensure_ascii=False)[:7000]}\nCurrent plan: {json.dumps(self.plan)}\n{extra}")}],
                tools=[], max_tokens=900,
            )
            text = "\n".join(str(block.get("text", "")) for block in result.content if block.get("type") == "text").strip()
            if text.startswith("```"):
                text = text.strip("`").removeprefix("json").strip()
            reflected = json.loads(text)
            if not isinstance(reflected, dict) or not isinstance(reflected.get("plan", []), list):
                raise ValueError("reflection did not return a plan object")
            self.logger.log("session_reflection_completed", purpose=purpose, tokens_used=budget.tokens_used)
            return self.logger.redactor.value(reflected)
        except Exception as exc:
            self.logger.log("session_reflection_fallback", purpose=purpose, error_type=type(exc).__name__)
            return fallback

    def revise_plan(self) -> None:
        reflected = self._reflection("wake-up plan review", "Revise the old plan against current state and spot checks.")
        self.plan = list(reflected.get("plan") or self.plan)
        self.handoff["long_term_summary"] = reflected.get("summary", self.handoff.get("long_term_summary", ""))
        self.logger.narrate("I reviewed the previous plan against current state and updated the plan.")

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
        greeting = self.boot()
        if (self.workspace / "STOP").exists():
            return None
        self.revise_plan()  # The required wake-up reflection occurs before exploration.
        runner = ToolRunner(self.logger, self.workspace)
        runner.identity = self.identity
        loop = AgentLoop(
            AgentConfig(
                workspace=self.workspace,
                max_iterations=max(1, self.max_iterations),
                token_budget=max(1, self.token_budget),
                max_wall_clock_seconds=max(1, self.max_wall_clock_seconds),
                input_provider=self.inbox.consume,
                pause_provider=self.paused.is_set,
                on_cycle=self._checkpoint_cycle,
                identity_context_provider=self.identity.prompt_context,
            ),
            self.logger, self._llm or LLMClient(self.logger), runner,
        )
        self.status.active_model, self.status.active_provider = getattr(loop.llm.client, "model", "unknown"), getattr(loop.llm.client, "provider", "unknown")
        try:
            summary = loop.run()
            reflection = self._reflection("shutdown reflection", f"Loop ended with reason={summary.reason}; last report={self.handoff.get('summary', '')}")
            self.plan = list(reflection.get("plan") or self.plan)
            self.identity.reflect_session(
                self.status.session_id,
                self._session_start,
                str(reflection.get("summary", "")),
            )
            handoff = self._make_handoff(reflection.get("summary", ""), summary.reason)
            handoff["failures_and_lessons"] = list(handoff["failures_and_lessons"]) + list(reflection.get("failures_and_lessons", []))
            end_reason = "clean_shutdown" if self.stop_requested or summary.reason == "max_iterations" else "stop_file" if summary.reason == "stop_file" else "budget_exhausted" if summary.reason in {"token_budget", "wall_clock_budget"} else "clean_shutdown"
            self.sessions.finish(self.status.session_id, handoff, summary.iterations, summary.tokens_used, end_reason)
            return summary
        except Exception:
            # Leave active_session.json marked running; the next wake records a
            # crash and reconstructs from the most recent checkpoint.
            self.logger.log("session_unexpected_exception")
            raise


def now_utc() -> str:
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
    coordinator.run()
    return 0


def run_tui(coordinator: WakeCoordinator) -> int:
    try:
        from textual.app import App, ComposeResult
        from textual.containers import Horizontal, Vertical, VerticalScroll
        from textual.widgets import Footer, Header, Input, Static
        from rich.text import Text
        from voice import VoiceController
    except ImportError:
        coordinator.logger.narrate("Textual is unavailable; falling back to --headless mode.")
        return run_headless(coordinator)

    class SelfApp(App[None]):
        CSS = """
        #body { height: 1fr; }
        #conversation-pane { width: 2fr; border: solid $primary; }
        #conversation-header { height: 3; padding: 1; color: $text-muted; }
        #presence { height: 3; padding: 1; border: solid $accent; color: $text; }
        #activity { height: 3; padding: 1; color: $secondary; }
        #conversation { height: 1fr; padding: 0 1; scrollbar-gutter: stable; }
        .message { width: 100%; margin: 0 0 1 0; padding: 1; }
        .agent-message { border-left: thick $primary; background: $panel; }
        .human-message { border-left: thick $accent; background: $boost; }
        .typing-message { border-left: thick $secondary; background: $panel; color: $text-muted; }
        #side { width: 1fr; }
        #plan, #status, #stats, #self { border: solid $secondary; height: 1fr; padding: 1; }
        #stats { height: 1.4fr; }
        #chat { dock: bottom; }
        """

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self.voice = VoiceController()
            self.typing_enabled = True
            self.typing_delay = max(0.001, min(float(os.getenv("SELF_TUI_TYPING_DELAY", "0.018")), 0.2))
            self._pending_messages: list[tuple[str, str, str]] = []
            self._draining_messages = False
            self._agent_running = False
            self._activity_frame = 0

        def compose(self) -> ComposeResult:
            yield Header(show_clock=True)
            with Horizontal(id="body"):
                with Vertical(id="conversation-pane"):
                    yield Static(f"[b]Conversation with {coordinator.identity.display_name()}[/b]   [b]YOU[/b] = human messages", id="conversation-header", markup=True)
                    yield Static(f"● {coordinator.identity.display_name()} · presence starting", id="presence")
                    yield Static("[----] idle", id="activity")
                    yield VerticalScroll(id="conversation")
                with Vertical(id="side"):
                    yield Static("Plan loading...", id="plan")
                    yield Static("Status loading...", id="status")
                    yield Static("Stats loading...", id="stats", markup=False)
                    yield Static("Self loading...", id="self")
            yield Input(placeholder="Talk to SELF; /name <your name> /restart /identity /rename <entity name>; /stop pauses safely", id="chat")
            yield Footer()

        def on_mount(self) -> None:
            self.title = f"SELF — {coordinator.identity.display_name()}"
            coordinator.on_narration = lambda message, kind: self.call_from_thread(self._write_narration, message, kind)
            self.set_interval(0.5, self._refresh)
            self.set_interval(0.16, self._animate_activity)
            self.run_worker(self._run_agent, thread=True)

        def _animate_activity(self) -> None:
            active = self._agent_running or self._draining_messages
            if not active:
                self.query_one("#activity", Static).update("[----] idle")
                return
            frames = ("[>   ]", "[>>  ]", "[>>> ]", "[ >>>]", "[  >>]", "[   >]")
            self._activity_frame = (self._activity_frame + 1) % len(frames)
            state = str(coordinator.runtime_snapshot()["state"]).lower()
            label = "talking" if self._draining_messages and not self._agent_running else state
            self.query_one("#activity", Static).update(f"{frames[self._activity_frame]} {label} ...")

        def _write_narration(self, message: str, kind: str) -> None:
            role = "human" if kind == "human" else "agent"
            self._pending_messages.append((role, message, kind))
            if not self._draining_messages:
                self._draining_messages = True
                self.run_worker(self._drain_messages(), exclusive=False)

        def _render_message(self, role: str, message: str, kind: str, *, typing: bool = False) -> Text:
            if role == "human":
                badge, badge_style, label_style = " YOU ", "bold white on dark_orange", "bold #ffbd7a"
            else:
                badge, badge_style, label_style = f" {coordinator.identity.display_name()} ", "bold white on dark_blue", "bold #8ed8ff"
            text = Text()
            text.append(badge, style=badge_style)
            text.append("  " + ("typing..." if typing else kind.title()), style=label_style)
            text.append("\n")
            text.append(message)
            return text

        async def _drain_messages(self) -> None:
            conversation = self.query_one("#conversation", VerticalScroll)
            try:
                while self._pending_messages:
                    role, message, kind = self._pending_messages.pop(0)
                    bubble = Static(self._render_message(role, "" if role == "agent" and self.typing_enabled else message, kind, typing=role == "agent" and self.typing_enabled), classes=f"message {'human' if role == 'human' else 'agent'}-message")
                    await conversation.mount(bubble)
                    conversation.scroll_end(animate=False)
                    if role == "agent" and self.typing_enabled:
                        step = max(1, len(message) // 90)
                        for index in range(step, len(message) + step, step):
                            visible = message[:index]
                            if len(visible) >= len(message):
                                visible = message
                            bubble.update(self._render_message(role, visible, kind))
                            conversation.scroll_end(animate=False)
                            if len(visible) < len(message):
                                await asyncio.sleep(self.typing_delay)
                    if role == "agent" and kind != "tool":
                        self.voice.speak(message)
            finally:
                self._draining_messages = False
                if self._pending_messages:
                    self._draining_messages = True
                    self.run_worker(self._drain_messages(), exclusive=False)

        def _write_human_command(self, message: str) -> None:
            self._write_narration(message, "human")

        def _voice_status(self, message: str | None = None) -> None:
            self._write_narration(message or self.voice.status_text(), "lesson")

        def _run_agent(self) -> None:
            self._agent_running = True
            final_message: str | None = None
            try:
                result = coordinator.run()
                if not (result is None and (coordinator.workspace / "STOP").exists()):
                    if (coordinator.workspace / "STOP").exists():
                        final_message = "I am paused because STOP was requested. Use /restart here, or remove workspace/STOP and launch SELF again."
                    elif (coordinator.workspace / "HUMAN_REQUEST.md").exists():
                        final_message = "I am waiting for your decision in HUMAN_REQUEST.md. Resolve it, remove the file, then use /restart."
                    else:
                        final_message = "This session ended cleanly. Use /restart to begin another conversation with me."
            except Exception as exc:
                coordinator.logger.narrate(f"Wake coordinator failed: {type(exc).__name__}")
                final_message = f"I could not continue this session because of {type(exc).__name__}. Review the log, then use /restart."
            finally:
                self._agent_running = False
                if final_message:
                    self.call_from_thread(self._write_narration, final_message, "request" if "paused" in final_message or "waiting" in final_message else "lesson")

        def _refresh(self) -> None:
            telemetry = coordinator.runtime_snapshot()
            ai_counts = telemetry["calls_by_ai"]
            calls = "\n".join(f"{name}: {count}" for name, count in sorted(ai_counts.items())) or "No AI calls yet"
            plan = "\n".join(f"{item.get('priority', 3)}. [{item.get('status', 'todo')}] {item.get('step', '')}" for item in coordinator.plan)
            uptime = int(time.monotonic() - coordinator.status.started_monotonic)
            since_human = int(time.monotonic() - coordinator.status.last_human_input)
            run_tokens = telemetry["run_tokens_used"] or coordinator.status.tokens_used
            run_budget = telemetry["run_budget"] or coordinator.token_budget
            status = f"Session: {coordinator.status.session_id[:12]}\nIteration: {coordinator.status.iteration}\nTokens: {run_tokens}/{run_budget}\nModel: {coordinator.status.active_provider}/{coordinator.status.active_model}\nTools: {len(coordinator._tool_list())}\nUptime: {uptime}s\nSince human input: {since_human}s"
            daily_remaining = max(0, telemetry["daily_cap"] - telemetry["daily_used"] - telemetry["daily_reserved"]) if telemetry["daily_cap"] else "unknown"
            stats = (
                f"Presence: {telemetry['state']}\n"
                f"Current AI: {telemetry['current_ai']}\n"
                f"Calls: {telemetry['total_calls']} total | {telemetry['completed_calls']} completed | {telemetry['failed_calls']} failed\n"
                f"Run budget: {run_budget}\n"
                f"Daily tokens: {telemetry['daily_used']}/{telemetry['daily_cap'] or '?'} (remaining {daily_remaining})\n"
                f"AI call counts:\n{calls}"
            )
            if telemetry["daily_blocked"]:
                stats += "\n\nACTION NEEDED: daily limit reached; see HUMAN_REQUEST.md"
            presence = f"● {coordinator.identity.display_name()} · {telemetry['state']} · {telemetry['current_ai']}"
            self.query_one("#presence", Static).update(presence)
            self.query_one("#plan", Static).update("[b]Plan[/b]\n" + (plan or "No plan"))
            self.query_one("#status", Static).update("[b]Status[/b]\n" + status + "\n" + self.voice.status_text())
            self.query_one("#stats", Static).update(stats)
            self.query_one("#self", Static).update(coordinator.identity.self_panel_text())
            self.title = f"SELF — {coordinator.identity.display_name()}"

        def on_input_submitted(self, event: Input.Submitted) -> None:
            text = event.value.strip()
            event.input.value = ""
            if not text:
                return
            if text == "/voice":
                self._write_human_command(text); self._voice_status(); return
            if text in {"/voice on", "/voice off"}:
                self._write_human_command(text); self._voice_status(self.voice.set_enabled(text.endswith(" on"))); return
            if text == "/typing":
                self._write_human_command(text); self._write_narration(f"Typing effect {'enabled' if self.typing_enabled else 'disabled'}.", "lesson"); return
            if text in {"/typing on", "/typing off"}:
                self._write_human_command(text); self.typing_enabled = text.endswith(" on"); self._write_narration(f"Typing effect {'enabled' if self.typing_enabled else 'disabled'}.", "lesson"); return
            if text == "/listen":
                self._write_human_command(text)
                self._write_narration("Listening for one microphone phrase...", "request")
                self.run_worker(self._listen_for_human, thread=True)
                return
            if text == "/restart":
                self._write_human_command(text)
                if self._agent_running:
                    self._write_narration("I am already running; use /stop first if you want a fresh session.", "lesson")
                    return
                stop_path = coordinator.workspace / "STOP"
                try:
                    if stop_path.exists():
                        stop_path.unlink()
                except OSError as exc:
                    self._write_narration(f"I could not remove STOP: {type(exc).__name__}.", "error")
                    return
                coordinator.stop_requested = False
                coordinator.paused.clear()
                self._write_narration("I removed the previous stop request and am waking now.", "request")
                self.run_worker(self._run_agent, thread=True)
                return
            if text == "/pause":
                self._write_human_command(text)
                coordinator.paused.set(); self._write_narration("Paused. I will stop at the next safe boundary.", "lesson"); return
            if text == "/resume":
                self._write_human_command(text)
                coordinator.paused.clear(); self._write_narration("Resuming.", "lesson"); return
            if text == "/stop":
                self._write_human_command(text)
                coordinator.stop_requested = True; (coordinator.workspace / "STOP").touch(); self._write_narration("Stop requested; finishing the current safe action.", "request"); return
            if text == "/plan":
                self._write_human_command(text)
                self._write_narration(json.dumps(coordinator.plan, ensure_ascii=False), "lesson"); return
            if text == "/identity":
                self._write_human_command(text)
                self._write_narration(json.dumps(coordinator.identity.load(), ensure_ascii=False, indent=2), "lesson"); return
            if text.startswith("/rename "):
                self._write_human_command(text)
                try:
                    identity = coordinator.identity.set_name(text[8:].strip(), coordinator.status.session_id, named_by="human")
                    self.title = f"SELF — {identity.get('name')}"
                    self._write_narration(f"Name saved as {identity.get('name')}.", "lesson")
                except ValueError as exc:
                    self._write_narration(f"Could not rename: {exc}", "error")
                return
            if text == "/name":
                self._write_human_command(text)
                current = coordinator.identity.human_name()
                self._write_narration(f"I currently know your name as {current}." if current else "I do not know your name yet. Use `/name <your name>` or say `My name is ...`.", "lesson")
                return
            if text.startswith("/name "):
                self._write_human_command(text)
                try:
                    saved = coordinator.identity.set_human_name(text[6:].strip(), coordinator.status.session_id)
                    self._write_narration(f"Thank you, {saved}. I saved your name for future conversations.", "lesson")
                except ValueError as exc:
                    self._write_narration(f"Could not save your name: {exc}", "error")
                return
            if text == "/self":
                self._write_human_command(text)
                try:
                    content = (coordinator.workspace / "state" / "self_inquiry.md").read_text(encoding="utf-8", errors="replace")
                except OSError:
                    content = "No self inquiry exists yet; it is written during first awakening."
                self._write_narration(content[-6_000:], "lesson"); return
            if text == "/patches":
                self._write_human_command(text)
                patches = coordinator.identity.proposed_patches()
                message = "\n".join(str(path) for path in patches[:20]) if patches else "No proposed core patches are waiting for review."
                self._write_narration(message, "request"); return
            if text.startswith("/about me delete "):
                self._write_human_command(text)
                try:
                    line_number = int(text.removeprefix("/about me delete ").strip())
                    self._write_narration(coordinator.identity.delete_human_line(line_number, coordinator.status.session_id), "lesson")
                except (ValueError, FileNotFoundError) as exc:
                    self._write_narration(f"Could not delete stored line: {exc}", "error")
                return
            if text == "/about me":
                self._write_human_command(text)
                content = coordinator.identity.about_human_text()
                numbered = "\n".join(f"{index}: {line}" for index, line in enumerate(content.splitlines(), start=1))
                self._write_narration(numbered or "No volunteered information is stored about you.", "lesson"); return
            if text == "/journal":
                self._write_human_command(text)
                try: self._write_narration((coordinator.workspace / "state" / "journal.md").read_text(encoding="utf-8")[-3_000:], "lesson")
                except OSError: self._write_narration("No journal entry exists yet.", "lesson")
                return
            if text == "/tools": self._write_human_command(text); self._write_narration(", ".join(coordinator._tool_list()) or "No custom tools registered.", "tool"); return
            if text == "/requests": self._write_human_command(text); self._write_narration(_requests_text(coordinator.workspace), "request"); return
            if text.startswith("/memory "):
                self._write_human_command(text)
                self._write_narration(coordinator.learning.retrieve_memories(text[8:]), "lesson"); return
            if text == "/budget":
                self._write_human_command(text)
                self._write_narration(json.dumps(DailyTokenLedger(coordinator.workspace, coordinator.logger)._read()), "lesson"); return
            if text.startswith("/goal "):
                self._write_human_command(text)
                coordinator.receive_human_input("Temporary focus from the human: " + text[6:]); self._write_narration("Temporary focus queued for the next cycle.", "request"); return
            coordinator.receive_human_input(text)

        def _listen_for_human(self) -> None:
            text, error = self.voice.listen()
            if error:
                self.call_from_thread(self._write_narration, error, "error")
                return
            if text:
                coordinator.receive_human_input(text)

    SelfApp().run()
    return 0


def main() -> int:
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
