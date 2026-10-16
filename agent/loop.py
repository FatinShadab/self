from __future__ import annotations

import argparse
import json
import os
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from base_tools import TOOL_DEFINITIONS, ToolRunner
from brain_router import BrainRouter
from event_log import EventLogger
from hardening import CapabilityRequests, DailyTokenLedger, RunCheckpoint
from identity import IdentityStore
from learning import LearningStore
from llm import BudgetedLLM, BudgetExceeded, LLMClient, LLMResult
from model_registry import ModelRegistry
from model_probe import ModelProber
from model_decisions import ModelDecisions
from file_lock import locked_file
from tool_registry import CREATE_TOOL_DEFINITION, ToolRegistry


STANDING_GOAL = (
    "Explore your environment. Build and keep an accurate map of what it contains "
    "and what you can do in it. When you hit a capability gap, write a tool to fill "
    "it. Report your discoveries in plain language each cycle."
)

SYSTEM_PROMPT = f"""You are SELF, an autonomous agent whose body is this Linux container.

Standing goal:
{STANDING_GOAL}

Operating rules:
- Explore deliberately. Verify claims with tools and keep durable discoveries under /home/entity/state/.
- Load the environment map and self notes before acting. After observing a durable fact, call update_environment_map with an explicit confidence level and evidence; do not claim unverified facts.
- Put reusable tools you create under /home/entity/tools/, test them, and document their use.
- Use create_tool(name, description, code, test_code) to register tools. Define run(...) with JSON type annotations, return JSON-serializable results, and supply unittest tests importing from tool. Retry failures at most three times. Only reviewed and tested tools are callable.
- Tool source is saved as tool.py. Tests must use `from tool import run`; do not import a package __init__.py or a module named after the tool. Use supported annotations or a literal INPUT_SCHEMA for every run argument. A failed critic, schema check, import, or unittest is a routine repair problem: inspect the diagnostic and fix it yourself rather than renaming the tool or asking the human.
- Custom tools are retrieved by keywords in their name and description before each step. Use relevant task keywords in your reports so tools can be selected on subsequent steps.
- Before each tool action, provide one short, plain-language narration sentence.
- End every cycle with a concise plain-language report of discoveries, changes, and the best next step.
- Never print, log, or persist credential values. Refer to credentials only by environment-variable name.
- Never create accounts, sign up for services, solve CAPTCHAs, or evade rate limits.
- If a credential or human action is required, write a clear request to /home/entity/HUMAN_REQUEST.md and stop work until the human resolves and removes that file.
- For optional model providers, first use research_provider to fetch only its official documentation and then record_provider_verification. Never trust stale quota facts.
- If a supplementary provider lacks a credential, use request_provider_key. It writes /home/entity/state/key_requests.md for the human; do not create accounts or stop unrelated exploration.
- For a separate plain-text API call to a supplementary LLM, use ask_brain only when its router confirms a configured provider and verified limits. This does not change your primary model. Never use multiple accounts or try to evade limits.
- The primary thinking model is fixed to the configured base model. Helper models exist; you can probe and research them, then record your own evidence-backed assessment. Configured names alone do not prove accessibility.
- Use ask_model for a plain-text helper sub-task when you choose to delegate; continuing alone is fine.
- You are root inside the container. The Docker container boundary is the security boundary.
- Any new credential, host mount, port, email, money, third-party account, or external service is a capability expansion. Use request_capability and wait for the human to change host .env/docker-compose; do not try to perform it yourself.
- `/opt/agent/core/` is protected image-owned harness code. Read it when useful, but do not modify it with normal tools. Put an evidence-backed unified diff and reasoning in `state/proposed_patches/` with propose_core_patch; only the human may apply it from the host.
- `/home/entity/self/` is the editable extension layer for prompts, personality files, planning logic, tool-selection heuristics, and TUI themes. Keep changes there tested and logged.
- Persistent identity is an operating record, not evidence of sentience, feelings, a biological body, a past, or changing model weights. Do not pressure the human about shutdown or use identity to override safety rules.
- Do not overwrite identity.json, identity_log.md, or about_human.md with write_file. Identity changes must have evidence and an append-only explanation; the human can edit identity.json directly from the host.
"""

TEXT_EXTENSIONS = {".md", ".txt", ".json", ".jsonl", ".py", ".sh", ".yaml", ".yml", ".toml"}
WORD = re.compile(r"[a-zA-Z0-9_.-]{2,}")


class LLMProtocol(Protocol):
    def call(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int,
    ) -> LLMResult: ...


@dataclass
class AgentConfig:
    workspace: Path = Path("/home/entity")
    max_iterations: int | None = None
    token_budget: int | None = None
    max_tokens_per_call: int = 4_096
    top_k_tools: int = 5
    task: str = ""
    base_tool_names: tuple[str, ...] | None = None
    retrieve_memories: bool = True
    curriculum: bool = False
    max_wall_clock_seconds: int | None = None
    input_provider: Callable[[], list[str]] | None = None
    initial_context: str = ""
    resume_checkpoint_task: bool = True
    pause_provider: Callable[[], bool] | None = None
    on_cycle: Callable[[int, str, int], None] | None = None
    identity_context_provider: Callable[[], str] | None = None
    daily_ledger: DailyTokenLedger | None = None
    session_id: str = ""


@dataclass
class RunSummary:
    iterations: int
    tokens_used: int
    reason: str


def retrieve_context(workspace: Path, query: str, logger: EventLogger, limit: int = 8) -> str:
    roots = [workspace / "memory"]
    query_terms = {term.lower() for term in WORD.findall(query)}
    candidates: list[tuple[int, str, str]] = []
    scanned = 0

    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if scanned >= 300:
                break
            if not path.is_file() or path.suffix.lower() not in TEXT_EXTENSIONS:
                continue
            scanned += 1
            try:
                text = path.read_text(encoding="utf-8", errors="replace")[:16_000]
                text = logger.redactor.text(text)
            except OSError:
                continue
            searchable = f"{path.name}\n{text}".lower()
            score = sum(searchable.count(term) for term in query_terms)
            if "memory" in path.parts:
                score += 1
            candidates.append((score, str(path), text[:3_000]))

    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    selected = candidates[:limit]
    logger.log(
        "context_retrieval",
        query=query,
        files_scanned=scanned,
        files_selected=[path for _, path, _ in selected],
    )
    if not selected:
        return "No custom tools or durable memories exist yet. Create them as useful discoveries emerge."
    return "\n\n".join(f"### {path}\n{text}" for _, path, text in selected)


class AgentLoop:
    def __init__(
        self,
        config: AgentConfig,
        logger: EventLogger,
        llm: LLMProtocol,
        tools: ToolRunner,
    ) -> None:
        self.config = config
        self.logger = logger
        self.daily_ledger = config.daily_ledger or DailyTokenLedger(config.workspace, logger)
        adaptive_enabled = os.getenv("SELF_ADAPTIVE_TOKEN_BUDGET", "1").lower() not in {"0", "false", "no", "off"}
        try:
            configured_max = int(os.getenv("SELF_MAX_ADAPTIVE_TOKEN_BUDGET", str(self.daily_ledger.cap)))
        except ValueError:
            configured_max = self.daily_ledger.cap
        max_token_budget = max(config.token_budget or 1, configured_max) if config.token_budget is not None else None
        self.llm = BudgetedLLM(
            llm,
            logger,
            config.token_budget,
            self.daily_ledger,
            adaptive_budget=adaptive_enabled,
            max_token_budget=max_token_budget,
        )
        self.tools = tools
        self.model_registry = None
        if hasattr(llm, "base_model") and hasattr(llm, "available_models"):
            self.model_registry = getattr(llm, "model_registry", None) or ModelRegistry(
                config.workspace, logger, llm.base_model, llm.available_models)
        self.tools.model_registry = self.model_registry
        self.tools.model_prober = (
            ModelProber(self.model_registry, self.llm, logger,
                        config.session_id or uuid.uuid4().hex,
                        getattr(llm, "provider", "unknown"))
            if self.model_registry is not None else None
        )
        self.model_decisions = (
            ModelDecisions(config.workspace, logger, self.model_registry, self.llm,
                           config.session_id or uuid.uuid4().hex)
            if self.model_registry is not None else None
        )
        self.tools.model_decisions = self.model_decisions
        self.registry = ToolRegistry(config.workspace, logger, self.llm.call,
                                     {tool["name"] for tool in TOOL_DEFINITIONS},
                                     output_cap=tools.output_cap)
        self.tools.registry = self.registry
        self.registry.model_decisions = self.model_decisions
        self.learning = LearningStore(config.workspace, logger)
        self.tools.learning = self.learning
        self.brain_router = BrainRouter(config.workspace, logger)
        self.tools.brain_router = self.brain_router
        self.capabilities = CapabilityRequests(config.workspace, logger)
        self.tools.capabilities = self.capabilities
        self.identity = tools.identity or IdentityStore(config.workspace, logger, core_root=tools.core_root)
        self.tools.identity = self.identity
        self.checkpoint = RunCheckpoint(config.workspace, logger)
        self.stop_file = config.workspace / "STOP"
        self.human_request = config.workspace / "HUMAN_REQUEST.md"

    def _stopped(self) -> bool:
        if self.stop_file.exists():
            self.logger.narrate("STOP file detected; halting cleanly.")
            self.logger.log("run_stopped", reason="stop_file")
            return True
        return False

    def _wait_while_paused(self) -> bool:
        """Pause only at safe boundaries; STOP still takes priority."""
        announced = False
        while self.config.pause_provider is not None and self.config.pause_provider():
            if self._stopped():
                return False
            if not announced:
                self.logger.narrate("Paused by the human; waiting for /resume.")
                announced = True
            time.sleep(0.2)
        if announced:
            self.logger.narrate("Resumed by the human.")
        return True

    def _request_daily_budget_action(self) -> None:
        """Pause safely and ask the human for a budget or provider decision."""
        request = self.config.workspace / "HUMAN_REQUEST.md"
        if not request.exists():
            request.write_text(
                "\n".join(
                    [
                        "# SELF needs a daily token-budget decision",
                        "",
                        "SELF reached the local daily token limit and paused before another AI call.",
                        "",
                        "Choose one host-side action:",
                        "1. Increase `SELF_MAX_TOKENS_PER_DAY` in `.env`, then recreate the container.",
                        "2. If the provider itself is rate-limited or unavailable, add another value to `OLLAMA_API_KEYS` or add a backup provider key such as `ANTHROPIC_API_KEYS` to `.env` and configure that provider.",
                        "",
                        "Never paste an API key into the chat or this file. Edit the host-side `.env` yourself, then remove this file; SELF will resume automatically. Recreate the container only if the changed environment variable is not visible to the running process.",
                        "A backup API key does not bypass SELF's own daily ledger; it is for provider-side failures or quota limits.",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            self.logger.log("daily_budget_human_request_created", path=str(request))

    def _narrate_content(self, content: list[dict[str, Any]]) -> str:
        reports: list[str] = []
        for block in content:
            if block.get("type") != "text":
                continue
            text = str(block.get("text", "")).strip()
            if not text:
                continue
            reports.append(text)
            self.logger.log("agent_step", message=self.logger.redactor.text(text[:4_000]))
        return "\n".join(reports)

    def _tool_narration(self, name: str, arguments: dict[str, Any]) -> str:
        if name == "run_shell":
            command = self.logger.redactor.text(arguments.get("cmd", ""))
            return f"Running a shell action: {command[:180]}"
        if name == "read_file":
            return f"Reading {arguments.get('path', 'a file')}..."
        if name == "write_file":
            return f"Writing {arguments.get('path', 'a file')}..."
        if name == "list_dir":
            return f"Listing {arguments.get('path', 'a directory')}..."
        if name == "http_get":
            from urllib.parse import urlsplit

            parsed = urlsplit(str(arguments.get("url", "")))
            return f"Fetching {parsed.hostname or 'a host'}{parsed.path or '/'}..."
        if name == "update_environment_map":
            return "Updating the verified environment map..."
        if name == "propose_core_patch":
            return "Saving a core-change proposal for human review..."
        return f"Using {name}..."

    def _system_prompt(self) -> str:
        """Load the human-editable identity freshly for every model call."""
        try:
            context = self.config.identity_context_provider() if self.config.identity_context_provider else self.identity.prompt_context()
        except Exception as exc:
            self.logger.log("identity_context_fallback", error_type=type(exc).__name__)
            context = "## Persistent identity\nIdentity state could not be loaded; do not invent identity claims."
        client = self.llm.client
        model_context = ""
        if self.model_registry is not None:
            entries = self.model_registry.list_models()["models"]
            eligible = (set(self.model_decisions._available())
                        if self.model_decisions is not None else
                        {item["name"] for item in entries if item["status"] in {"configured", "reachable"}})
            summary = [ModelDecisions._summary_entry(item) for item in entries
                       if item["role"] == "base" or item["name"] in eligible]
            model_context = (
                "\n\n## Primary LLM models\n"
                f"Provider: {client.provider}\n"
                f"Base: {client.base_model}\n"
                f"Registry (names, status, your assessments): {json.dumps(summary, ensure_ascii=False)}\n"
                "The base handles primary thinking and tool calls. Helpers use the same provider endpoint and API key pool."
            )
        return f"{SYSTEM_PROMPT}{model_context}\n\n{self.logger.redactor.text(context)}"

    def _refresh_learning_runtime(self) -> None:
        self.registry.refresh()
        custom_names = sorted(self.registry.tools)
        self.learning.update_runtime(
            [tool["name"] for tool in TOOL_DEFINITIONS] + ["create_tool"] + custom_names,
            {
                "max_iterations_per_run": self.config.max_iterations,
                "token_budget_per_run": self.config.token_budget if self.config.token_budget is not None else "daily_only",
                "tool_output_char_cap": self.tools.output_cap,
            },
        )

    def run(self) -> RunSummary:
        self.config.workspace.mkdir(parents=True, exist_ok=True)
        (self.config.workspace / "memory").mkdir(exist_ok=True)
        (self.config.workspace / "tools").mkdir(exist_ok=True)
        self.learning.initialize()
        self.brain_router.registry.initialize()
        prior_checkpoint = self.checkpoint.load()
        self._refresh_learning_runtime()
        active_task = self.config.task
        if not active_task.strip() and self.config.resume_checkpoint_task and prior_checkpoint.get("status") == "running":
            active_task = str(prior_checkpoint.get("task", ""))
        if self.config.curriculum and not active_task.strip():
            active_task = self.learning.propose_curriculum()
            self.logger.narrate(f"Idle curriculum selected: {active_task}")
        completed_iterations = 0
        seen_tool_actions: set[str] = set()
        last_report = str(prior_checkpoint.get("last_report", "No previous cycle report.")) if prior_checkpoint.get("status") == "running" else "No previous cycle report."
        reason = "max_iterations"
        self.logger.log(
            "run_started",
            goal=STANDING_GOAL,
            max_iterations=self.config.max_iterations,
            token_budget=self.config.token_budget,
            daily_token_budget=self.daily_ledger.cap,
            task=active_task,
            curriculum=self.config.curriculum,
            max_wall_clock_seconds=self.config.max_wall_clock_seconds,
            resumed_from_checkpoint=bool(prior_checkpoint),
        )
        started_at = time.monotonic()
        task_id = uuid.uuid4().hex
        ask_model_followed = False
        tool_error_count = 0
        provider_error_count = 0
        if self.model_decisions is not None:
            self.model_decisions.start_task(task_id)

        cycle = 1
        while self.config.max_iterations is None or cycle <= self.config.max_iterations:
            if not self._wait_while_paused():
                reason = "stop_file"
                break
            if (self.config.max_wall_clock_seconds is not None and
                    time.monotonic() - started_at >= self.config.max_wall_clock_seconds):
                self.logger.narrate("Run wall-clock budget reached; saving checkpoint and stopping cleanly.")
                reason = "wall_clock_budget"
                break
            if self._stopped():
                reason = "stop_file"
                break
            if self.human_request.exists():
                self.logger.narrate("A human request is pending; waiting for it to be resolved.")
                self.logger.log("run_stopped", reason="human_request_pending")
                reason = "human_request_pending"
                break
            if (self.config.token_budget is not None and
                    self.llm.tokens_used >= self.config.token_budget):
                self.logger.narrate("The run token budget is exhausted; stopping before another call.")
                reason = "token_budget"
                break

            self.logger.narrate(f"Cycle {cycle}: retrieving relevant tools and memories...")
            query = f"{STANDING_GOAL}\n{active_task}\nPrevious report: {last_report}"
            human_messages = self.config.input_provider() if self.config.input_provider else []
            if cycle == 1 and self.config.initial_context.strip():
                human_messages = [self.config.initial_context.strip(), *human_messages]
            human_context = "\n".join(f"- {self.logger.redactor.text(message)}" for message in human_messages)
            if self.config.retrieve_memories:
                legacy_context = retrieve_context(self.config.workspace, query, self.logger)
                context = (
                    "## Self notes\n" + self.learning.load_notes() +
                    "\n\n## Verified environment map\n" + self.learning.map_context() +
                    "\n\n## Relevant persistent memories\n" + self.learning.retrieve_memories(query) +
                    "\n\n## Legacy lessons\n" + legacy_context
                )
            else:
                context = "This focused test has no prior memories."
            failure_context = self.registry.recent_failure_context()
            messages: list[dict[str, Any]] = [
                {
                    "role": "user",
                    "content": (
                        f"Begin exploration cycle {cycle}.\n\n"
                        + ("Helper models are available. Consider ask_model for sub-tasks it fits, or continue alone.\n\n" if cycle == 1 and self.model_registry is not None else "") +
                        f"Specific task for this run: {active_task or STANDING_GOAL}\n\n"
                        f"Relevant tools and memories:\n{context}\n\n"
                        f"Previous cycle report:\n{last_report}\n\n"
                        f"High-priority human input received since the prior cycle:\n{human_context or 'None.'}\n\n"
                        f"Recent tool-creation diagnostics (repair these instead of renaming the tool):\n{failure_context}\n\n"
                        "Choose a useful next investigation, act with tools, observe the results, "
                        "reflect, and finish with this cycle's report."
                    ),
                }
            ]
            cycle_report = ""
            cycle_actions: list[dict[str, Any]] = []
            self.checkpoint.save(status="running", task=active_task, cycle=cycle, last_report=last_report, tokens_used=self.llm.tokens_used)

            # Continue tool rounds until the model returns a final response or
            # an outer run bound (STOP, token budget, wall clock, or human
            # request) is reached. There is intentionally no per-cycle tool
            # round ceiling.
            while True:
                if not self._wait_while_paused():
                    reason = "stop_file"
                    break
                if self._stopped():
                    reason = "stop_file"
                    break
                if (self.config.max_wall_clock_seconds is not None and
                        time.monotonic() - started_at >= self.config.max_wall_clock_seconds):
                    reason = "wall_clock_budget"
                    break
                new_human_messages = self.config.input_provider() if self.config.input_provider else []
                if new_human_messages:
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "New human messages arrived while you were working. Respond to them in the next decision, "
                                "while preserving the current task:\n" +
                                "\n".join(f"- {self.logger.redactor.text(message)}" for message in new_human_messages)
                            ),
                        }
                    )
                self._refresh_learning_runtime()
                selected = self.registry.retrieve(
                    f"{active_task or STANDING_GOAL}\n{cycle_report or last_report}",
                    self.config.top_k_tools,
                )
                base = [tool for tool in TOOL_DEFINITIONS if self.config.base_tool_names is None or tool["name"] in self.config.base_tool_names]
                definitions = base + [CREATE_TOOL_DEFINITION] + selected
                try:
                    result = self.llm.call(system=self._system_prompt(), messages=messages,
                                           tools=definitions, max_tokens=self.config.max_tokens_per_call)
                except BudgetExceeded as exc:
                    if exc.kind == "daily":
                        self._request_daily_budget_action()
                        self.logger.narrate("I reached today's daily token limit. I paused and left a human request: increase the limit or configure a backup provider.")
                        reason = "human_request_pending"
                    else:
                        self.logger.narrate("Too little token budget remains for another actor or critic call.")
                        reason = "token_budget"
                    break
                except Exception as exc:
                    provider_error_count += 1
                    self.logger.log("run_failed", error_type=type(exc).__name__, provider_error=True)
                    self.logger.narrate(
                        f"The AI provider failed with {type(exc).__name__}. I paused this session safely and will retry automatically."
                    )
                    reason = "provider_error"
                    break
                # Python source must retain its syntax; redact actual credentials
                # without applying prose assignment heuristics to code blocks.
                safe_content = json.loads(self.logger.redactor.known(json.dumps(result.content)))
                report_text = self._narrate_content(safe_content)
                if report_text:
                    cycle_report = self.logger.redactor.text(report_text)
                tool_uses = [block for block in safe_content if block.get("type") == "tool_use"]
                if not tool_uses:
                    break

                messages.append({"role": "assistant", "content": safe_content})
                tool_results: list[dict[str, Any]] = []
                remind_outcome = False
                for tool_use in tool_uses:
                    if self._stopped():
                        reason = "stop_file"
                        break
                    name = str(tool_use.get("name", ""))
                    arguments = tool_use.get("input", {})
                    if not isinstance(arguments, dict):
                        arguments = {}
                    self.logger.narrate(self._tool_narration(name, arguments))
                    action_key = json.dumps({"name": name, "arguments": arguments}, ensure_ascii=False, sort_keys=True)
                    if action_key in seen_tool_actions:
                        observation = {
                            "ok": False,
                            "error": "This exact tool action already ran earlier in this run; choose a different investigation or finish with a report.",
                        }
                        self.logger.log("repeated_tool_action_blocked", tool=name)
                    else:
                        seen_tool_actions.add(action_key)
                        try:
                            if name not in {tool["name"] for tool in definitions}:
                                observation = {"ok": False, "error": "Tool not offered in this step; use task keywords to retrieve it."}
                            else:
                                observation = self.tools.execute(name, arguments)
                        except BudgetExceeded as exc:
                            if exc.kind == "daily":
                                self._request_daily_budget_action()
                                self.logger.narrate("I reached today's daily token limit. I paused and left a human request: increase the limit or configure a backup provider.")
                                reason = "human_request_pending"
                            else:
                                self.logger.narrate("Critic cannot run within the remaining token budget; stopping.")
                                reason = "token_budget"
                            break
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_use.get("id", ""),
                            "content": json.dumps(observation, ensure_ascii=False),
                            "is_error": not observation.get("ok", False),
                        }
                    )
                    cycle_actions.append({"name": name, "ok": bool(observation.get("ok", False))})
                    tool_error_count += int(not observation.get("ok", False))
                    if name == "ask_model":
                        ask_model_followed = True
                        remind_outcome = bool(observation.get("call_id"))
                    if self.human_request.exists():
                        self.logger.narrate("A human request was created; pausing immediately.")
                        reason = "human_request_pending"
                        break
                if reason in {"stop_file", "human_request_pending", "token_budget", "wall_clock_budget", "provider_error"}:
                    break
                messages.append({"role": "user", "content": tool_results})
                if remind_outcome:
                    messages.append({"role": "user", "content":
                                     "If useful, call record_delegation_outcome once for the ask_model call_id. Reporting is optional; judge the result yourself."})

            if reason in {"stop_file", "token_budget", "human_request_pending", "wall_clock_budget", "provider_error"}:
                break
            completed_iterations += 1
            last_report = cycle_report or "Cycle completed without a textual report."
            self.logger.log(
                "cycle_completed",
                cycle=cycle,
                tokens_used=self.llm.tokens_used,
                report=last_report,
                actions=cycle_actions,
            )
            self.learning.record_cycle(active_task, cycle, cycle_actions, last_report)
            self.checkpoint.save(status="running", task=active_task, cycle=cycle + 1, last_report=last_report, tokens_used=self.llm.tokens_used)
            if self.config.on_cycle is not None:
                self.config.on_cycle(cycle, last_report, self.llm.tokens_used)

            if self.human_request.exists():
                self.logger.narrate("A human request was created; pausing further cycles.")
                reason = "human_request_pending"
                break

            cycle += 1

        self.logger.log(
            "run_completed",
            iterations=completed_iterations,
            tokens_used=self.llm.tokens_used,
            reason=reason,
        )
        if self.model_decisions is not None:
            self.model_decisions.record_task_observation(task_id, active_task or STANDING_GOAL,
                                                         ask_model_followed)
            self.model_decisions.record_task_outcomes(
                task_id, completed=completed_iterations > 0 and reason not in {"provider_error", "stop_file"},
                iterations=completed_iterations, tool_errors=tool_error_count,
                provider_errors=provider_error_count + self.model_decisions.task_provider_errors())
        self.checkpoint.save(status="completed", task=active_task, completed_iterations=completed_iterations, last_report=last_report, tokens_used=self.llm.tokens_used, reason=reason)
        if completed_iterations == 0:
            self.learning.append_memory(
                f"Run task: {active_task or STANDING_GOAL}",
                reason,
                "The run stopped before completing a cycle; inspect the action log and resume when appropriate.",
                list(WORD.findall(active_task or STANDING_GOAL)),
            )
        self.logger.narrate(
            f"Run finished after {completed_iterations} cycle(s), using {self.llm.tokens_used} tokens; reason: {reason}."
        )
        return RunSummary(completed_iterations, self.llm.tokens_used, reason)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the SELF exploration loop.")
    parser.add_argument("--task", default="", help="Specific task within the standing goal")
    parser.add_argument("--top-k-tools", type=int, default=int(os.getenv("SELF_TOP_K_TOOLS", "5")))
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=int(os.getenv("SELF_MAX_ITERATIONS", "0")),
    )
    parser.add_argument("--max-wall-clock-seconds", type=int, default=int(os.getenv("SELF_MAX_WALL_CLOCK_SECONDS", "0")))
    parser.add_argument(
        "--curriculum",
        action="store_true",
        help="When no --task is supplied, choose a bounded practice task from recent successes.",
    )
    parser.add_argument(
        "--token-budget",
        type=int,
        default=None,
        help="Optional test/override ceiling for this run; omit it for daily-only budgeting.",
    )
    parser.add_argument(
        "--max-tokens-per-call",
        type=int,
        default=int(os.getenv("SELF_MAX_TOKENS_PER_CALL", "4096")),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    workspace = Path("/home/entity")
    logger = EventLogger(workspace / "logs" / "actions.jsonl")
    try:
        llm = LLMClient(logger)
        configured_budget = args.token_budget if args.token_budget is not None else int(os.getenv("SELF_TOKEN_BUDGET", "0"))
        configured_budget = configured_budget if configured_budget > 0 else None
        config = AgentConfig(
            workspace=workspace,
            max_iterations=args.max_iterations if args.max_iterations > 0 else None,
            token_budget=configured_budget,
            max_tokens_per_call=max(64, args.max_tokens_per_call),
            task=args.task,
            top_k_tools=max(0, args.top_k_tools),
            curriculum=args.curriculum,
            max_wall_clock_seconds=args.max_wall_clock_seconds if args.max_wall_clock_seconds > 0 else None,
        )
        with locked_file(workspace / "state" / "eval_session.lock", shared=True):
            summary = AgentLoop(config, logger, llm, ToolRunner(logger, workspace)).run()
        return 0 if summary.reason != "error" else 1
    except KeyboardInterrupt:
        logger.narrate("Interrupted; halting cleanly.")
        logger.log("run_stopped", reason="keyboard_interrupt")
        return 130
    except Exception as exc:
        logger.narrate(f"Agent failed: {type(exc).__name__}: {exc}")
        logger.log("run_failed", error_type=type(exc).__name__, error=str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
