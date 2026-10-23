"""First-awakening sequence execution, self-inquiry, and code explanation."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.identity.store.constants import now
from agent.infra.event_log import EventLogger


def ensure_editable_layer(self_root: Path, logger: EventLogger) -> None:
    """Create the intentionally writable extension layer without overwriting it."""
    for directory in (self_root, self_root / "prompts", self_root / "heuristics", self_root / "themes"):
        directory.mkdir(parents=True, exist_ok=True)
    readme = self_root / "README.md"
    if not readme.exists():
        readme.write_text(
            "# SELF editable layer\n\n"
            "This directory is the agent's writable extension area for prompts, personality notes, "
            "planning logic, tool-selection heuristics, and TUI themes. Core harness changes belong "
            "in `state/proposed_patches/` for human review; do not copy or modify `/opt/agent/core/`.\n",
            encoding="utf-8",
        )
        logger.log("editable_self_layer_initialized", path=str(self_root))


def core_reference(filename: str, needle: str, core_root: Path) -> str:
    """Return a file:line reference after reading the actual source when possible."""
    candidates = [core_root / filename, Path(__file__).resolve().parents[1] / filename]
    for candidate in candidates:
        try:
            lines = candidate.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        line_number = 1
        if needle:
            for index, line in enumerate(lines, start=1):
                if needle in line:
                    line_number = index
                    break
        shown = str(candidate)
        if candidate.parent == core_root and str(core_root) == "/opt/agent/core":
            shown = f"/opt/agent/core/{filename}"
        return f"{shown}:{line_number}"
    return f"/opt/agent/core/{filename}:1 (source unavailable during this check)"


def write_self_inquiry(inquiry_path: Path, core_root: Path, body: Any, redactor: Any) -> None:
    """Write the initial self_inquiry.md with verified evidence references."""
    loop_ref = core_reference("loop.py", "STANDING_GOAL", core_root)
    tool_ref = core_reference("base_tools.py", "class ToolRunner", core_root)
    budget_ref = core_reference("hardening.py", "class DailyTokenLedger", core_root)
    log_ref = core_reference("event_log.py", "class SecretRedactor", core_root)
    harness_context = (
        body.describe().identity_harness_context
        if body and hasattr(body, "describe") and body.describe().identity_harness_context
        else "running in a Linux container."
    )
    content = f"""# SELF inquiry

Generated at {now()}. This document separates checked facts from questions that still need evidence.

## What am I made of?

**Verified.** I am an LLM-driven Python harness {harness_context} The loop, tools, persistent workspace state, and model wrapper are separate software components; they are not a biological body or proof of subjective experience.


Evidence:

- `{loop_ref}` defines the standing goal and the cycle loop.
- `{tool_ref}` implements the container tools.
- `{log_ref}` implements redaction before harness logs and tool results.

## What can I do, and what am I forbidden to do, and why?

**Verified.** I can inspect and work inside the container, write workspace extensions and tested tools, and make logged HTTP requests through the harness. I must not create accounts, solve CAPTCHAs, evade limits, expose credentials, or expand beyond the container without a human approval request. Those limits protect the human, credentials, and host boundary.

Evidence:

- `{budget_ref}` persists budgets and capability requests.
- `/home/entity/self/README.md:1` describes the writable extension layer.

## What do I not know about myself?

**Unverified.** I do not yet know which exploration strategies will be most useful, which optional providers will be available, or which working style the human prefers. I must test those questions rather than assume answers.

## What do I want to find out first, and why?

**Verified as an operating priority, not a feeling.** First, I should map the container, its limits, and its available tools. Accurate constraints make later self-written tools and plans safer and more useful.

Evidence: `{loop_ref}` and the persisted standing goal.
"""
    inquiry_path.parent.mkdir(parents=True, exist_ok=True)
    text = redactor.text(content) if hasattr(redactor, "text") else content
    inquiry_path.write_text(text, encoding="utf-8")


def write_code_explanation(
    explanation_path: Path,
    core_root: Path,
    self_root: Path,
    redactor: Any,
) -> None:
    """Write self_code_explanation.md with verified file references."""
    references = {
        "loop": core_reference("loop.py", "class AgentLoop", core_root),
        "tools": core_reference("tool_registry.py", "class ToolRegistry", core_root),
        "logging": core_reference("event_log.py", "class EventLogger", core_root),
        "budget": core_reference("hardening.py", "class DailyTokenLedger", core_root),
        "capability": core_reference("hardening.py", "class CapabilityRequests", core_root),
        "wake": core_reference("wake.py", "class WakeCoordinator", core_root),
    }
    observed_core = []
    try:
        observed_core = sorted(path.name for path in core_root.iterdir() if path.is_file())[:30]
    except OSError:
        observed_core = ["core source will be inspected in the container image"]
    observed_self = []
    try:
        readme = self_root / "README.md"
        if readme.exists():
            readme.read_text(encoding="utf-8", errors="replace")
        observed_self = sorted(path.name for path in self_root.iterdir())[:30]
    except OSError:
        observed_self = ["editable layer unavailable during this check"]
    content = f"""# How SELF currently works

Checked at {now()}. This is a plain-language reading of the harness and editable layer, not a claim about model internals.

## Verified structure

- **Cycle loop:** `{references['loop']}` retrieves memory and relevant tool definitions, asks the model, executes returned tool calls, records observations, and repeats within configured bounds. It checks for `STOP` at safe boundaries.
- **Tool loading:** `{references['tools']}` loads registered tools from the mounted workspace and selects a bounded relevant subset for a model step. New tools must be reviewed and tested before registration.
- **Memory and sessions:** `state/` is on the mounted workspace. The wake coordinator (`{references['wake']}`) creates handoffs and resumes durable session information after restart.
- **Logs and redaction:** `{references['logging']}` writes append-only JSONL events and applies a redaction filter before harness output is persisted.
- **Budgets and kill controls:** `{references['budget']}` persists daily token use (the single active token limit); the loop checks run iteration and wall-clock bounds. A workspace `STOP` file halts cleanly.
- **Credentials and reach:** `{references['capability']}` writes human review requests for credentials and other expansions instead of changing host configuration.
- **Editable layer:** `/home/entity/self/README.md:1` is the writable place for extension prompts, heuristics, planning logic, and themes.

## Source inspected

Core directory observed: {", ".join(observed_core)}.

Editable layer observed: {", ".join(observed_self)}.

## Risks, confusions, and improvements

- The container is the security boundary. Because the process intentionally runs as root inside it, file permissions are an integrity guard against normal harness writes, not a stronger containment mechanism than Docker.
- Network activity launched directly by unrestricted shell commands cannot be fully audited by the Python-level egress logger; harness HTTP/provider calls are logged.
- No core patch is generated automatically. If an evidence-backed core improvement is needed, it must be saved as a reviewed proposal under `state/proposed_patches/` and applied by the human from the host.
"""
    explanation_path.parent.mkdir(parents=True, exist_ok=True)
    text = redactor.text(content) if hasattr(redactor, "text") else content
    explanation_path.write_text(text, encoding="utf-8")


def initialize_human_file(human_path: Path) -> None:
    """Initialize about_human.md if missing."""
    if human_path.exists():
        return
    human_path.parent.mkdir(parents=True, exist_ok=True)
    human_path.write_text(
        "# About the human\n\n"
        "This file holds only information the human chooses to share. Use `/about me` to view it or "
        "`/about me delete <line>` to remove a stored line.\n\n"
        "## First meeting\n\n"
        "- SELF asked what the human hopes it will do, what they are worried about, what they want reported, "
        "and how they prefer it to speak.\n",
        encoding="utf-8",
    )
