"""Regression tests verifying environment-agnostic prompts and expectation-framed body profiles."""
from __future__ import annotations

import re
import unittest

from agent.body.container import ContainerBody
from agent.infra.untrusted import UNTRUSTED_DATA_RULE
from agent.prompts.container_body import (
    CONTAINER_BODY_RULES,
    CONTAINER_CONVERSATION_CONTEXT,
    CONTAINER_DEFAULT_INTERESTS,
    CONTAINER_EMBODIMENT_CLAUSE,
    CONTAINER_EMBODIMENT_TEXT,
    CONTAINER_IDENTITY_CONTEXT,
    CONTAINER_IDENTITY_HARNESS_CONTEXT,
    CONTAINER_IDENTITY_OPERATING_ENVIRONMENT,
    CONTAINER_IDENTITY_ORIENTATION_CONTEXT,
    CONTAINER_INITIAL_ORIENTATION_TASK,
    CONTAINER_NOTES_PREAMBLE,
    CONTAINER_POST_CAPABILITY_RULES,
    CONTAINER_PRE_CAPABILITY_RULES,
    DEFAULT_NOTES_PREAMBLE,
)
from agent.prompts.conversation import (
    build_conversation_user_message,
    render_conversation_system_prompt,
)
from agent.prompts.cycle import (
    assemble_loop_system_prompt,
    build_cycle_user_message,
    build_model_context_block,
)
from agent.prompts.identity import (
    AUTONOMOUS_VOICE,
    NO_IDENTITY_RECORD_CONTEXT,
)
from agent.prompts.system import (
    CORE_CAPABILITY_RULE,
    CORE_IDENTITY_RULES,
    CORE_SYSTEM_PROMPT_HEAD,
    OPENCODE_CAPABILITY_PROMPT,
    ORIENTATION_TASK,
    STANDING_GOAL,
    render_core_system_prompt,
)
from agent.runtime.prompts import SYSTEM_PROMPT, assemble_system_prompt
from agent.session.conversation import assemble_conversation_system_prompt


FORBIDDEN_DEFAULT_TOKENS = [
    r"docker",
    r"container",
    r"linux",
    r"\broot\b",
    r"/home/entity",
    r"/opt/agent",
    r"/config/permissions\.json",
    r"whose body",
    r"your body",
    r"image-owned",
]


class TestEnvironmentAgnosticPrompts(unittest.TestCase):
    """Step 5.1 & 5.2 regression tests for environment-agnostic prompts."""

    def test_default_prompt_paths_contain_no_location_or_body_claims(self) -> None:
        """Verify that every default prompt path with NO body profile/plugin has zero forbidden tokens."""
        core_sys = render_core_system_prompt()
        loop_sys = assemble_loop_system_prompt(
            system_prompt=core_sys,
            model_context="",
            opencode_context="",
            identity_context=NO_IDENTITY_RECORD_CONTEXT,
            plugin_embodiment="",
            untrusted_rule=UNTRUSTED_DATA_RULE,
        )
        cycle_msg = build_cycle_user_message(
            cycle=1,
            helper_prompt="",
            plan_version=1,
            plan_summary="1. Discover environment.",
            primary_goal="Map environment with tools.",
            last_report="None.",
            actions_summary="None.",
            context="None.",
            plugin_section="",
            plugin_projects_section="",
            human_context="",
            failure_context="",
        )
        conv_prompt = render_conversation_system_prompt()
        conv_assembled = assemble_conversation_system_prompt(None)
        sys_assembled = assemble_system_prompt(None)

        prompt_targets = {
            "core_system_prompt": core_sys,
            "system_prompt_constant": SYSTEM_PROMPT,
            "assembled_system_prompt_none": sys_assembled,
            "loop_system_prompt": loop_sys,
            "cycle_user_message": cycle_msg,
            "conversation_prompt": conv_prompt,
            "assembled_conversation_prompt_none": conv_assembled,
            "identity_context_no_record": NO_IDENTITY_RECORD_CONTEXT,
            "default_notes_preamble": DEFAULT_NOTES_PREAMBLE,
            "orientation_task": ORIENTATION_TASK,
        }

        for path_name, text in prompt_targets.items():
            for pattern in FORBIDDEN_DEFAULT_TOKENS:
                match = re.search(pattern, text, re.IGNORECASE)
                self.assertIsNone(
                    match,
                    f"Forbidden token pattern '{pattern}' found in {path_name}:\n...{text[max(0, match.start()-40):match.end()+40] if match else ''}...",
                )

    def test_optional_container_profile_wraps_claims_as_expectations(self) -> None:
        """Verify that the optional container profile wraps claims as expectations with no unconditional facts."""
        container_body = ContainerBody()
        desc = container_body.describe()

        # Unconditional assertions that MUST NOT appear
        unconditional_prohibited = [
            r"\bYou are root\b",
            r"\bYour body is\b",
            r"\bThe Docker container boundary is\b",
        ]

        # Targets to inspect from the container profile
        profile_targets = {
            "embodiment_text": desc.embodiment_text,
            "embodiment_clause": desc.embodiment_clause,
            "pre_capability_rules": "\n".join(desc.pre_capability_rules),
            "post_capability_rules": "\n".join(desc.post_capability_rules),
            "body_rules": "\n".join(desc.body_rules),
            "notes_preamble": desc.notes_preamble,
            "conversation_context": desc.conversation_context,
            "identity_context": desc.identity_context,
            "identity_harness_context": desc.identity_harness_context,
            "identity_orientation_context": desc.identity_orientation_context,
            "identity_operating_environment": desc.identity_operating_environment,
        }

        for target_name, text in profile_targets.items():
            # Must not contain unconditional claims
            for pattern in unconditional_prohibited:
                match = re.search(pattern, text, re.IGNORECASE)
                self.assertIsNone(
                    match,
                    f"Unconditional claim '{pattern}' found in container profile {target_name}: '{text}'",
                )

            # Must contain expectation keywords: 'expects', 'expected', 'verify', or 'confirm'
            has_expectation = bool(
                re.search(r"\b(expects?|expected|verify|confirm)\b", text, re.IGNORECASE)
            )
            self.assertTrue(
                has_expectation,
                f"Container profile {target_name} lacks expectation/verification framing: '{text}'",
            )

        # Orientation task must encourage finding out with tools
        self.assertIn("Find out with tools", desc.initial_orientation_task)
        self.assertIn("Record each finding in the environment map", desc.initial_orientation_task)


if __name__ == "__main__":
    unittest.main()
