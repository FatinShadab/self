"""System prompt assembly and core prompt constants for the autonomous loop."""
from __future__ import annotations

from typing import Any

from agent.prompts.system import (
    CORE_CAPABILITY_RULE,
    CORE_IDENTITY_RULES,
    CORE_SYSTEM_PROMPT_HEAD,
    OFF_PROMPT_PREFIXES,
    OPENCODE_CAPABILITY_PROMPT,
    ORIENTATION_TASK,
    STANDING_GOAL,
    render_core_system_prompt,
)


def assemble_system_prompt(body: Any | None = None) -> str:
    """Assemble the system prompt from core rules and body-specific description.

    When body is None, renders a completely neutral environment-agnostic prompt
    with no body profile or location claims.
    """
    if body is None:
        return render_core_system_prompt()
    desc = body.describe()
    return render_core_system_prompt(
        embodiment_clause=desc.embodiment_clause,
        pre_capability_rules=desc.pre_capability_rules,
        post_capability_rules=desc.post_capability_rules,
        body_rules=desc.body_rules,
    )


SYSTEM_PROMPT: str = assemble_system_prompt()

__all__ = [
    "CORE_CAPABILITY_RULE",
    "CORE_IDENTITY_RULES",
    "CORE_SYSTEM_PROMPT_HEAD",
    "OFF_PROMPT_PREFIXES",
    "OPENCODE_CAPABILITY_PROMPT",
    "ORIENTATION_TASK",
    "STANDING_GOAL",
    "SYSTEM_PROMPT",
    "assemble_system_prompt",
    "render_core_system_prompt",
]
