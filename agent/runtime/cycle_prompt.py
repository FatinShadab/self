"""Per-cycle prompt assembly for the autonomous agent loop."""
from __future__ import annotations

import json
from typing import Any, Callable

from agent.helper_models.model_decisions import ModelDecisions
from agent.infra.event_log import EventLogger
from agent.infra.untrusted import UNTRUSTED_DATA_RULE, wrap_untrusted
from agent.prompts.cycle import (
    assemble_loop_system_prompt,
    build_model_context_block,
)
from agent.prompts.system import (
    OFF_PROMPT_PREFIXES,
    OPENCODE_CAPABILITY_PROMPT,
)
from agent.runtime.prompts import assemble_system_prompt


def build_system_prompt_for_cycle(
    identity: Any,
    body: Any,
    logger: EventLogger,
    llm: Any,
    model_registry: Any,
    model_decisions: Any,
    plugins: Any,
    helper_mode: bool,
    identity_context_provider: Callable[[], str] | None = None,
) -> str:
    """Load fresh identity, model context, and plugin embodiment into the cycle system prompt."""
    active_plugins_set = set(plugins.active_plugins.keys()) if plugins else set()
    try:
        context = (
            identity_context_provider()
            if identity_context_provider
            else identity.prompt_context(active_plugins=active_plugins_set)
        )
    except Exception as exc:
        logger.log("identity_context_fallback", error_type=type(exc).__name__)
        context = "## Persistent identity\nIdentity state could not be loaded; do not invent identity claims."

    client = llm.client
    model_context = ""
    if model_registry is not None:
        entries = model_registry.list_models()["models"]
        eligible = (
            set(model_decisions._available())
            if model_decisions is not None
            else {item["name"] for item in entries if item["status"] in {"configured", "reachable"}}
        )
        summary = [
            ModelDecisions._summary_entry(item)
            for item in entries
            if item["role"] == "base" or item["name"] in eligible
        ]
        model_context = build_model_context_block(
            provider=client.provider,
            base_model=client.base_model,
            summary_json=json.dumps(summary, ensure_ascii=False),
        )

    prompt_text = assemble_system_prompt(body)
    system_prompt = (
        prompt_text
        if helper_mode
        else "\n".join(line for line in prompt_text.splitlines() if not line.startswith(OFF_PROMPT_PREFIXES))
    )
    plugin_embodiment_text = (
        plugins.get_embodiment_prompt().strip() if (plugins and plugins.get_embodiment_prompt()) else ""
    )
    plugin_embodiment = (
        f"\n\n{wrap_untrusted(plugin_embodiment_text, source='plugins:embodiment')}"
        if plugin_embodiment_text
        else ""
    )
    opencode_context = f"\n\n{OPENCODE_CAPABILITY_PROMPT}"

    return assemble_loop_system_prompt(
        system_prompt=system_prompt,
        model_context=model_context,
        opencode_context=opencode_context,
        identity_context=logger.redactor.text(context),
        plugin_embodiment=plugin_embodiment,
        untrusted_rule=UNTRUSTED_DATA_RULE,
    )
