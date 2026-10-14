"""SELF's wake-up coordinator and optional Textual terminal interface."""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import signal
import threading
import time
from dataclasses import dataclass
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
        self._last_checkpoint = time.monotonic()
        self._session_start = ""
        self._session_info: dict[str, Any] = {}
        self._first_awakening_messages: list[str] = []
        self._llm: Any = llm_client
        self.on_narration: Callable[[str, str], None] | None = None
        self.logger.add_listener(self._event_listener)

    def _event_listener(self, record: dict[str, Any]) -> None:
        if record.get("event") == "narration" and self.on_narration:
            message = str(record.get("message", ""))
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
        ledger._read()  # validates/reinitializes the daily persisted budget.
        if (self.workspace / "STOP").exists():
            return "STOP file is present. I will not wake until it is removed."
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
        self.logger.narrate(f"Human: {text}")

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
        from textual.containers import Horizontal, Vertical
        from textual.widgets import Footer, Header, Input, RichLog, Static
    except ImportError:
        coordinator.logger.narrate("Textual is unavailable; falling back to --headless mode.")
        return run_headless(coordinator)

    class SelfApp(App[None]):
        CSS = """
        #body { height: 1fr; }
        #narration { width: 2fr; border: solid $primary; }
        #side { width: 1fr; }
        #plan, #status, #self { border: solid $secondary; height: 1fr; padding: 1; }
        #chat { dock: bottom; }
        """

        def compose(self) -> ComposeResult:
            yield Header(show_clock=True)
            with Horizontal(id="body"):
                yield RichLog(id="narration", wrap=True, markup=True)
                with Vertical(id="side"):
                    yield Static("Plan loading...", id="plan")
                    yield Static("Status loading...", id="status")
                    yield Static("Self loading...", id="self")
            yield Input(placeholder="Talk to SELF; /identity /rename <name> /self /patches /about me; /stop always halts cleanly", id="chat")
            yield Footer()

        def on_mount(self) -> None:
            self.title = f"SELF — {coordinator.identity.display_name()}"
            coordinator.on_narration = lambda message, kind: self.call_from_thread(self._write_narration, message, kind)
            self.set_interval(0.5, self._refresh)
            self.run_worker(self._run_agent, thread=True)

        def _write_narration(self, message: str, kind: str) -> None:
            color = {"explore": "cyan", "tool": "green", "error": "red", "lesson": "yellow", "request": "magenta"}.get(kind, "white")
            self.query_one("#narration", RichLog).write(f"[{color}]{message}[/{color}]")

        def _run_agent(self) -> None:
            try:
                coordinator.run()
            except Exception as exc:
                coordinator.logger.narrate(f"Wake coordinator failed: {type(exc).__name__}")
            finally:
                self.call_from_thread(self._write_narration, "Session ended. Review the handoff or restart SELF when ready.", "lesson")

        def _refresh(self) -> None:
            plan = "\n".join(f"{item.get('priority', 3)}. [{item.get('status', 'todo')}] {item.get('step', '')}" for item in coordinator.plan)
            uptime = int(time.monotonic() - coordinator.status.started_monotonic)
            since_human = int(time.monotonic() - coordinator.status.last_human_input)
            status = f"Session: {coordinator.status.session_id[:12]}\nIteration: {coordinator.status.iteration}\nTokens: {coordinator.status.tokens_used}/{coordinator.token_budget}\nModel: {coordinator.status.active_provider}/{coordinator.status.active_model}\nTools: {len(coordinator._tool_list())}\nUptime: {uptime}s\nSince human input: {since_human}s"
            self.query_one("#plan", Static).update("[b]Plan[/b]\n" + (plan or "No plan"))
            self.query_one("#status", Static).update("[b]Status[/b]\n" + status)
            self.query_one("#self", Static).update(coordinator.identity.self_panel_text())
            self.title = f"SELF — {coordinator.identity.display_name()}"

        def on_input_submitted(self, event: Input.Submitted) -> None:
            text = event.value.strip()
            event.input.value = ""
            if not text:
                return
            if text == "/pause":
                coordinator.paused.set(); self._write_narration("Paused. I will stop at the next safe boundary.", "lesson"); return
            if text == "/resume":
                coordinator.paused.clear(); self._write_narration("Resuming.", "lesson"); return
            if text == "/stop":
                coordinator.stop_requested = True; (coordinator.workspace / "STOP").touch(); self._write_narration("Stop requested; finishing the current safe action.", "request"); return
            if text == "/plan":
                self._write_narration(json.dumps(coordinator.plan, ensure_ascii=False), "lesson"); return
            if text == "/identity":
                self._write_narration(json.dumps(coordinator.identity.load(), ensure_ascii=False, indent=2), "lesson"); return
            if text.startswith("/rename "):
                try:
                    identity = coordinator.identity.set_name(text[8:].strip(), coordinator.status.session_id, named_by="human")
                    self.title = f"SELF — {identity.get('name')}"
                    self._write_narration(f"Name saved as {identity.get('name')}.", "lesson")
                except ValueError as exc:
                    self._write_narration(f"Could not rename: {exc}", "error")
                return
            if text == "/self":
                try:
                    content = (coordinator.workspace / "state" / "self_inquiry.md").read_text(encoding="utf-8", errors="replace")
                except OSError:
                    content = "No self inquiry exists yet; it is written during first awakening."
                self._write_narration(content[-6_000:], "lesson"); return
            if text == "/patches":
                patches = coordinator.identity.proposed_patches()
                message = "\n".join(str(path) for path in patches[:20]) if patches else "No proposed core patches are waiting for review."
                self._write_narration(message, "request"); return
            if text.startswith("/about me delete "):
                try:
                    line_number = int(text.removeprefix("/about me delete ").strip())
                    self._write_narration(coordinator.identity.delete_human_line(line_number, coordinator.status.session_id), "lesson")
                except (ValueError, FileNotFoundError) as exc:
                    self._write_narration(f"Could not delete stored line: {exc}", "error")
                return
            if text == "/about me":
                content = coordinator.identity.about_human_text()
                numbered = "\n".join(f"{index}: {line}" for index, line in enumerate(content.splitlines(), start=1))
                self._write_narration(numbered or "No volunteered information is stored about you.", "lesson"); return
            if text == "/journal":
                try: self._write_narration((coordinator.workspace / "state" / "journal.md").read_text(encoding="utf-8")[-3_000:], "lesson")
                except OSError: self._write_narration("No journal entry exists yet.", "lesson")
                return
            if text == "/tools": self._write_narration(", ".join(coordinator._tool_list()) or "No custom tools registered.", "tool"); return
            if text == "/requests": self._write_narration(_requests_text(coordinator.workspace), "request"); return
            if text.startswith("/memory "):
                self._write_narration(coordinator.learning.retrieve_memories(text[8:]), "lesson"); return
            if text == "/budget":
                self._write_narration(json.dumps(DailyTokenLedger(coordinator.workspace, coordinator.logger)._read()), "lesson"); return
            if text.startswith("/goal "):
                coordinator.receive_human_input("Temporary focus from the human: " + text[6:]); self._write_narration("Temporary focus queued for the next cycle.", "request"); return
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
