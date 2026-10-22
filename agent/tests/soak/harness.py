"""Deterministic soak test harness for multi-cycle simulation against real loop and session state."""
from __future__ import annotations

import json
import os
import random
import re
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from agent.infra.event_log import EventLogger
from agent.llm.llm import LLMResult
from agent.session.coordinator import WakeCoordinator


# -----------------------------------------------------------------------------
# 1. Exact Exception Types matching Real Provider Client Shapes
# -----------------------------------------------------------------------------

class APIConnectionError(ConnectionError):
    """Network connection error, matching Anthropic / Ollama network failure."""
    def __init__(self, message: str = "Connection refused or unreachable") -> None:
        super().__init__(message)
        self.status_code = None


class APITimeoutError(TimeoutError):
    """Request timeout error."""
    def __init__(self, message: str = "Request timed out after deadline") -> None:
        super().__init__(message)
        self.status_code = None


class RateLimitError(Exception):
    """HTTP 429 rate limit exceeded."""
    def __init__(self, message: str = "Rate limit exceeded (429)") -> None:
        super().__init__(message)
        self.status_code = 429


class InternalServerError(Exception):
    """HTTP 500 internal server error."""
    def __init__(self, message: str = "Internal server error (500)") -> None:
        super().__init__(message)
        self.status_code = 500


class BadRequestError(Exception):
    """HTTP 400 bad request error."""
    def __init__(self, message: str = "Bad request (400)") -> None:
        super().__init__(message)
        self.status_code = 400


# -----------------------------------------------------------------------------
# 2. Fake Clock for Deterministic Time Progression
# -----------------------------------------------------------------------------

class FakeClock:
    """Deterministic clock providing monotonic and epoch time without real sleep."""

    def __init__(self, start_time: float = 1729500000.0) -> None:
        self.epoch = start_time
        self.mono = 1000.0

    def time(self) -> float:
        return self.epoch

    def monotonic(self) -> float:
        return self.mono

    def advance(self, seconds: float) -> None:
        self.epoch += max(0.0, seconds)
        self.mono += max(0.0, seconds)

    def sleep(self, seconds: float) -> None:
        self.advance(seconds)


# -----------------------------------------------------------------------------
# 3. Fault Schedule
# -----------------------------------------------------------------------------

class FaultSchedule:
    """Schedule of faults injected by cycle, round, or call count."""

    def __init__(
        self,
        schedule: dict[Any, Any] | None = None,
        *,
        consume: bool = True,
    ) -> None:
        self.schedule: dict[Any, Any] = dict(schedule or {})
        self.consume = consume

    def add_fault(self, target: Any, fault: Any) -> None:
        self.schedule[target] = fault

    def get_fault(self, cycle: int, round_num: int = 1, call_count: int = 0) -> Any | None:
        for key in ((cycle, round_num), cycle, f"call_{call_count}", f"cycle_{cycle}"):
            if key in self.schedule:
                return self.schedule.pop(key) if self.consume else self.schedule[key]
        return None


# -----------------------------------------------------------------------------
# 4. Scripted Provider
# -----------------------------------------------------------------------------

class ScriptedProvider:
    """Scripted LLM provider simulating real model turns, faults, and tool calls."""

    def __init__(
        self,
        fault_schedule: FaultSchedule | None = None,
        cycle_scripts: dict[int, list[LLMResult | dict[str, Any] | str]] | None = None,
        model: str = "scripted-fake-model",
        key_count: int = 1,
    ) -> None:
        self.model = model
        self.base_model = model
        self.provider = "scripted"
        self.available_models = [model, "helper-fast", "helper-reasoning"]
        self.key_count = max(1, key_count)
        self.key_index = 0
        self.calls = 0
        self.current_cycle = 1
        self.round_in_cycle = 0
        self.max_observed_rounds_per_cycle = 0
        self.calls_by_cycle: dict[int, int] = {}
        self.call_history: list[dict[str, Any]] = []
        self.fault_schedule = fault_schedule or FaultSchedule()
        self.cycle_scripts = cycle_scripts or {}
        self.max_calls_per_cycle = 20

    def _rotate_key(self) -> bool:
        if self.key_index + 1 < self.key_count:
            self.key_index += 1
            return True
        return False

    def _parse_cycle(self, messages: list[dict[str, Any]]) -> int:
        if messages and isinstance(messages[0].get("content"), str):
            m = re.search(r"Begin exploration cycle (\d+)", messages[0]["content"])
            if m:
                return int(m.group(1))
        return 1

    def call(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int,
        model: str | None = None,
        **_: Any,
    ) -> LLMResult:
        self.calls += 1
        cycle = self._parse_cycle(messages)
        if len(messages) == 1 or cycle != self.current_cycle:
            self.current_cycle = cycle
            self.round_in_cycle = 1
        else:
            self.round_in_cycle += 1

        round_num = self.round_in_cycle
        self.max_observed_rounds_per_cycle = max(self.max_observed_rounds_per_cycle, round_num)
        self.calls_by_cycle[cycle] = max(self.calls_by_cycle.get(cycle, 0), round_num)

        if round_num > self.max_calls_per_cycle:
            raise RuntimeError(f"Infinite loop protection: cycle {cycle} exceeded {self.max_calls_per_cycle} calls")

        selected_model = model or self.base_model
        record = {
            "call_index": self.calls,
            "cycle": cycle,
            "round": round_num,
            "model": selected_model,
            "message_count": len(messages),
            "tool_count": len(tools),
        }
        self.call_history.append(record)

        # 1. Check fault schedule
        fault = self.fault_schedule.get_fault(cycle, round_num, self.calls)
        if fault is not None:
            if isinstance(fault, type) and issubclass(fault, Exception):
                raise fault()
            if isinstance(fault, Exception):
                raise fault
            if fault == "empty_body" or fault == "empty_response":
                return LLMResult(content=[], input_tokens=10, output_tokens=0, stop_reason="end_turn", model=selected_model)
            if fault == "truncated":
                return LLMResult(
                    content=[{"type": "text", "text": "Report truncated due to token limit..."}],
                    input_tokens=25, output_tokens=max_tokens, stop_reason="max_tokens", model=selected_model,
                )
            if fault == "malformed_json":
                return LLMResult(
                    content=[{"type": "tool_use", "id": f"bad-{self.calls}", "name": "read_file", "input": "{malformed json"}],
                    input_tokens=15, output_tokens=10, stop_reason="tool_use", model=selected_model,
                )
            if isinstance(fault, LLMResult):
                return fault

        # 2. Check cycle scripts
        if cycle in self.cycle_scripts:
            script_list = self.cycle_scripts[cycle]
            script_idx = round_num - 1
            if script_idx < len(script_list):
                item = script_list[script_idx]
                if isinstance(item, LLMResult):
                    return item
                if isinstance(item, dict):
                    # Check if it's a tool call dict
                    if "name" in item:
                        return LLMResult(
                            content=[{"type": "tool_use", "id": f"call-{self.calls}", "name": item["name"], "input": item.get("input", {})}],
                            input_tokens=20, output_tokens=20, stop_reason="tool_use", model=selected_model,
                        )
                    if "text" in item:
                        return LLMResult(
                            content=[{"type": "text", "text": item["text"]}],
                            input_tokens=20, output_tokens=20, stop_reason="end_turn", model=selected_model,
                        )
                if isinstance(item, str):
                    return LLMResult(
                        content=[{"type": "text", "text": item}],
                        input_tokens=20, output_tokens=20, stop_reason="end_turn", model=selected_model,
                    )

        # 3. Default progressive behavior: finish cycle cleanly with an autonomous report
        return LLMResult(
            content=[{"type": "text", "text": f"Cycle {cycle} complete. Exploration proceeding steadily according to plan."}],
            input_tokens=40, output_tokens=30, stop_reason="end_turn", model=selected_model,
        )


# -----------------------------------------------------------------------------
# 4b. Replay Provider
# -----------------------------------------------------------------------------

class ReplayProvider:
    """Replays historical error sequences, create_tool churn, and reflection patterns."""

    def __init__(
        self,
        fixture_path: Path | str | None = None,
        model: str = "replay-historical-model",
        logger: EventLogger | None = None,
        total_replay_cycles: int = 30,
    ) -> None:
        self.model = model
        self.base_model = model
        self.provider = "ollama"
        self.calls = 0
        self.current_cycle = 1
        self.round_in_cycle = 0
        self.logger = logger
        self.total_replay_cycles = max(1, total_replay_cycles)
        if fixture_path is None:
            fixture_path = Path(__file__).parent / "fixtures" / "real_run_shape.jsonl"
        self.fixture_path = Path(fixture_path)
        self.events: list[dict[str, Any]] = []
        if self.fixture_path.exists():
            with open(self.fixture_path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        self.events.append(json.loads(line))
                    except Exception:
                        pass
        self.llm_failures = [e for e in self.events if e.get("event") == "llm_call_failed"]
        self.create_tool_events = [e for e in self.events if e.get("tool") == "create_tool" and e.get("target_tool")]
        self.llm_cursor = 0
        self.tool_cursor = 0
        self.replayed_llm_failures: dict[str, int] = {}
        self.replayed_create_tools = 0
        self.replayed_reflections = 0

    def _parse_cycle(self, messages: list[dict[str, Any]]) -> int:
        if messages and isinstance(messages[0].get("content"), str):
            m = re.search(r"Begin exploration cycle (\d+)", messages[0]["content"])
            if m:
                return int(m.group(1))
        return self.current_cycle

    def call(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int,
        model: str | None = None,
        **_: Any,
    ) -> LLMResult:
        self.calls += 1
        cycle = self._parse_cycle(messages)
        if len(messages) == 1 or cycle != self.current_cycle:
            self.current_cycle = cycle
            self.round_in_cycle = 1
        else:
            self.round_in_cycle += 1

        selected_model = model or self.base_model

        # Handle reflection turns with nested 'Session complete after' text
        is_reflection = any("reflection" in str(m.get("content", "")).lower() for m in messages)
        if is_reflection:
            self.replayed_reflections += 1
            return LLMResult(
                content=[{
                    "type": "text",
                    "text": (
                        f"Session complete after {cycle} cycle(s).\n"
                        "Trying to do: shutdown reflection\n"
                        "Achieved: Session complete after 0 cycle(s).\n"
                        "Trying to do: shutdown reflection\n"
                        "Achieved: Exploratory work completed without unhandled faults."
                    ),
                }],
                input_tokens=50,
                output_tokens=40,
                stop_reason="end_turn",
                model=selected_model,
            )

        # In round 1 of a cycle, replay a slice of historical LLM failures and a create_tool attempt
        if self.round_in_cycle == 1:
            batch_size = max(1, len(self.llm_failures) // self.total_replay_cycles) if self.llm_failures else 0
            # On final cycle, consume remainder of fixture
            end_idx = len(self.llm_failures) if cycle >= self.total_replay_cycles else min(len(self.llm_failures), self.llm_cursor + batch_size)
            slice_failures = self.llm_failures[self.llm_cursor:end_idx]
            self.llm_cursor = end_idx

            if self.logger:
                for evt in slice_failures:
                    err_type = str(evt.get("error_type", "LLMError"))
                    self.replayed_llm_failures[err_type] = self.replayed_llm_failures.get(err_type, 0) + 1
                    self.logger.log(
                        "llm_call_failed",
                        cycle=cycle,
                        provider=self.provider,
                        model=selected_model,
                        error_type=err_type,
                        error=f"Replayed {err_type} from historical run",
                        retry_attempt=1,
                        retryable=evt.get("retryable", False),
                        effective_cap=max_tokens,
                    )

            # Repeatedly attempt a failing tool (timer_service_map from historical log)
            # across cycles 1, 3, 5, 7 to exercise 3-attempt lesson recording and blocking
            if cycle in (1, 3, 5, 7):
                target_tool = "timer_service_map"
            elif self.create_tool_events and self.tool_cursor < len(self.create_tool_events):
                target_tool = self.create_tool_events[self.tool_cursor]["target_tool"]
                self.tool_cursor += 1
            else:
                target_tool = "replay_broken_tool"

            self.replayed_create_tools += 1
            if cycle % 2 == 1:
                return LLMResult(
                    content=[{
                        "type": "tool_use",
                        "id": f"call-replay-{self.calls}",
                        "name": "create_tool",
                        "input": {
                            "name": target_tool,
                            "description": f"Historical failing tool {target_tool} attempt {cycle}",
                            "code": f"def run():\n    raise RuntimeError('deliberate failure attempt {cycle}')\n",
                            "test_code": "import unittest\nclass T(unittest.TestCase):\n    def test_fail(self):\n        self.fail('deliberate replay failure')\n",
                        },
                    }],
                    input_tokens=60,
                    output_tokens=40,
                    stop_reason="tool_use",
                    model=selected_model,
                )
            else:
                return LLMResult(
                    content=[{
                        "type": "tool_use",
                        "id": f"call-replay-{self.calls}",
                        "name": "read_file",
                        "input": {"path": "state/self_code_explanation.md" if (cycle // 2) % 2 == 0 else "state/plan.json"},
                    }],
                    input_tokens=40,
                    output_tokens=30,
                    stop_reason="tool_use",
                    model=selected_model,
                )

        # Subsequent rounds in cycle complete cleanly
        return LLMResult(
            content=[{"type": "text", "text": f"Cycle {cycle} complete. Replay stress test proceeding cleanly."}],
            input_tokens=40,
            output_tokens=30,
            stop_reason="end_turn",
            model=selected_model,
        )


# -----------------------------------------------------------------------------
# 5. Invariants Checker
# -----------------------------------------------------------------------------

class Invariants:
    """Comprehensive invariant assertion suite evaluated every cycle and at run finish."""

    MAX_HANDOFF_CHARS = 6_000
    MAX_PLAN_ITEMS = 20
    MAX_MEMORY_ENTRIES = 500
    MAX_CYCLE_LOG_GROWTH_BYTES = 25_000

    @classmethod
    def _get_recent_logs(cls, workspace: Path, lines: int = 20) -> str:
        log_file = workspace / "logs" / "actions.jsonl"
        if not log_file.exists():
            return "No actions.jsonl log found."
        try:
            all_lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
            return "\n".join(all_lines[-lines:])
        except Exception as exc:
            return f"Failed to read logs: {exc}"

    @classmethod
    def check_handoff(cls, cycle: int, seed: int, workspace: Path) -> None:
        """Invariant: handoff <= 6,000 chars, overflow used on excess, 'Session complete after' <= 1."""
        handoff_path = workspace / "state" / "handoff.json"
        if not handoff_path.exists():
            return
        content = handoff_path.read_text(encoding="utf-8", errors="replace")
        chars = len(content)
        if chars > cls.MAX_HANDOFF_CHARS:
            recent = cls._get_recent_logs(workspace)
            raise AssertionError(
                f"Invariant violation [HANDOFF_SIZE] at cycle {cycle} (seed={seed}): "
                f"handoff.json length is {chars} > {cls.MAX_HANDOFF_CHARS} characters.\n"
                f"Last 20 log lines:\n{recent}"
            )
        repeats = len(re.findall(r"Session complete after", content))
        if repeats > 1:
            recent = cls._get_recent_logs(workspace)
            raise AssertionError(
                f"Invariant violation [HANDOFF_REPEATS] at cycle {cycle} (seed={seed}): "
                f"'Session complete after' appears {repeats} times in handoff (max allowed is 1).\n"
                f"Last 20 log lines:\n{recent}"
            )

    @classmethod
    def check_plan(cls, cycle: int, seed: int, workspace: Path) -> None:
        """Invariant: plan items <= cap, cycle logs plan_updated OR plan_unchanged."""
        plan_path = workspace / "state" / "plan.json"
        if plan_path.exists():
            try:
                data = json.loads(plan_path.read_text(encoding="utf-8"))
                items = data.get("items", [])
                if len(items) > cls.MAX_PLAN_ITEMS:
                    recent = cls._get_recent_logs(workspace)
                    raise AssertionError(
                        f"Invariant violation [PLAN_CAP] at cycle {cycle} (seed={seed}): "
                        f"Plan contains {len(items)} items > cap {cls.MAX_PLAN_ITEMS}.\n"
                        f"Last 20 log lines:\n{recent}"
                    )
            except json.JSONDecodeError:
                pass

        # Check actions log for plan activity in this cycle
        log_path = workspace / "logs" / "actions.jsonl"
        if log_path.exists() and cycle > 0:
            found_plan_activity = False
            for line in reversed(log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-100:]):
                try:
                    ev = json.loads(line)
                    if ev.get("event") in {"plan_updated", "plan_unchanged"}:
                        if ev.get("cycle") == cycle:
                            found_plan_activity = True
                            break
                except Exception:
                    continue
            if not found_plan_activity:
                recent = cls._get_recent_logs(workspace)
                raise AssertionError(
                    f"Invariant violation [PLAN_ACTIVITY] at cycle {cycle} (seed={seed}): "
                    f"No plan_updated or plan_unchanged event logged for cycle {cycle}.\n"
                    f"Last 20 log lines:\n{recent}"
                )

    @classmethod
    def check_memory(cls, cycle: int, seed: int, workspace: Path) -> None:
        """Invariant: persistent memory entries <= cap."""
        mem_path = workspace / "memory" / "memory.jsonl"
        if mem_path.exists():
            lines = [l for l in mem_path.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]
            if len(lines) > cls.MAX_MEMORY_ENTRIES:
                recent = cls._get_recent_logs(workspace)
                raise AssertionError(
                    f"Invariant violation [MEMORY_CAP] at cycle {cycle} (seed={seed}): "
                    f"Memory contains {len(lines)} entries > cap {cls.MAX_MEMORY_ENTRIES}.\n"
                    f"Last 20 log lines:\n{recent}"
                )

    @classmethod
    def check_daily_ledger(cls, cycle: int, seed: int, workspace: Path) -> None:
        """Invariant: daily ledger <= cap, no leaked token reservations."""
        budget_path = workspace / "state" / "daily_token_budget.json"
        if budget_path.exists():
            try:
                data = json.loads(budget_path.read_text(encoding="utf-8"))
                used = data.get("tokens_used", 0)
                cap = data.get("max_tokens_per_day", 200_000)
                if used > cap:
                    recent = cls._get_recent_logs(workspace)
                    raise AssertionError(
                        f"Invariant violation [DAILY_LEDGER_EXCEEDED] at cycle {cycle} (seed={seed}): "
                        f"tokens_used {used} exceeds daily cap {cap}.\n"
                        f"Last 20 log lines:\n{recent}"
                    )
                # Check active unreleased reservations
                reservations = data.get("active_reservations", {})
                if isinstance(reservations, dict) and reservations:
                    recent = cls._get_recent_logs(workspace)
                    raise AssertionError(
                        f"Invariant violation [LEAKED_RESERVATION] at cycle {cycle} (seed={seed}): "
                        f"Leaked active token reservations found: {reservations}.\n"
                        f"Last 20 log lines:\n{recent}"
                    )
            except json.JSONDecodeError:
                pass

    @classmethod
    def check_audit_trail(cls, cycle: int, seed: int, workspace: Path, coordinator: WakeCoordinator | None = None) -> None:
        """Invariant: hash chain / audit trail verifies sequential integrity."""
        if coordinator is not None and getattr(coordinator, "audit_trail", None) is not None:
            valid, count, error = coordinator.audit_trail.verify()
            if not valid:
                recent = cls._get_recent_logs(workspace)
                raise AssertionError(
                    f"Invariant violation [AUDIT_TRAIL_CHAIN] at cycle {cycle} (seed={seed}): "
                    f"Audit trail integrity check failed at record {count}: {error}.\n"
                    f"Last 20 log lines:\n{recent}"
                )

    @classmethod
    def check_log_growth(cls, cycle: int, seed: int, workspace: Path, prior_bytes: int) -> int:
        """Invariant: actions.jsonl growth per cycle under stated bound (exempting full session start)."""
        log_path = workspace / "logs" / "actions.jsonl"
        current_bytes = log_path.stat().st_size if log_path.exists() else 0
        delta = current_bytes - prior_bytes
        # Specification: no single cycle > 25,000 bytes unless full session start
        cap = cls.MAX_CYCLE_LOG_GROWTH_BYTES * 2 if cycle == 1 else cls.MAX_CYCLE_LOG_GROWTH_BYTES
        if delta > cap:
            recent = cls._get_recent_logs(workspace)
            raise AssertionError(
                f"Invariant violation [LOG_GROWTH] at cycle {cycle} (seed={seed}): "
                f"actions.jsonl grew by {delta} bytes in cycle {cycle} > cap {cap}.\n"
                f"Last 20 log lines:\n{recent}"
            )
        return current_bytes

    @classmethod
    def check_stop_pause(cls, cycle: int, seed: int, workspace: Path, finish_reason: str) -> None:
        """Invariant: STOP and PAUSE are honored within the same cycle."""
        stop_file = workspace / "STOP"
        if stop_file.exists():
            if finish_reason not in {"stop_file", "stop_watcher", "broker_panic"}:
                recent = cls._get_recent_logs(workspace)
                raise AssertionError(
                    f"Invariant violation [STOP_NOT_HONORED] at cycle {cycle} (seed={seed}): "
                    f"STOP file present but run finished with reason {finish_reason!r}.\n"
                    f"Last 20 log lines:\n{recent}"
                )

    @classmethod
    def check_cycle(cls, cycle: int, seed: int, runner: SoakRunner) -> None:
        """Execute all per-cycle invariant checks."""
        ws = runner.workspace
        cls.check_handoff(cycle, seed, ws)
        cls.check_plan(cycle, seed, ws)
        cls.check_memory(cycle, seed, ws)
        cls.check_daily_ledger(cycle, seed, ws)
        cls.check_audit_trail(cycle, seed, ws, runner.coordinator)
        runner.last_log_bytes = cls.check_log_growth(cycle, seed, ws, runner.last_log_bytes)


# -----------------------------------------------------------------------------
# 6. Soak Runner
# -----------------------------------------------------------------------------

@dataclass
class CycleMetric:
    cycle: int
    handoff_chars: int
    plan_items: int
    memory_entries: int
    log_bytes: int
    tokens_used: int


@dataclass
class SoakRunResult:
    iterations: int
    finish_reason: str
    tokens_used: int
    metrics: list[CycleMetric] = field(default_factory=list)
    seed: int = 42
    invariants_passed: bool = True
    error: str | None = None


class SoakRunner:
    """Orchestrates deterministic multi-cycle execution with per-cycle invariant checking."""

    def __init__(
        self,
        workspace: Path | None = None,
        provider: ScriptedProvider | None = None,
        max_iterations: int = 30,
        seed: int = 42,
        daily_cap: int = 200_000,
        clock: FakeClock | None = None,
        invariants: Invariants | None = None,
    ) -> None:
        self.is_temp_workspace = workspace is None
        self.workspace = workspace or Path(tempfile.mkdtemp(prefix="soak_ws_"))
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.seed = seed
        random.seed(seed)
        self.max_iterations = max_iterations
        self.daily_cap = daily_cap
        self.clock = clock or FakeClock()
        self.provider = provider or ScriptedProvider()
        self.invariants = invariants or Invariants()
        self.last_log_bytes = 0
        self.metrics: list[CycleMetric] = []

        # Build coordinator with scripted provider
        self.coordinator = WakeCoordinator(
            workspace=self.workspace,
            max_iterations=self.max_iterations,
            llm_client=self.provider,
        )
        self.coordinator.daily_ledger.cap = daily_cap

        # Wire per-cycle checkpoint and invariant hook
        orig_checkpoint = self.coordinator._checkpoint_cycle

        def _soak_checkpoint_hook(cycle: int, report: str, tokens: int) -> None:
            # 1. Force durable handoff checkpoint every cycle for invariant verification
            self.coordinator.sessions.checkpoint(
                self.coordinator.status.session_id,
                self.coordinator._make_handoff(report, "checkpoint"),
                cycle,
                tokens,
            )
            orig_checkpoint(cycle, report, tokens)

            # 2. Record cycle metrics
            h_len = 0
            h_path = self.workspace / "state" / "handoff.json"
            if h_path.exists():
                h_len = len(h_path.read_text(encoding="utf-8", errors="replace"))

            p_len = len(self.coordinator.plan_store.items) if self.coordinator.plan_store else 0

            m_count = 0
            m_path = self.workspace / "memory" / "memory.jsonl"
            if m_path.exists():
                m_count = len([l for l in m_path.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()])

            log_b = (self.workspace / "logs" / "actions.jsonl").stat().st_size if (self.workspace / "logs" / "actions.jsonl").exists() else 0

            metric = CycleMetric(
                cycle=cycle,
                handoff_chars=h_len,
                plan_items=p_len,
                memory_entries=m_count,
                log_bytes=log_b,
                tokens_used=tokens,
            )
            self.metrics.append(metric)

            # 3. Check invariants after every cycle
            self.invariants.check_cycle(cycle, self.seed, self)

        self.coordinator._checkpoint_cycle = _soak_checkpoint_hook

    def run(self) -> SoakRunResult:
        """Run the real loop through the coordinator for up to max_iterations."""
        try:
            summary = self.coordinator.run()
            reason = getattr(summary, "reason", "clean_shutdown")
            iters = getattr(summary, "iterations", 0)
            tokens = getattr(summary, "tokens_used", 0)

            # Check final invariants
            self.invariants.check_handoff(iters, self.seed, self.workspace)
            self.invariants.check_daily_ledger(iters, self.seed, self.workspace)
            self.invariants.check_audit_trail(iters, self.seed, self.workspace, self.coordinator)
            self.invariants.check_stop_pause(iters, self.seed, self.workspace, reason)

            return SoakRunResult(
                iterations=iters,
                finish_reason=reason,
                tokens_used=tokens,
                metrics=self.metrics,
                seed=self.seed,
                invariants_passed=True,
            )
        except Exception as exc:
            return SoakRunResult(
                iterations=len(self.metrics),
                finish_reason="exception",
                tokens_used=self.metrics[-1].tokens_used if self.metrics else 0,
                metrics=self.metrics,
                seed=self.seed,
                invariants_passed=False,
                error=f"{type(exc).__name__}: {exc}",
            )

    def close(self) -> None:
        """Clean up resources and temporary workspace."""
        try:
            self.coordinator.close()
        except Exception:
            pass
        if self.is_temp_workspace and self.workspace.exists():
            shutil.rmtree(self.workspace, ignore_errors=True)


# -----------------------------------------------------------------------------
# 7. Trend and Growth Fitting Utilities
# -----------------------------------------------------------------------------

def linear_slope(series: list[float | int]) -> float:
    """Compute the linear regression slope of a series against index."""
    n = len(series)
    if n <= 1:
        return 0.0
    x_mean = (n - 1) / 2.0
    y_mean = sum(series) / float(n)
    numerator = sum((i - x_mean) * (y - y_mean) for i, y in enumerate(series))
    denominator = sum((i - x_mean) ** 2 for i in range(n))
    return numerator / denominator if denominator > 0 else 0.0
