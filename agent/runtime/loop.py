"""SELF loop module - autonomous cycle orchestrator."""
from __future__ import annotations

import argparse
import os
import time
from pathlib import Path
from typing import Any

from agent.infra.event_log import EventLogger
from agent.infra.file_lock import locked_file
from agent.llm.llm import LLMClient
from agent.runtime.config import AgentConfig, LLMProtocol, RunSummary
from agent.runtime.context_retrieval import retrieve_context
from agent.runtime.cycle_prompt import build_system_prompt_for_cycle
from agent.runtime.cycle_runner import run_agent_loop
from agent.runtime.plugin_projects import check_active_plugin_projects
from agent.runtime.prompts import (
    CORE_CAPABILITY_RULE,
    CORE_IDENTITY_RULES,
    CORE_SYSTEM_PROMPT_HEAD,
    OFF_PROMPT_PREFIXES,
    OPENCODE_CAPABILITY_PROMPT,
    ORIENTATION_TASK,
    STANDING_GOAL,
    SYSTEM_PROMPT,
    assemble_system_prompt,
    render_core_system_prompt,
)
from agent.runtime.stop_control import (
    check_is_stopped,
    pause_until_daily_reset,
    request_daily_budget_action,
    wait_while_paused,
)
from agent.runtime.tool_narration import (
    format_content_narration,
    format_tool_narration,
)
from agent.runtime.wiring import wire_loop_collaborators
from agent.tools.base_tools import (
    HELPER_TOOL_NAMES,
    TOOL_DEFINITIONS,
    ToolRunner,
)


class AgentLoop:
    """Run bounded autonomous cycles against an isolated workspace."""

    def __init__(
        self,
        config: AgentConfig,
        logger: EventLogger,
        llm: LLMProtocol,
        tools: ToolRunner,
    ) -> None:
        """Initialize the agent loop with collaborators wired explicitly."""
        self.config = config
        self.logger = logger
        self.tools = tools
        self.reviewed_thresholds: dict[str, set[int]] = {}

        wired = wire_loop_collaborators(config, logger, llm, tools)
        self.daily_ledger = wired.daily_ledger
        self.llm = wired.budgeted_llm
        self.body = wired.body
        self.helper_mode = wired.helper_mode
        self.model_registry = wired.model_registry
        self.max_tokens_per_call = wired.max_tokens_per_call
        self.model_prober = wired.model_prober
        self.model_decisions = wired.model_decisions
        self.registry = wired.registry
        self.learning = wired.learning
        self.plan_store = wired.plan_store
        self.brain_router = wired.brain_router
        self.capabilities = wired.capabilities
        self.identity = wired.identity
        self.checkpoint = wired.checkpoint
        self.plugins = wired.plugins
        self.plugin_dev = wired.plugin_dev
        self.broker = wired.broker
        self.audit_trail = wired.audit_trail
        self.watcher = wired.watcher
        self.stop_file = wired.stop_file
        self.human_request = wired.human_request
        self.harness_human_request = wired.harness_human_request
        self._opencode_status: dict[str, Any] | None = None

    def has_pending_human_request(self) -> bool:
        """Check whether a human request is pending in workspace or harness-owned state."""
        return self.human_request.exists() or self.harness_human_request.exists()

    def _stopped(self) -> bool:
        """Check whether any graceful stop condition is triggered."""
        return check_is_stopped(self.watcher, self.broker, self.stop_file, self.logger)

    def _wait_while_paused(self) -> bool:
        """Pause only at safe boundaries; STOP still takes priority."""
        return wait_while_paused(
            self.config.pause_provider,
            self._stopped,
            self.logger,
            sleep_fn=time.sleep,
        )

    def _request_daily_budget_action(self) -> None:
        """Pause safely and ask the human for a budget or provider decision."""
        request_daily_budget_action(self.config.workspace, self.logger)

    def _pause_until_daily_reset(self) -> None:
        """Pause safely until the daily ledger resets or is increased."""
        pause_until_daily_reset(
            self.daily_ledger,
            self.config.session_id,
            self.config.workspace,
            self.human_request,
            self._stopped,
            self.logger,
            sleep_fn=time.sleep,
        )

    def _narrate_content(self, content: list[dict[str, Any]]) -> str:
        """Extract and log user-visible text blocks from model responses."""
        return format_content_narration(content, self.logger)

    def _tool_narration(self, name: str, arguments: dict[str, Any]) -> str:
        """Return a user-facing narration string for a tool call."""
        return format_tool_narration(name, arguments, self.logger)

    def _check_active_plugin_projects(self, cycle: int) -> str:
        """Check active plugin projects for exploration nudge and stop-loss reviews."""
        return check_active_plugin_projects(
            self.config.workspace,
            self.plan_store,
            self.tools.cost_ledger,
            self.reviewed_thresholds,
            cycle,
        )

    def _system_prompt(self) -> str:
        """Load the human-editable identity freshly for every model call."""
        return build_system_prompt_for_cycle(
            identity=self.identity,
            body=self.body,
            logger=self.logger,
            llm=self.llm,
            model_registry=self.model_registry,
            model_decisions=self.model_decisions,
            plugins=self.plugins,
            helper_mode=self.helper_mode,
            identity_context_provider=self.config.identity_context_provider,
            opencode_status=self._opencode_status,
        )

    def _refresh_learning_runtime(self) -> None:
        """Refresh dynamic custom tool registrations and learning bounds."""
        self.registry.refresh()
        custom_names = sorted(self.registry.tools)
        self.learning.update_runtime(
            [
                tool["name"]
                for tool in TOOL_DEFINITIONS
                if self.helper_mode or tool["name"] not in HELPER_TOOL_NAMES
            ]
            + ["create_tool"]
            + custom_names,
            {
                "max_iterations_per_run": self.config.max_iterations,
                "token_budget_per_run": (
                    self.config.token_budget if self.config.token_budget is not None else "daily_only"
                ),
                "tool_output_char_cap": self.tools.output_cap,
            },
        )

    @staticmethod
    def _format_actions(actions: list[dict[str, Any]]) -> str:
        """Format a summary string of recent actions taken in the current cycle."""
        if not actions:
            return "No previous actions in this run."
        return ", ".join(f"{a.get('name')}(ok={a.get('ok')})" for a in actions[:10])

    def run(self) -> RunSummary:
        """Execute bounded autonomous cycles until finished, stopped, or capped."""
        return run_agent_loop(self)


def parse_args() -> argparse.Namespace:
    """Parse autonomous-loop command-line options."""
    parser = argparse.ArgumentParser(description="Run the SELF exploration loop.")
    parser.add_argument("--task", default="", help="Specific task within the standing goal")
    parser.add_argument("--top-k-tools", type=int, default=int(os.getenv("SELF_TOP_K_TOOLS", "5")))
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=int(os.getenv("SELF_MAX_ITERATIONS", "0")),
    )
    parser.add_argument(
        "--max-wall-clock-seconds",
        type=int,
        default=int(os.getenv("SELF_MAX_WALL_CLOCK_SECONDS", "0")),
    )
    parser.add_argument(
        "--curriculum",
        action="store_true",
        help="When no --task is supplied, choose a bounded practice task from recent successes.",
    )
    parser.add_argument(
        "--token-budget",
        type=int,
        default=None,
        help="Deprecated and ignored; only the daily token limit is enforced.",
    )
    parser.add_argument(
        "--max-tokens-per-call",
        type=int,
        default=None,
        help="Optional per-call output token limit override; defaults to model registry ceiling.",
    )
    return parser.parse_args()


def main() -> int:
    """Parse command-line arguments and run this module's entry point."""
    args = parse_args()
    if args.token_budget is not None:
        import warnings

        warnings.warn(
            "--token-budget is deprecated and ignored; only the daily token limit is enforced.",
            stacklevel=2,
        )
    workspace = Path("/home/entity")
    logger = EventLogger(workspace / "logs" / "actions.jsonl")
    try:
        llm = LLMClient(logger)
        config = AgentConfig(
            workspace=workspace,
            max_iterations=args.max_iterations if args.max_iterations > 0 else None,
            token_budget=None,
            max_tokens_per_call=args.max_tokens_per_call,
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


__all__ = [
    "AgentConfig",
    "AgentLoop",
    "CORE_CAPABILITY_RULE",
    "CORE_IDENTITY_RULES",
    "CORE_SYSTEM_PROMPT_HEAD",
    "LLMProtocol",
    "OFF_PROMPT_PREFIXES",
    "OPENCODE_CAPABILITY_PROMPT",
    "ORIENTATION_TASK",
    "RunSummary",
    "STANDING_GOAL",
    "SYSTEM_PROMPT",
    "assemble_system_prompt",
    "main",
    "parse_args",
    "render_core_system_prompt",
    "retrieve_context",
    "time",
]
