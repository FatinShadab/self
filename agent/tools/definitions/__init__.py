"""Aggregated tool definitions and specifications preserving exact canonical order."""
from __future__ import annotations

from typing import Any

from agent.tools.definitions.models import (
    ASK_MODEL_DEFINITION,
    HELPER_TOOL_NAMES,
    LIST_MODELS_DEFINITION,
    MODEL_TOOL_SPECS,
    PROBE_LOCAL_OLLAMA_DEFINITION,
    PROBE_MODEL_DEFINITION,
    RECORD_DELEGATION_OUTCOME_DEFINITION,
    RECORD_MODEL_ASSESSMENT_DEFINITION,
    RESEARCH_MODEL_DEFINITION,
)
from agent.tools.definitions.core import (
    HTTP_GET_DEFINITION,
    LIST_DIR_DEFINITION,
    READ_FILE_DEFINITION,
    RUN_SHELL_DEFINITION,
    WRITE_FILE_DEFINITION,
)
from agent.tools.definitions.plan import (
    READ_PLAN_DEFINITION,
    UPDATE_ENVIRONMENT_MAP_DEFINITION,
    UPDATE_PLAN_DEFINITION,
)
from agent.tools.definitions.provider import (
    ASK_BRAIN_DEFINITION,
    BENCHMARK_PROVIDERS_DEFINITION,
    RECORD_PROVIDER_VERIFICATION_DEFINITION,
    REQUEST_PROVIDER_KEY_DEFINITION,
    RESEARCH_PROVIDER_DEFINITION,
)
from agent.tools.definitions.system import (
    PROPOSE_CORE_PATCH_DEFINITION,
    REQUEST_CAPABILITY_DEFINITION,
)
from agent.tools.definitions.plugins import (
    PROPOSE_PLUGIN_DEFINITION,
    READ_COST_LEDGER_DEFINITION,
    REQUEST_PLUGIN_REVIEW_DEFINITION,
    SCAFFOLD_PLUGIN_DEFINITION,
    TEST_PLUGIN_DEFINITION,
    VALIDATE_PLUGIN_DEFINITION,
)

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    LIST_MODELS_DEFINITION,
    RECORD_MODEL_ASSESSMENT_DEFINITION,
    PROBE_MODEL_DEFINITION,
    RESEARCH_MODEL_DEFINITION,
    ASK_MODEL_DEFINITION,
    RECORD_DELEGATION_OUTCOME_DEFINITION,
    RUN_SHELL_DEFINITION,
    READ_FILE_DEFINITION,
    WRITE_FILE_DEFINITION,
    LIST_DIR_DEFINITION,
    HTTP_GET_DEFINITION,
    UPDATE_ENVIRONMENT_MAP_DEFINITION,
    READ_PLAN_DEFINITION,
    UPDATE_PLAN_DEFINITION,
    RESEARCH_PROVIDER_DEFINITION,
    RECORD_PROVIDER_VERIFICATION_DEFINITION,
    REQUEST_PROVIDER_KEY_DEFINITION,
    ASK_BRAIN_DEFINITION,
    BENCHMARK_PROVIDERS_DEFINITION,
    PROBE_LOCAL_OLLAMA_DEFINITION,
    REQUEST_CAPABILITY_DEFINITION,
    PROPOSE_CORE_PATCH_DEFINITION,
    READ_COST_LEDGER_DEFINITION,
    PROPOSE_PLUGIN_DEFINITION,
    SCAFFOLD_PLUGIN_DEFINITION,
    VALIDATE_PLUGIN_DEFINITION,
    TEST_PLUGIN_DEFINITION,
    REQUEST_PLUGIN_REVIEW_DEFINITION,
]


def get_tool_definitions(
    body: Any = None,
    extra_descriptions: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Return tool definitions, optionally augmented with extra description text from a body profile or caller."""
    extra: dict[str, str] = {}
    if body is not None:
        desc = getattr(body, "describe", lambda: body)()
        body_extra = getattr(desc, "extra_tool_descriptions", None) or getattr(desc, "tool_descriptions", None)
        if body_extra and isinstance(body_extra, dict):
            extra.update(body_extra)
    if extra_descriptions:
        extra.update(extra_descriptions)

    if not extra:
        return [dict(t) for t in TOOL_DEFINITIONS]

    result: list[dict[str, Any]] = []
    for tool in TOOL_DEFINITIONS:
        name = tool.get("name")
        if name in extra:
            copied = dict(tool)
            extra_text = extra[name]
            base_desc = copied.get("description", "")
            if extra_text.startswith(" ") or extra_text.startswith("\n"):
                copied["description"] = f"{base_desc}{extra_text}"
            else:
                copied["description"] = f"{base_desc} {extra_text}"
            result.append(copied)
        else:
            result.append(dict(tool))
    return result


__all__ = [
    "TOOL_DEFINITIONS",
    "get_tool_definitions",
    "HELPER_TOOL_NAMES",
    "MODEL_TOOL_SPECS",
    "LIST_MODELS_DEFINITION",
    "RECORD_MODEL_ASSESSMENT_DEFINITION",
    "PROBE_MODEL_DEFINITION",
    "RESEARCH_MODEL_DEFINITION",
    "ASK_MODEL_DEFINITION",
    "RECORD_DELEGATION_OUTCOME_DEFINITION",
    "RUN_SHELL_DEFINITION",
    "READ_FILE_DEFINITION",
    "WRITE_FILE_DEFINITION",
    "LIST_DIR_DEFINITION",
    "HTTP_GET_DEFINITION",
    "UPDATE_ENVIRONMENT_MAP_DEFINITION",
    "READ_PLAN_DEFINITION",
    "UPDATE_PLAN_DEFINITION",
    "RESEARCH_PROVIDER_DEFINITION",
    "RECORD_PROVIDER_VERIFICATION_DEFINITION",
    "REQUEST_PROVIDER_KEY_DEFINITION",
    "ASK_BRAIN_DEFINITION",
    "BENCHMARK_PROVIDERS_DEFINITION",
    "PROBE_LOCAL_OLLAMA_DEFINITION",
    "REQUEST_CAPABILITY_DEFINITION",
    "PROPOSE_CORE_PATCH_DEFINITION",
    "READ_COST_LEDGER_DEFINITION",
    "PROPOSE_PLUGIN_DEFINITION",
    "SCAFFOLD_PLUGIN_DEFINITION",
    "VALIDATE_PLUGIN_DEFINITION",
    "TEST_PLUGIN_DEFINITION",
    "REQUEST_PLUGIN_REVIEW_DEFINITION",
]
