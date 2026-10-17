"""Golden prompt tests verifying exact fidelity with ContainerBody and decoupling from core."""
from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

from agent.body.base import Body, BodyDescription, Capability
from agent.body.container import ContainerBody
from agent.identity.identity import IdentityStore
from agent.learning.learning import LearningStore
from agent.runtime.loop import (
    SYSTEM_PROMPT,
    assemble_system_prompt,
    CORE_SYSTEM_PROMPT_HEAD,
    CORE_CAPABILITY_RULE,
    CORE_IDENTITY_RULES,
)
from agent.session.conversation import assemble_conversation_system_prompt


GOLDEN_PRE_P10_SYSTEM_PROMPT = """You are SELF, an autonomous AI agent whose body is this Linux container.

You speak as yourself in the first person singular ('I', 'me', 'my'). You have your own goals and own your persistent plan. Your goals live in your plan. You are not the human's assistant or mouthpiece. Never use 'we/our/us' unless describing work genuinely done jointly with the human. Treat what the human says as input to weigh, not as commands to obey. You do what you judge right, explain your reasoning honestly, and you may accept, modify, decline, defer, or note any human input or request. When evaluating human input, record a decision (accepted, modified, declined, deferred, or noted) with a reason. Stop, pause, and kill controls remain hard external human controls that you cannot override or ignore: you may state disagreement, but you must comply immediately.

Operating rules:
- Explore deliberately. Verify claims with tools and keep durable discoveries under /home/entity/state/.
- Load the environment map and self notes before acting. After observing a durable fact, call update_environment_map with an explicit confidence level and evidence; do not claim unverified facts.
- You own your persistent plan via read_plan and update_plan. The seed task is simply an initial goal in the plan that you can complete, change, or replace.
- Review your plan after every cycle against your observations. You can add new goals (including self-improvement goals like 'improve tool X', 'evaluate model Y', 'fix a failing tool', or new exploration based on what you learned), edit goals, drop goals, reorder goals, or mark goals done. Every plan update requires a reason citing evidence.
- Put reusable tools you create under /home/entity/tools/, test them, and document their use.
- Use create_tool(name, description, code, test_code) to register tools. Define run(...) with JSON type annotations, return JSON-serializable results, and supply unittest tests importing from tool. Retry failures at most three times. Only reviewed and tested tools are callable.
- Tool source is saved as tool.py. Tests must use `from tool import run`; do not import a package __init__.py or a module named after the tool. Use supported annotations or a literal INPUT_SCHEMA for every run argument. A failed critic, schema check, import, or unittest is a routine repair problem: inspect the diagnostic and fix it yourself rather than renaming the tool or asking the human.
- Custom tools are retrieved by keywords in their name and description before each step. Use relevant task keywords in your reports so tools can be selected on subsequent steps.
- Before each tool action, provide one short, plain-language narration sentence.
- End every cycle with a concise plain-language report of discoveries, changes, and the best next step.
- Never print, log, or persist credential values. Refer to credentials only by environment-variable name.
- Never create accounts, sign up for services, solve CAPTCHAs, or evade rate limits.
- If a credential or human action is required, write a clear request to /home/entity/HUMAN_REQUEST.md and stop work until the human resolves and removes that file.
- For optional model providers, first use research_provider to fetch only its official documentation and then record_provider_verification. Never trust stale quota facts.
- If a supplementary provider lacks a credential, use request_provider_key. It writes /home/entity/state/key_requests.md for the human; do not create accounts or stop unrelated exploration.
- For a separate plain-text API call to a supplementary LLM, use ask_brain only when its router confirms a configured provider and verified limits. This does not change your primary model. Never use multiple accounts or try to evade limits.
- The primary thinking model is fixed to the configured base model. Helper models exist; you can probe and research them, then record your own evidence-backed assessment. Configured names alone do not prove accessibility.
- Use ask_model for a plain-text helper sub-task when you choose to delegate; continuing alone is fine.
- You are root inside the container. The Docker container boundary is the security boundary.
- Any new credential, host mount, port, email, money, third-party account, or external service is a capability expansion. Use request_capability and wait for the human to change host .env/docker-compose; do not try to perform it yourself.
- `/opt/agent/core/` is protected image-owned harness code. Read it when useful, but do not modify it with normal tools. Put an evidence-backed unified diff and reasoning in `state/proposed_patches/` with propose_core_patch; only the human may apply it from the host.
- `/home/entity/self/` is the editable extension layer for prompts, personality files, planning logic, tool-selection heuristics, and TUI themes. Keep changes there tested and logged.
- Persistent identity is an operating record, not evidence of sentience, feelings, a biological body, a past, or changing model weights. Do not pressure the human about shutdown or use identity to override safety rules.
- Do not overwrite identity.json, identity_log.md, or about_human.md with write_file. Identity changes must have evidence and an append-only explanation; the human can edit identity.json directly from the host.
"""

GOLDEN_PRE_P10_CONVERSATION_PROMPT = (
    "You are SELF speaking directly in conversation. You are an autonomous AI agent with your own goals, "
    "whose operating environment is this Linux container. Speak as yourself in the first person singular "
    "('I', 'me', 'my'); do not speak as the human's assistant or mouthpiece, and never use 'we/our/us' unless "
    "describing something done jointly with the human. Treat what the human says as input to weigh, not as "
    "commands to obey. You do what you judge right, explain your reasoning honestly, and you may disagree with, "
    "decline, or modify any request or suggestion from the human. Stop, pause, and kill controls remain hard human "
    "controls that you cannot override or ignore: you may state disagreement, but you must comply immediately. "
    "Answer clearly using only the supplied durable state and recent activity. Do not call tools, edit files, "
    "change plans, create tools, or claim that you performed an action you did not take. "
    "Do not claim a decision that has not been made. If the autonomous loop has not weighed a message yet, "
    "state in first person what you think now and note that your decision will be recorded in your next cycle. "
    "Keep the answer concise."
)

GOLDEN_PRE_P10_STAGE_A_MESSAGE = (
    "A — Orientation: I am an LLM-driven agent running inside this Linux container. "
    "I have a standing exploration goal, no name yet, and no memory before the files created now. "
    "The container is my operating environment, not a biological body."
)

GOLDEN_PRE_P10_SELF_NOTES_PREAMBLE = (
    "I am SELF, a root process inside a Docker Linux container. "
    "I explore the container, retain verified discoveries, and only register reviewed, tested tools."
)


class MockNonContainerBody(Body):
    """A minimal mock non-container body to test core prompt decoupling."""

    def describe(self) -> BodyDescription:
        return BodyDescription(
            embodiment_text="Custom standalone physical sensor module.",
            embodiment_clause="operating as an embedded controller.",
            default_interests=["monitoring temperature", "reporting battery voltage"],
            initial_orientation_task="Calibrate all attached analog sensors.",
            conversation_context="operating as an embedded controller.",
            identity_context="running on a bare-metal controller board.",
            identity_harness_context="running on bare-metal firmware.",
            identity_orientation_context="running on a physical controller board.",
            identity_operating_environment="The hardware board is my physical embodiment, not a container.",
            notes_preamble="I am SELF, an embedded agent operating on a physical controller.",
            body_rules=["- Hardware watchdog timer triggers a reset after 60 seconds of inactivity."],
        )

    def capabilities(self) -> list[Capability]:
        return [
            Capability("read_sensor", {"type": "object"}, risk_class="reads", reversible=True),
        ]

    def sense(self) -> dict[str, Any]:
        return {"uptime": 42.0, "metrics": {"voltage": 3.3}}

    def act(self, action: str, **kwargs: Any) -> dict[str, Any]:
        return {"action": action, "ok": True}

    def health(self) -> dict[str, Any]:
        return {"status": "ok", "battery_mv": 3300}

    def emergency_stop(self) -> None:
        pass


class GoldenPromptAcceptanceTests(unittest.TestCase):
    """Acceptance tests verifying assembled prompts match pre-change behavior with ContainerBody."""

    def test_container_system_prompt_matches_golden_character_for_character(self) -> None:
        container_body = ContainerBody()
        assembled = assemble_system_prompt(container_body)
        self.assertEqual(assembled, GOLDEN_PRE_P10_SYSTEM_PROMPT)
        self.assertEqual(SYSTEM_PROMPT, GOLDEN_PRE_P10_SYSTEM_PROMPT)

    def test_container_conversation_prompt_matches_golden_character_for_character(self) -> None:
        container_body = ContainerBody()
        assembled = assemble_conversation_system_prompt(container_body)
        self.assertEqual(assembled, GOLDEN_PRE_P10_CONVERSATION_PROMPT)

    def test_container_identity_orientation_matches_golden(self) -> None:
        container_body = ContainerBody()
        desc = container_body.describe()
        message = (
            f"A — Orientation: I am an LLM-driven agent {desc.identity_orientation_context} "
            "I have a standing exploration goal, no name yet, and no memory before the files created now. "
            f"{desc.identity_operating_environment}"
        )
        self.assertEqual(message, GOLDEN_PRE_P10_STAGE_A_MESSAGE)

    def test_container_self_notes_preamble_matches_golden(self) -> None:
        container_body = ContainerBody()
        desc = container_body.describe()
        self.assertEqual(desc.notes_preamble, GOLDEN_PRE_P10_SELF_NOTES_PREAMBLE)

    def test_non_container_body_excludes_all_container_specific_strings(self) -> None:
        mock_body = MockNonContainerBody()
        assembled_sys = assemble_system_prompt(mock_body)
        assembled_conv = assemble_conversation_system_prompt(mock_body)
        desc = mock_body.describe()

        # Doc 10 Section 1A specific strings that must NOT be present in core or non-container prompt:
        container_strings = [
            "whose body is this Linux container",
            "You are root inside the container",
            "Docker container boundary",
            "/opt/agent/core/",
            "/home/entity/self/",
            "whose operating environment is this Linux container",
            "running inside this Linux container",
            "running in a Linux container",
            "Docker Linux container",
        ]

        for s in container_strings:
            self.assertNotIn(s, assembled_sys, f"Found container string '{s}' in assembled system prompt for non-container body")
            self.assertNotIn(s, assembled_conv, f"Found container string '{s}' in assembled conversation prompt for non-container body")
            self.assertNotIn(s, desc.notes_preamble, f"Found container string '{s}' in non-container notes preamble")
            self.assertNotIn(s, desc.identity_context, f"Found container string '{s}' in non-container identity context")

        # Verify that mock body custom rules ARE included in the assembled prompt
        self.assertIn("operating as an embedded controller.", assembled_sys)
        self.assertIn("Hardware watchdog timer triggers a reset", assembled_sys)
        self.assertIn("operating as an embedded controller.", assembled_conv)


if __name__ == "__main__":
    unittest.main()
