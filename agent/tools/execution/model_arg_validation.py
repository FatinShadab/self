"""Validation and alias normalization for helper-model tool invocation arguments."""
from __future__ import annotations

from typing import Any

from agent.tools.definitions.models import MODEL_TOOL_SPECS


def validate_model_tool_arguments(
    name: str,
    arguments: dict[str, Any],
    model_registry: Any = None,
) -> dict[str, Any] | None:
    """Validate argument names and model name validity against MODEL_TOOL_SPECS.

    Mutates arguments in-place if an alias normalization hint is returned by the registry.

    Returns:
        Error dict if validation fails; None if validation passes.
    """
    if name not in MODEL_TOOL_SPECS:
        return None

    spec = MODEL_TOOL_SPECS[name]
    allowed = spec["allowed"]
    required = spec["required"]

    unexpected = sorted(set(arguments) - allowed)
    if unexpected:
        return {
            "ok": False,
            "error": f"Unexpected argument(s) {unexpected} for {name}. Valid arguments are: {sorted(allowed)}.",
        }

    missing = sorted(required - set(arguments))
    if missing:
        return {
            "ok": False,
            "error": f"Missing required argument(s) {missing} for {name}. Valid arguments are: {sorted(allowed)}.",
        }

    if model_registry is not None:
        arg_name = spec.get("model_arg")
        if arg_name and arg_name in arguments:
            model_name = str(arguments[arg_name])
            helpers_only = bool(spec.get("helpers_only", False))
            valid, hint = model_registry.validate_model_name(model_name, helpers_only=helpers_only)
            if not valid:
                return {"ok": False, "error": hint}
            if hint and hint != model_name:
                arguments[arg_name] = hint

    return None
