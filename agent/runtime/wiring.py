"""Collaborator wiring and explicit dependency injection for the autonomous agent loop."""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.helper_models.model_decisions import ModelDecisions
from agent.helper_models.model_probe import ModelProber
from agent.identity.identity import IdentityStore
from agent.infra.event_log import EventLogger
from agent.infra.hardening import CapabilityRequests, DailyTokenLedger, RunCheckpoint
from agent.learning.learning import LearningStore
from agent.learning.plan import PlanStore
from agent.llm.brain_router import BrainRouter
from agent.llm.llm import BudgetedLLM
from agent.llm.model_registry import ModelRegistry
from agent.runtime.config import AgentConfig, LLMProtocol
from agent.tools.base_tools import TOOL_DEFINITIONS, ToolRunner
from agent.tools.tool_registry import ToolRegistry


@dataclass
class LoopCollaborators:
    """The resolved set of collaborating systems wired to an AgentLoop."""

    daily_ledger: DailyTokenLedger
    budgeted_llm: BudgetedLLM
    body: Any
    helper_mode: bool
    model_registry: ModelRegistry | None
    max_tokens_per_call: int
    model_prober: ModelProber | None
    model_decisions: ModelDecisions | None
    registry: ToolRegistry
    learning: LearningStore
    plan_store: PlanStore
    brain_router: BrainRouter
    capabilities: CapabilityRequests
    identity: IdentityStore
    checkpoint: RunCheckpoint
    plugins: Any
    plugin_dev: Any
    broker: Any
    audit_trail: Any
    watcher: Any
    stop_file: Path
    human_request: Path


def wire_loop_collaborators(
    config: AgentConfig,
    logger: EventLogger,
    llm: LLMProtocol,
    tools: ToolRunner,
) -> LoopCollaborators:
    """Construct, wire, and attach collaborators to ToolRunner and return the collaborator set."""
    daily_ledger = config.daily_ledger or DailyTokenLedger(config.workspace, logger)
    budgeted_llm = BudgetedLLM(llm, logger, daily_ledger=daily_ledger)

    body = config.body

    helper_mode = os.getenv("SELF_HELPER_MODELS", "on").strip().lower() == "on"

    model_registry = None
    if helper_mode and hasattr(llm, "base_model") and hasattr(llm, "available_models"):
        model_registry = getattr(llm, "model_registry", None) or ModelRegistry(
            config.workspace, logger, llm.base_model, llm.available_models
        )
    tools.model_registry = model_registry

    base_model_name = getattr(llm, "base_model", "gpt-oss:120b")
    if config.max_tokens_per_call is not None and config.max_tokens_per_call != 4096:
        max_tokens_per_call = config.max_tokens_per_call
    elif model_registry is not None:
        max_tokens_per_call = model_registry.get_output_cap(base_model_name)
    else:
        max_tokens_per_call = int(os.getenv("SELF_DEFAULT_OUTPUT_CEILING", "32768"))

    session_id = config.session_id or uuid.uuid4().hex
    model_prober = (
        ModelProber(
            model_registry,
            budgeted_llm,
            logger,
            session_id,
            getattr(llm, "provider", "unknown"),
        )
        if model_registry is not None
        else None
    )
    tools.model_prober = model_prober

    model_decisions = (
        ModelDecisions(config.workspace, logger, model_registry, budgeted_llm, session_id)
        if model_registry is not None
        else None
    )
    tools.model_decisions = model_decisions

    registry = ToolRegistry(
        config.workspace,
        logger,
        budgeted_llm.call,
        {tool["name"] for tool in TOOL_DEFINITIONS},
        output_cap=tools.output_cap,
    )
    tools.registry = registry
    registry.model_decisions = model_decisions

    learning = LearningStore(config.workspace, logger)
    tools.learning = learning

    plan_store = getattr(tools, "plan_store", None) or PlanStore(config.workspace, logger)
    tools.plan_store = plan_store
    tools.review_call = budgeted_llm.call

    brain_router = BrainRouter(config.workspace, logger)
    tools.brain_router = brain_router

    capabilities = CapabilityRequests(config.workspace, logger)
    tools.capabilities = capabilities

    identity = tools.identity or IdentityStore(config.workspace, logger, core_root=tools.core_root)
    tools.identity = identity

    checkpoint = RunCheckpoint(config.workspace, logger)

    plugins = getattr(config, "plugins", None)
    if plugins is None:
        from agent.plugins.manager import PluginManager

        plugins = PluginManager(config.workspace, logger=logger)
    tools.plugins = plugins

    from agent.plugins.self_dev import PluginDevManager

    plugin_dev = PluginDevManager(
        workspace=config.workspace,
        logger=logger,
        cost_ledger=tools.cost_ledger,
        review_call=budgeted_llm.call,
    )
    tools.plugin_dev = plugin_dev

    broker = config.broker or getattr(tools, "broker", None)
    audit_trail = config.audit_trail or getattr(tools, "audit_trail", None)
    if broker is not None:
        tools.broker = broker
        if audit_trail is not None and getattr(broker, "audit_trail", None) is None:
            broker.audit_trail = audit_trail

    stop_file = config.workspace / "STOP"
    human_request = config.workspace / "HUMAN_REQUEST.md"

    return LoopCollaborators(
        daily_ledger=daily_ledger,
        budgeted_llm=budgeted_llm,
        body=body,
        helper_mode=helper_mode,
        model_registry=model_registry,
        max_tokens_per_call=max_tokens_per_call,
        model_prober=model_prober,
        model_decisions=model_decisions,
        registry=registry,
        learning=learning,
        plan_store=plan_store,
        brain_router=brain_router,
        capabilities=capabilities,
        identity=identity,
        checkpoint=checkpoint,
        plugins=plugins,
        plugin_dev=plugin_dev,
        broker=broker,
        audit_trail=audit_trail,
        watcher=config.stop_watcher,
        stop_file=stop_file,
        human_request=human_request,
    )
