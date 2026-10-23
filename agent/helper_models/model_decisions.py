"""Bounded helper delegation and base-model decision checkpoints facade."""
from __future__ import annotations

import os
from pathlib import Path
import sys
from typing import Any

from agent.helper_models.decisions.build_routes import (
    build_route_stats as _build_route_stats,
    record_build_outcome as _record_build_outcome,
    record_build_route as _record_build_route,
)
from agent.helper_models.decisions.history_log import (
    append_decision_record,
    migrate_legacy_records,
    print_decision_summary,
    read_last_decisions,
)
from agent.helper_models.decisions.routing_matrix import (
    CHECKPOINT_CONTEXT_CHARS,
    CHECKPOINT_SUMMARY_CHARS,
    FAILURE_COOLDOWN_SECONDS,
    MAX_DELEGATION_PROMPT_CHARS,
    MAX_RETURN_CHARS,
    RAW_RESPONSE_CAP,
    _first_json_object,
    _text,
    execute_ask_model,
    execute_decide_model,
    get_available_models,
)
from agent.helper_models.decisions.summary_entry import build_summary_entry
from agent.helper_models.decisions.task_tracking import (
    record_delegation_outcome as _record_delegation_outcome,
    record_task_observation as _record_task_observation,
    record_task_outcomes as _record_task_outcomes,
    record_tool_outcome as _record_tool_outcome,
    task_provider_errors as _task_provider_errors,
)
from agent.helper_models.model_outcomes import (
    BuildOutcomes,
    ModelOutcomes,
    SELF_REPORTED_USEFULNESS,
    VALID_BUILD_RESULTS,
    VALID_BUILD_ROUTES,
)
from agent.infra.event_log import EventLogger
from agent.llm.model_registry import ModelRegistry

MAX_CHECKPOINTS_PER_SESSION = 0  # Deprecated: checkpoint cap removed
CHECKPOINT_OUTPUT_TOKENS = 32_768  # Deprecated: replaced by registry ceiling
RETRY_OUTPUT_TOKENS = 32_768  # Deprecated: replaced by registry ceiling
MAX_DELEGATION_OUTPUT_TOKENS = 32_768  # Deprecated: replaced by registry ceiling


class ModelDecisions:
    """Persist model-routing decisions and delegation outcomes."""

    def __init__(
        self,
        workspace: str | Path,
        logger: EventLogger,
        registry: ModelRegistry,
        llm: Any,
        session_id: str,
    ) -> None:
        self.path = Path(workspace) / "state" / "model_decisions.jsonl"
        self.task_path = self.path.with_name("model_task_observations.jsonl")
        self.lock_path = self.path.with_suffix(".lock")
        self.cap_path = self.path.with_name(".checkpoint_cap.json")
        self.logger = logger
        self.registry = registry
        self.llm = llm
        self.session_id = session_id
        self.outcomes = ModelOutcomes(workspace, logger)
        self.build_outcomes = BuildOutcomes(workspace, logger)
        self.active_task_id: str | None = None
        self.task_calls: list[tuple[str, str, str]] = []
        self.successful_helper_calls: set[str] = set()
        self.extra_provider_errors = 0
        self.last_checkpoint_call_id: str | None = None
        self._cached_choices: dict[str, tuple[str, str]] = {}
        self._last_tool_name: str | None = None
        self.defaulted_decisions_count = 0
        try:
            self.failure_cooldown_seconds = max(
                0,
                min(
                    86_400,
                    int(os.getenv("SELF_MODEL_FAILURE_COOLDOWN_SECONDS", str(FAILURE_COOLDOWN_SECONDS))),
                ),
            )
        except ValueError:
            self.failure_cooldown_seconds = FAILURE_COOLDOWN_SECONDS
        self._client_records_stats = (
            getattr(getattr(llm, "client", None), "model_registry", None) is registry
        )
        self._migrate_legacy_records()

    def _append(self, record: dict[str, Any]) -> None:
        append_decision_record(self.path, self.lock_path, self.logger, record)

    def _migrate_legacy_records(self) -> None:
        """Preserve earlier observations while marking missing decision evidence."""
        migrate_legacy_records(self.path, self.task_path, self.lock_path)

    def last_decisions(self, limit: int | None = 10) -> list[dict[str, Any]]:
        """Return the most recent persisted model decisions."""
        return read_last_decisions(self.path, limit=limit)

    def _available(self) -> dict[str, dict[str, Any]]:
        return get_available_models(self.registry, self.failure_cooldown_seconds)

    def start_task(self, task_id: str) -> None:
        """Start a tracked task so later outcomes can be attributed to it."""
        self.active_task_id = task_id
        self.task_calls = []
        self.successful_helper_calls = set()
        self.extra_provider_errors = 0
        self._cached_choices.clear()
        self._last_tool_name = None

    def record_provider_error(self) -> None:
        """Associate a provider error with the active tracked task."""
        if self.active_task_id:
            self.extra_provider_errors += 1
        self._cached_choices.clear()

    def _track_call(self, call_id: str, model: str, source: str) -> None:
        if self.active_task_id:
            self.task_calls.append((call_id, model, source))

    def record_delegation_outcome(self, call_id: str, usefulness: str, note: str) -> dict[str, Any]:
        """Persist the observed result of a helper-model delegation."""
        return _record_delegation_outcome(self, call_id, usefulness, note)

    def record_task_outcomes(
        self,
        task_id: str,
        *,
        completed: bool,
        iterations: int,
        tool_errors: int,
        provider_errors: int,
    ) -> None:
        """Persist task-level outcome signals after a tracked run."""
        _record_task_outcomes(
            self,
            task_id,
            completed=completed,
            iterations=iterations,
            tool_errors=tool_errors,
            provider_errors=provider_errors,
        )

    def task_provider_errors(self) -> int:
        """Return provider errors recorded for a task."""
        return _task_provider_errors(self)

    def record_tool_outcome(
        self,
        *,
        tool_name: str,
        attempt: int,
        critic_call_id: str | None,
        critic_model: str,
        critic_approved: bool | None,
        tests_passed: bool | None,
        registered: bool,
    ) -> None:
        """Persist an outcome signal for a generated tool."""
        _record_tool_outcome(
            self,
            tool_name=tool_name,
            attempt=attempt,
            critic_call_id=critic_call_id,
            critic_model=critic_model,
            critic_approved=critic_approved,
            tests_passed=tests_passed,
            registered=registered,
        )

    @staticmethod
    def _summary_entry(entry: dict[str, Any]) -> dict[str, Any]:
        return build_summary_entry(entry)

    def record_task_observation(
        self,
        task_id: str,
        task: str,
        ask_model_followed: bool,
    ) -> None:
        """Record an objective observation for delegated or baseline work."""
        _record_task_observation(self, task_id, task, ask_model_followed)

    def ask_model(
        self,
        model: str,
        prompt: str,
        task_type: str,
        reason: str,
        expected_benefit: str,
    ) -> dict[str, Any]:
        """Delegate a task to an eligible helper and persist the decision."""
        return execute_ask_model(self, model, prompt, task_type, reason, expected_benefit)

    def decide_model(
        self,
        context: str,
        options: list[str] | None = None,
        *,
        moment: str,
        tool_name: str | None = None,
    ) -> str:
        """Choose a model for a checkpoint and record the choice origin."""
        return execute_decide_model(self, context, options, moment=moment, tool_name=tool_name)

    def record_build_route(
        self,
        task: str,
        route: str,
        reasons: str,
        expected_effort: str,
        forced_by: str | None = None,
    ) -> dict[str, Any]:
        """Record a decision to build via 'self' or delegate to 'opencode'."""
        return _record_build_route(self, task, route, reasons, expected_effort, forced_by)

    def record_build_outcome(
        self,
        task_id: str,
        result: str,
        notes: str | None = None,
        *,
        route: str | None = None,
        duration: float = 0.0,
        acceptance_passed: bool | None = None,
        retries: int = 0,
        provider: str | None = None,
        model: str | None = None,
        forced_by: str | None = None,
    ) -> dict[str, Any]:
        """Record the outcome of a build task (for route 'self' or manual completion)."""
        return _record_build_outcome(
            self,
            task_id,
            result,
            notes,
            route=route,
            duration=duration,
            acceptance_passed=acceptance_passed,
            retries=retries,
            provider=provider,
            model=model,
            forced_by=forced_by,
        )

    def build_route_stats(
        self,
        limit: int = 10,
        opencode_status: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Compute summary statistics and recent records for build routes."""
        return _build_route_stats(self, limit=limit, opencode_status=opencode_status)


if __name__ == "__main__":
    print_decision_summary(sys.argv[1] if len(sys.argv) > 1 else "/home/entity")

__all__ = [
    "ModelDecisions",
    "print_decision_summary",
    "MAX_DELEGATION_PROMPT_CHARS",
    "MAX_RETURN_CHARS",
    "CHECKPOINT_CONTEXT_CHARS",
    "CHECKPOINT_SUMMARY_CHARS",
    "RAW_RESPONSE_CAP",
    "FAILURE_COOLDOWN_SECONDS",
    "MAX_CHECKPOINTS_PER_SESSION",
    "CHECKPOINT_OUTPUT_TOKENS",
    "RETRY_OUTPUT_TOKENS",
    "MAX_DELEGATION_OUTPUT_TOKENS",
    "_text",
    "_first_json_object",
]
