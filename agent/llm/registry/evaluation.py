"""Evaluation requirement calculations for configured helper models."""
from __future__ import annotations

from typing import Any

from agent.llm.registry.constants import PROBE_FORMAT_VERSION


def get_helpers_needing_evaluation(data_or_registry: dict[str, Any] | Any) -> list[str]:
    """Compute helpers that need evaluation from models.json data or a ModelRegistry.

    A helper needs evaluation if it has no probe in probe_history at the current probe_format_version,
    or its latest probe is invalidated, or research.status is not_checked, or it has no agent_assessment.
    """
    if hasattr(data_or_registry, "list_models"):
        data = data_or_registry.list_models()
    elif isinstance(data_or_registry, dict):
        data = data_or_registry
    else:
        return []
    format_version = int(data.get("probe_format_version", PROBE_FORMAT_VERSION) or PROBE_FORMAT_VERSION)
    needing: list[str] = []
    for model in data.get("models", []):
        if not isinstance(model, dict):
            continue
        if model.get("role") == "base" or model.get("status") == "disabled" or model.get("configured") is False:
            continue
        name = model.get("name")
        if not name:
            continue
        history = [item for item in model.get("probe_history", []) if isinstance(item, dict)]
        has_current_probe = any(
            not item.get("invalidated")
            and int(item.get("format_version", format_version) or format_version) == format_version
            for item in history
        )
        latest_invalidated = bool(history and history[-1].get("invalidated"))
        research = model.get("research", {})
        research_status = research.get("status", "not_checked") if isinstance(research, dict) else "not_checked"
        has_assessment = bool(str(model.get("agent_assessment", "")).strip())

        if not has_current_probe or latest_invalidated or research_status == "not_checked" or not has_assessment:
            needing.append(name)
    return needing
