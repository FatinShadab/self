"""SELF delegation prompts."""
from __future__ import annotations

from typing import Sequence

OPENCODE_RETRY_NOTE = (
    "\n\nNOTE: A previous attempt using another provider failed or was interrupted. "
    "Partial work may already exist in the repository sandbox."
)


def build_opencode_prompt(
    target_dirs: Sequence[str],
    acceptance_check: str,
    spec: str,
    is_retry: bool = False,
) -> str:
    """Build the prompt string passed to the opencode coding engine."""
    target_dirs_str = ", ".join(target_dirs)
    prompt = (
        "You are an automated coding assistant operating inside a repository sandbox.\n"
        f"You may ONLY create, edit, or delete files inside the following directories: {target_dirs_str}.\n"
        "Do NOT modify or touch files outside these directories.\n"
        "Your changes must make the following acceptance check pass:\n"
        f"  {acceptance_check}\n\n"
        f"Task Specification:\n{spec}\n"
    )
    if is_retry:
        prompt += OPENCODE_RETRY_NOTE
    return prompt
