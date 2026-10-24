"""SELF base tools module and primary tool execution coordinator."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from agent.body.base import Body
from agent.infra.event_log import EventLogger
from agent.infra.permission_broker import PermissionBroker, PermissionLevel
from agent.infra.redirect_handler import _LoggingRedirectHandler
from agent.tools.definitions import (
    HELPER_TOOL_NAMES,
    MODEL_TOOL_SPECS,
    TOOL_DEFINITIONS,
    get_tool_definitions,
)
from agent.tools.dispatch import dispatch_tool
from agent.tools.execution.authorization import (
    authorize_tool_action,
    build_action_request,
    record_action_execution,
)
from agent.tools.execution.call_logging import (
    log_tool_call,
    log_tool_result,
    prepare_logged_arguments,
)
from agent.tools.execution.model_arg_validation import validate_model_tool_arguments
from agent.tools.handlers.files import (
    check_is_core_path,
    handle_http_get,
    handle_list_dir,
    handle_read_file,
    handle_run_shell,
    handle_write_file,
)
from agent.tools.handlers.opencode import (
    ensure_model_decisions,
    ensure_opencode,
    get_opencode_tool_definitions,
    handle_apply_delegation,
    handle_build_route_stats,
    handle_delegate_coding,
    handle_discard_delegation,
    handle_opencode_status,
    handle_record_build_outcome,
    handle_record_build_route,
)
from agent.tools.handlers.plan import (
    handle_read_plan,
    handle_update_environment_map,
    handle_update_plan,
)
from agent.tools.handlers.plugin_dev import (
    handle_propose_plugin,
    handle_read_cost_ledger,
    handle_request_plugin_review,
    handle_scaffold_plugin,
    handle_test_plugin,
    handle_validate_plugin,
)
from agent.tools.handlers.provider import (
    handle_ask_brain,
    handle_benchmark_providers,
    handle_probe_local_ollama,
    handle_record_provider_verification,
    handle_request_provider_key,
    handle_research_provider,
)
from agent.tools.handlers.system import (
    handle_propose_core_patch,
    handle_request_capability,
)
from agent.tools.permissions import DEFAULT_OUTPUT_CAP, TOOL_PERMISSION_LEVELS


class ToolRunner:
    """Execute built-in tools subject to workspace and harness boundaries."""

    def __init__(
        self,
        logger: EventLogger,
        workspace: str | Path = "/home/entity",
        output_cap: int | None = None,
        core_root: str | Path = "/opt/agent/core",
        agent_root: str | Path = "/opt/agent",
        body: Body | None = None,
        broker: PermissionBroker | None = None,
        plugin_dev: Any = None,
    ) -> None:
        """Initialize ToolRunner with filesystem boundaries, body, and permission broker."""
        self.logger = logger
        self.workspace = Path(workspace)
        self.core_root = Path(core_root)
        self.agent_root = Path(agent_root)
        self.broker = broker
        self.plugin_dev = plugin_dev
        configured_cap = int(os.getenv("SELF_MAX_OUTPUT_CHARS", str(DEFAULT_OUTPUT_CAP)))
        self.output_cap = max(1_000, output_cap or configured_cap)
        if body is None:
            from agent.body.container import ContainerBody

            body = ContainerBody(
                workspace=self.workspace,
                logger=self.logger,
                core_root=self.core_root,
                agent_root=self.agent_root,
                output_cap=self.output_cap,
            )
        self.body = body
        self.registry: Any = None
        self.learning: Any = None
        self.brain_router: Any = None
        self.capabilities: Any = None
        self._identity: Any = None
        self.model_registry: Any = None
        self.model_prober: Any = None
        self.model_decisions: Any = None
        self.plan_store: Any = None
        self.plugins: Any = None
        self.opencode: Any = None
        self.current_cycle: int = 1
        from agent.infra.cost_ledger import CostLedger

        self.cost_ledger = CostLedger(self.workspace)
        self.review_call: Any = None

    @property
    def identity(self) -> Any:
        """Return the agent identity store."""
        return self._identity

    @identity.setter
    def identity(self, value: Any) -> None:
        """Set the agent identity store and forward to body if supported."""
        self._identity = value
        if hasattr(self.body, "identity"):
            self.body.identity = value

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute a named tool with its supplied arguments under the broker."""
        import time

        if os.getenv("SELF_HELPER_MODELS", "on").strip().lower() != "on" and name in HELPER_TOOL_NAMES:
            return {"ok": False, "error": f"{name} is disabled in this experiment arm"}

        logged_arguments = prepare_logged_arguments(name, arguments, self.logger)
        log_tool_call(self.logger, name, logged_arguments)
        started = time.monotonic()

        action_request = build_action_request(name, arguments, self.plugins) if self.broker is not None else None
        result = authorize_tool_action(self.broker, action_request)

        if result is None:
            arg_err = validate_model_tool_arguments(name, arguments, self.model_registry)
            if arg_err is not None:
                result = arg_err
            else:
                result = dispatch_tool(self, name, arguments)

        safe_result = self.logger.redactor.value(result)
        record_action_execution(self.broker, action_request, safe_result)
        log_tool_result(self.logger, name, safe_result, started)
        return safe_result

    def run_shell(self, cmd: str, timeout: float = 30) -> dict[str, Any]:
        """Run a bounded shell command inside the container."""
        return handle_run_shell(self.body, cmd=cmd, timeout=timeout, plugin_dev=self.plugin_dev)

    def read_plan(self, include_history: bool = False, **arguments: Any) -> dict[str, Any]:
        """Read the persistent plan state."""
        return handle_read_plan(self.plan_store, include_history=include_history, **arguments)

    def update_plan(self, **arguments: Any) -> dict[str, Any]:
        """Update the persistent plan with a required reason citing evidence."""
        return handle_update_plan(
            self.plan_store,
            self.logger,
            self.cost_ledger,
            self.current_cycle,
            self.plugin_dev,
            **arguments,
        )

    def update_environment_map(self, entries: list[dict[str, Any]]) -> dict[str, Any]:
        """Record observed environment facts through the learning store."""
        return handle_update_environment_map(self.learning, entries)

    def research_provider(self, provider: str) -> dict[str, Any]:
        """Fetch official provider information through the router."""
        return handle_research_provider(self.brain_router, provider)

    def record_provider_verification(
        self,
        provider: str,
        free_tier: dict[str, Any],
        models: list[str],
        strengths: list[str],
        source_url: str,
    ) -> dict[str, Any]:
        """Store provider limits verified against its official source."""
        return handle_record_provider_verification(
            self.brain_router,
            provider,
            free_tier,
            models,
            strengths,
            source_url,
        )

    def request_provider_key(self, provider: str) -> dict[str, Any]:
        """Ask the human to configure a missing provider credential."""
        return handle_request_provider_key(self.brain_router, provider)

    def ask_brain(
        self,
        prompt: str,
        task_type: str = "simple",
        model: str | None = None,
        preferred_provider: str | None = None,
        max_tokens: int = 512,
    ) -> dict[str, Any]:
        """Send a bounded plain-text request through a supplemental provider."""
        return handle_ask_brain(
            self.brain_router,
            prompt,
            task_type,
            model,
            preferred_provider,
            max_tokens,
        )

    def benchmark_providers(self, providers: list[str] | None = None) -> dict[str, Any]:
        """Run the small built-in provider comparison and persist scores."""
        return handle_benchmark_providers(self.workspace, self.logger, self.brain_router, providers)

    def probe_local_ollama(self) -> dict[str, Any]:
        """Check local Ollama availability without starting or pulling a model."""
        return handle_probe_local_ollama(self.body)

    def request_capability(
        self,
        kind: str,
        summary: str,
        reason: str,
        provider: str = "",
        env_names: list[str] | None = None,
        signup_url: str = "",
    ) -> dict[str, Any]:
        """Record a human-facing request for expanded capabilities."""
        return handle_request_capability(
            self.capabilities,
            kind,
            summary,
            reason,
            provider,
            env_names,
            signup_url,
        )

    def propose_core_patch(self, name: str, diff: str, reasoning: str) -> dict[str, Any]:
        """Reject direct harness changes and record a proposed patch instead."""
        return handle_propose_core_patch(self.identity, name, diff, reasoning)

    def _is_core_path(self, path: Path) -> bool:
        """Treat symlink and traversal variants of image-owned harness paths as protected."""
        return check_is_core_path(path, self.core_root, self.agent_root, self.workspace, self.body)

    def read_file(self, path: str, max_chars: int = DEFAULT_OUTPUT_CAP) -> dict[str, Any]:
        """Read a file that passes the runner's path checks."""
        return handle_read_file(self.body, path=path, max_chars=max_chars)

    def write_file(self, path: str, content: str, append: bool = False) -> dict[str, Any]:
        """Write a workspace file after enforcing path and size limits."""
        return handle_write_file(
            self.body,
            self.workspace,
            path=path,
            content=content,
            append=append,
            plugin_dev=self.plugin_dev,
            identity=self._identity,
        )

    def list_dir(self, path: str, max_entries: int = 500) -> dict[str, Any]:
        """List directory entries up to a bounded count without following links."""
        return handle_list_dir(self.body, path=path, max_entries=max_entries)

    def http_get(self, url: str, timeout: float = 20, max_chars: int = DEFAULT_OUTPUT_CAP) -> dict[str, Any]:
        """Fetch a URL and record observable network access."""
        return handle_http_get(self.body, url=url, timeout=timeout, max_chars=max_chars)

    def read_cost_ledger(self) -> dict[str, Any]:
        """Read measured cost ledger baselines and plugin project totals."""
        return handle_read_cost_ledger(self.cost_ledger)

    def propose_plugin(
        self,
        name: str,
        need: str,
        evidence: str,
        alternatives_considered: Any,
        estimate: Any,
        expected_benefit: str,
        actions_needed_with_risk_levels: Any,
        maintenance_burden: str,
        stop_loss: Any,
        rollback: str,
    ) -> dict[str, Any]:
        """Propose developing a specialization plugin."""
        return handle_propose_plugin(
            self.plugin_dev,
            self.plan_store,
            self.current_cycle,
            name=name,
            need=need,
            evidence=evidence,
            alternatives_considered=alternatives_considered,
            estimate=estimate,
            expected_benefit=expected_benefit,
            actions_needed_with_risk_levels=actions_needed_with_risk_levels,
            maintenance_burden=maintenance_burden,
            stop_loss=stop_loss,
            rollback=rollback,
        )

    def scaffold_plugin(self, name: str, kind: str = "skill", description: str = "") -> dict[str, Any]:
        """Scaffold a plugin draft in workspace/plugin_dev/<name>/."""
        return handle_scaffold_plugin(self.plugin_dev, name=name, kind=kind, description=description)

    def validate_plugin(self, name: str) -> dict[str, Any]:
        """Run static validation on a plugin draft in workspace/plugin_dev/<name>/."""
        return handle_validate_plugin(self.plugin_dev, name=name)

    def test_plugin(self, name: str, test_type: str = "unit") -> dict[str, Any]:
        """Execute unittests for a plugin draft in workspace/plugin_dev/<name>/."""
        return handle_test_plugin(self.plugin_dev, name=name, test_type=test_type)

    def request_plugin_review(self, name: str) -> dict[str, Any]:
        """Request strict critic review of a validated plugin draft."""
        return handle_request_plugin_review(self.plugin_dev, name=name)

    def _ensure_opencode(self) -> Any:
        """Lazily initialize OpencodeDelegator if not already set."""
        return ensure_opencode(self)

    def _ensure_model_decisions(self) -> Any:
        """Lazily initialize ModelDecisions for recording build routes and outcomes."""
        return ensure_model_decisions(self)

    def opencode_status(self) -> dict[str, Any]:
        """Check opencode availability status."""
        return handle_opencode_status(self)

    def delegate_coding(self, **kwargs: Any) -> dict[str, Any]:
        """Delegate a scoped coding task to opencode in a sandbox."""
        return handle_delegate_coding(self, **kwargs)

    def apply_delegation(self, delegation_id: str) -> dict[str, Any]:
        """Apply a completed delegation's changes to the real repository."""
        return handle_apply_delegation(self, delegation_id)

    def discard_delegation(self, delegation_id: str) -> dict[str, Any]:
        """Discard a delegation record and delete its sandbox directory."""
        return handle_discard_delegation(self, delegation_id)

    def record_build_route(self, **kwargs: Any) -> dict[str, Any]:
        """Record a build route choice (self or opencode)."""
        return handle_record_build_route(self, **kwargs)

    def record_build_outcome(self, **kwargs: Any) -> dict[str, Any]:
        """Record the final outcome of a build task."""
        return handle_record_build_outcome(self, **kwargs)

    def build_route_stats(self, limit: int = 10) -> dict[str, Any]:
        """Read recent build route history and statistics."""
        return handle_build_route_stats(self, limit=limit)

    def get_opencode_tool_definitions(self) -> list[dict[str, Any]]:
        """Return schema definitions for opencode delegation tools."""
        return get_opencode_tool_definitions()

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        """Return tool definitions, optionally augmented by active body profile."""
        return get_tool_definitions(self.body)


__all__ = [
    "DEFAULT_OUTPUT_CAP",
    "HELPER_TOOL_NAMES",
    "MODEL_TOOL_SPECS",
    "TOOL_DEFINITIONS",
    "TOOL_PERMISSION_LEVELS",
    "ToolRunner",
    "_LoggingRedirectHandler",
    "get_tool_definitions",
]
