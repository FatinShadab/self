"""Regression tests verifying environment-agnostic prompts and expectation-framed body profiles."""
from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from agent.body.container import ContainerBody
from agent.body.simulation.description import build_sim_description
from agent.identity.identity import IdentityStore
from agent.identity.store.first_awakening import (
    write_code_explanation,
    write_self_inquiry,
)
from agent.identity.store.schema import get_default_identity
from agent.infra.event_log import EventLogger
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
from agent.session.session import default_plan
from agent.tools.definitions import TOOL_DEFINITIONS, get_tool_definitions

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

    def test_tool_schemas_environment_neutral_in_default_path(self) -> None:
        """Verify that all default tool schemas in TOOL_DEFINITIONS contain no location or body claims."""
        for tool in TOOL_DEFINITIONS:
            name = tool["name"]
            desc = tool.get("description", "")
            for pattern in FORBIDDEN_DEFAULT_TOKENS:
                match = re.search(pattern, desc, re.IGNORECASE)
                self.assertIsNone(
                    match,
                    f"Forbidden token pattern '{pattern}' found in tool '{name}' description: '{desc}'",
                )

            # Check input schema properties descriptions
            properties = tool.get("input_schema", {}).get("properties", {})
            for prop_name, prop_spec in properties.items():
                if isinstance(prop_spec, dict) and "description" in prop_spec:
                    prop_desc = prop_spec["description"]
                    for pattern in FORBIDDEN_DEFAULT_TOKENS:
                        match = re.search(pattern, prop_desc, re.IGNORECASE)
                        self.assertIsNone(
                            match,
                            f"Forbidden token pattern '{pattern}' in tool '{name}' prop '{prop_name}': '{prop_desc}'",
                        )

        # get_tool_definitions with no body produces neutral tools
        defs_none = get_tool_definitions(body=None)
        self.assertEqual(len(defs_none), len(TOOL_DEFINITIONS))
        for tool in defs_none:
            for pattern in FORBIDDEN_DEFAULT_TOKENS:
                self.assertIsNone(re.search(pattern, tool.get("description", ""), re.IGNORECASE))

        # get_tool_definitions with ContainerBody supplies expectation-framed descriptions
        container_body = ContainerBody()
        defs_container = get_tool_definitions(body=container_body)
        shell_def = next(t for t in defs_container if t["name"] == "run_shell")
        self.assertIn("expects a Linux container", shell_def["description"])

    def test_identity_fallbacks_contain_no_location_or_body_claims(self) -> None:
        """Verify identity fallbacks and default identity schema contain no location or body claims."""
        with tempfile.TemporaryDirectory() as temp:
            temp_path = Path(temp)
            logger = EventLogger(temp_path / "logs" / "actions.jsonl")
            identity_store = IdentityStore(temp_path, logger, body=None)

            # run_first_awakening stage A fallback message
            messages = identity_store.run_first_awakening("test-sess")
            stage_a = messages[0]
            for pattern in FORBIDDEN_DEFAULT_TOKENS:
                match = re.search(pattern, stage_a, re.IGNORECASE)
                self.assertIsNone(
                    match,
                    f"Forbidden token pattern '{pattern}' found in stage A orientation message: '{stage_a}'",
                )

        # Check default identity interests
        default_id = get_default_identity(body=None)
        interests = [item["interest"] for item in default_id["interests"]]
        self.assertIn("mapping my environment accurately", interests)
        for interest in interests:
            for pattern in FORBIDDEN_DEFAULT_TOKENS:
                self.assertIsNone(
                    re.search(pattern, interest, re.IGNORECASE),
                    f"Forbidden token pattern '{pattern}' found in default interest: '{interest}'",
                )

    def test_session_seed_goal_reuses_standing_goal_and_is_neutral(self) -> None:
        """Verify that the default persistent plan seed goal reuses STANDING_GOAL and has no container wording."""
        plan = default_plan()
        self.assertTrue(len(plan) >= 1)
        seed_why = plan[0]["why"]
        self.assertEqual(seed_why, STANDING_GOAL)
        for pattern in FORBIDDEN_DEFAULT_TOKENS:
            self.assertIsNone(
                re.search(pattern, seed_why, re.IGNORECASE),
                f"Forbidden token pattern '{pattern}' found in default plan seed why: '{seed_why}'",
            )

    def test_first_awakening_generated_files_contain_no_static_claims(self) -> None:
        """Verify that state/self_inquiry.md and state/self_code_explanation.md have no static Docker/path claims."""
        with tempfile.TemporaryDirectory() as temp:
            temp_path = Path(temp)
            state_dir = temp_path / "state"
            state_dir.mkdir(parents=True)
            self_dir = temp_path / "self"
            self_dir.mkdir(parents=True)
            core_dir = temp_path / "core"
            core_dir.mkdir(parents=True)

            logger = EventLogger(temp_path / "logs" / "actions.jsonl")
            inquiry_path = state_dir / "self_inquiry.md"
            explanation_path = state_dir / "self_code_explanation.md"

            write_self_inquiry(inquiry_path, core_dir, body=None, redactor=logger.redactor, self_root=self_dir)
            write_code_explanation(explanation_path, core_dir, self_dir, redactor=logger.redactor)

            inquiry_text = inquiry_path.read_text(encoding="utf-8")
            explanation_text = explanation_path.read_text(encoding="utf-8")

            # Must contain verified and unverified markers for backward compatibility
            self.assertIn("**Verified.**", inquiry_text)
            self.assertIn("**Unverified.**", inquiry_text)

            # Neither file may contain static container/root/path claims in the default neutral path
            forbidden_files_tokens = [
                r"docker",
                r"container",
                r"linux",
                r"\broot\b",
                r"/home/entity",
                r"/opt/agent",
                r"image-owned",
            ]
            for pattern in forbidden_files_tokens:
                match_inq = re.search(pattern, inquiry_text, re.IGNORECASE)
                self.assertIsNone(
                    match_inq,
                    f"Forbidden token '{pattern}' found in self_inquiry.md:\n{inquiry_text}",
                )
                match_exp = re.search(pattern, explanation_text, re.IGNORECASE)
                self.assertIsNone(
                    match_exp,
                    f"Forbidden token '{pattern}' found in self_code_explanation.md:\n{explanation_text}",
                )

    def test_simulation_body_profile_wraps_claims_as_expectations(self) -> None:
        """Verify that the simulation body profile frames its embodiment as expectations."""
        desc = build_sim_description({})

        unconditional_prohibited = [
            r"\bYour body is\b",
        ]
        for pattern in unconditional_prohibited:
            self.assertIsNone(
                re.search(pattern, desc.embodiment_text, re.IGNORECASE),
                f"Unconditional claim '{pattern}' found in SimBody embodiment_text: '{desc.embodiment_text}'",
            )

        # Must contain expectation keywords: 'expects' or 'expected'
        self.assertTrue(
            bool(re.search(r"\b(expects?|expected)\b", desc.embodiment_text, re.IGNORECASE)),
            f"SimBody embodiment_text lacks expectation framing: '{desc.embodiment_text}'",
        )
        self.assertTrue(
            bool(re.search(r"\b(expects?|expected)\b", desc.notes_preamble, re.IGNORECASE)),
            f"SimBody notes_preamble lacks expectation framing: '{desc.notes_preamble}'",
        )

    def test_verification_criteria(self) -> None:
        """Verify (a) request_capability behavior, (b) default tools and permissions, and (c) voice consistency."""
        # (a) request_capability enforces stop-until-resolved and records credential request
        with tempfile.TemporaryDirectory() as temp:
            temp_path = Path(temp)
            logger = EventLogger(temp_path / "logs" / "actions.jsonl")
            from agent.infra.hardening import CapabilityRequests
            cap_requests = CapabilityRequests(temp_path, logger)
            result = cap_requests.request(
                kind="credential",
                summary="Need API key for model",
                reason="Expanding inference capabilities",
                provider="groq",
                env_names=["GROQ_API_KEY"],
            )
            self.assertFalse(result["ok"], "request_capability must return ok=False to enforce stop-until-resolved")
            self.assertEqual(result["status"], "human_approval_required")
            req_content = (temp_path / "state" / "capability_requests.md").read_text(encoding="utf-8")
            self.assertIn("GROQ_API_KEY", req_content)
            self.assertIn("Human action required", req_content)

        # (b) Default tool list and permissions match base
        from agent.tools.permissions import TOOL_PERMISSION_LEVELS
        expected_base_tools = {
            "list_models", "record_model_assessment", "probe_model", "research_model",
            "ask_model", "record_delegation_outcome", "run_shell", "read_file",
            "write_file", "list_dir", "http_get", "update_environment_map",
            "read_plan", "update_plan", "research_provider", "record_provider_verification",
            "request_provider_key", "ask_brain", "benchmark_providers", "probe_local_ollama",
            "request_capability", "propose_core_patch", "read_cost_ledger", "propose_plugin",
            "scaffold_plugin", "validate_plugin", "test_plugin", "request_plugin_review",
        }
        actual_tool_names = {t["name"] for t in TOOL_DEFINITIONS}
        self.assertEqual(actual_tool_names, expected_base_tools)
        for tool_name in ["run_shell", "write_file", "read_file", "list_dir", "http_get", "request_capability"]:
            self.assertIn(tool_name, TOOL_PERMISSION_LEVELS)

        # (c) Voice of the protected-code bullet matches its neighbors
        self.assertIn(
            "- Some of your own code is protected; you cannot modify it directly, propose an evidence-backed patch for the human to apply.",
            CORE_SYSTEM_PROMPT_HEAD,
        )
        self.assertNotIn(
            "- Some of my own code is protected",
            CORE_SYSTEM_PROMPT_HEAD,
        )


if __name__ == "__main__":
    unittest.main()
