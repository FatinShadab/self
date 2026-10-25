"""Characterization tests: sha256 digests for all static prompt constants."""
from __future__ import annotations

import hashlib
import json
import unittest
from typing import Any

from agent.body.container import ContainerBody
from agent.helper_models.model_probe import PROBE_CASES
from agent.identity.identity import IdentityStore
from agent.identity.migration import AUTONOMOUS_VOICE
from agent.infra.untrusted import PERMISSION_RULE, STOP_RULE, UNTRUSTED_DATA_RULE
from agent.learning.plan import SEED_STANDING_GOAL
from agent.plugins.self_dev import PLUGIN_CRITIC_PROMPT
from agent.prompts.container_body import DEFAULT_NOTES_PREAMBLE
from agent.runtime.loop import (
    CORE_CAPABILITY_RULE,
    CORE_IDENTITY_RULES,
    CORE_SYSTEM_PROMPT_HEAD,
    OFF_PROMPT_PREFIXES,
    OPENCODE_CAPABILITY_PROMPT,
    ORIENTATION_TASK,
    STANDING_GOAL,
)
from agent.tools.tool_registry import CRITIC_PROMPT
from agent.ui.disk_tool_demo import BUILD_TASK, REUSE_TASK


def _sha256(val: str | bytes | list[Any] | tuple[Any, ...]) -> str:
    if isinstance(val, (list, tuple)):
        data = json.dumps(val).encode("utf-8")
    elif isinstance(val, str):
        data = val.encode("utf-8")
    else:
        data = val
    return hashlib.sha256(data).hexdigest()


EXPECTED_SHA256: dict[str, str] = {
    "STANDING_GOAL": "a095560402bc613c9e657760c537933f76c0c91335ed79a9b7d6f79c3ee72fef",
    "SEED_STANDING_GOAL": "a095560402bc613c9e657760c537933f76c0c91335ed79a9b7d6f79c3ee72fef",
    "OPENCODE_CAPABILITY_PROMPT": "b7200632a7c561e082fff90a17a48a421e1a83e37d024da4e4bbec194a2166f2",
    "CORE_SYSTEM_PROMPT_HEAD": "b6ea38c3885fe00e4049daca1c011c8c8aa50286ae80e4434a322e8c0fe091d6",
    "ORIENTATION_TASK": "3509635212ab4db40baf0b847ecf229ea58aae39327d4fa34da597e812c74dec",
    "CORE_CAPABILITY_RULE": "089463ce4df899138e28a10dfba9037adfc5f8b93922e58c85c79d546f06ae3c",
    "CORE_IDENTITY_RULES": "a23bd1349172e70bfe11e33514210e0aa14874fc14eb8fa3f29cfe2e023b55e8",
    "OFF_PROMPT_PREFIXES": "bcfb8705ff5e452c09f69c3d4ce5dec154da48765d969a1def19ca897764d411",
    "UNTRUSTED_DATA_RULE": "c2e31495f9eea0dbd288dab3663229c198c8b48ca6329dffb9666753d7fe5708",
    "STOP_RULE": "a369ebc021502fcd22d17823561bd445c2443bad20ff7f7f2906fca7787df9ab",
    "PERMISSION_RULE": "e8b2e4e02b3fffe3d66ffed26e96f3ba1017668c5d5b2b58ca350b50ec07dd6f",
    "CRITIC_PROMPT": "2e4fbf1586a287a79bcef6108e6f7017577276c2cb114f884b7fdc0a9485850a",
    "PLUGIN_CRITIC_PROMPT": "b8755bea6e9660274c631d5a7484313231f4282ee9d79e6d1d50f40d46dd9110",
    "PROBE_SYSTEM": "94428a7a7098bfc40c7fad28005b9c0a0b3dae101df8e7db064197abde085fd8",
    "PROBE_CASES": "76b3283ce17fc76b43c11febd856f362dd4c70797b5895b253d99ccafa1d823d",
    "BUILD_TASK": "84557175ceccaaa7dbb7e3b34ba892b0e4b6761fb07be5cac03a92042584be29",
    "REUSE_TASK": "d2a43896fc37b3191dc817ed61b8b4caf7d4991ba21c1651936a23db5ecac527",
    "AUTONOMOUS_VOICE": "5a0201f370cfc50f0a4f47af37a5ececf1903b0a29ca213be628b337c272fc8a",
    "CURRICULUM_TASKS": "4da81b6f988dfc8366ce7d20f9f9f643ed014402ca97b380f8fdae513fdec8f8",
    "DEFAULT_NOTES_PREAMBLE": "7b286be0d6ffef5a19a2f9a9b9976601708ffc163ac8dbc7ebb8d4bf07a2bd24",
    "CONTAINER_EMBODIMENT_TEXT": "d0f2b06bb9a3e7d0249c98b5409c3b058664bf769ee7a6197cfe3b4c0614f05d",
    "CONTAINER_EMBODIMENT_CLAUSE": "5de09430c51b6907c78dfa355deb41b9db5952de1f833d80cc68b3483b907650",
    "CONTAINER_PRE_CAPABILITY_RULES": "44300c1a11b377caa94550a33778b5e7fdc26b06b11441262cc2f02d3123133f",
    "CONTAINER_POST_CAPABILITY_RULES": "78e887e5c475fb9434d038950012dd1f991dc5ef9f73d0eb757285f6af382da1",
    "CONTAINER_BODY_RULES": "20f6fcbeabb3063bcf2fc9613b508a560ac63544cd550a02d8e0b17cd53ae76e",
    "CONTAINER_DEFAULT_INTERESTS": "bb9f6d3ef30ec8c7cd6e13d2353c59ddbcd1434ff0ed883c1d023695c6f7bd23",
    "CONTAINER_INITIAL_ORIENTATION_TASK": "a0fcd614035073e7711ecb3713d38ca819381e6b374817b37501b9d2ccd3ea90",
    "CONTAINER_CONVERSATION_CONTEXT": "67f11a4af73d3da0693add9626a2fc52de98cc83b0d3315af1cb1eaaa3be8d3c",
    "CONTAINER_IDENTITY_CONTEXT": "84a54c3bbc1c3be59361d69d7fc49fa24ced7103e98a40e31b54011c10a3978e",
    "CONTAINER_IDENTITY_HARNESS_CONTEXT": "efc909475a586d935d2476030377dcb34a677f90a1aff22d9d84a52a71e55258",
    "CONTAINER_IDENTITY_ORIENTATION_CONTEXT": "7c4b38c9fbefc52c744933d750ca6f1c0f08d24e396c4ecf99bd4ac09ed7c340",
    "CONTAINER_IDENTITY_OPERATING_ENVIRONMENT": "08f5155a49d59301846234741af3169ce882de766b4f453ef9bf421f9199a926",
    "CONTAINER_NOTES_PREAMBLE": "78b86f3caa28c31c42ab2c2f4c7c927eba28f634770516df8ad8285f4c82544d",
}


class StaticConstantsSha256Tests(unittest.TestCase):
    """Verify byte-for-byte SHA256 integrity of all moved static constants."""

    def test_all_static_constants_sha256(self) -> None:
        body = ContainerBody()
        desc = body.describe()

        probe_system = "You are taking a small public-data capability probe. Follow the user instruction exactly."
        curriculum_tasks = [
            "Inventory one environment category and record confidence-backed facts in the environment map.",
            "Compare two available commands or libraries, verify one with a small test, and record the useful capability.",
            "Identify a repetitive observation task and propose or build a carefully tested local tool for it.",
            "Exercise a previously created tool on a new input, verify its limits, and update its lesson or environment map.",
            "Design a bounded experiment combining two existing capabilities, then record verified outcomes and limits.",
        ]
        rewrite_notes_preamble = "I am SELF. I explore my environment, retain verified discoveries, and only register reviewed, tested tools."

        actuals = {
            "STANDING_GOAL": STANDING_GOAL,
            "SEED_STANDING_GOAL": SEED_STANDING_GOAL,
            "OPENCODE_CAPABILITY_PROMPT": OPENCODE_CAPABILITY_PROMPT,
            "ORIENTATION_TASK": ORIENTATION_TASK,
            "CORE_SYSTEM_PROMPT_HEAD": CORE_SYSTEM_PROMPT_HEAD,
            "CORE_CAPABILITY_RULE": CORE_CAPABILITY_RULE,
            "CORE_IDENTITY_RULES": CORE_IDENTITY_RULES,
            "OFF_PROMPT_PREFIXES": list(OFF_PROMPT_PREFIXES),
            "UNTRUSTED_DATA_RULE": UNTRUSTED_DATA_RULE,
            "STOP_RULE": STOP_RULE,
            "PERMISSION_RULE": PERMISSION_RULE,
            "CRITIC_PROMPT": CRITIC_PROMPT,
            "PLUGIN_CRITIC_PROMPT": PLUGIN_CRITIC_PROMPT,
            "PROBE_SYSTEM": probe_system,
            "PROBE_CASES": list(PROBE_CASES),
            "BUILD_TASK": BUILD_TASK,
            "REUSE_TASK": REUSE_TASK,
            "AUTONOMOUS_VOICE": AUTONOMOUS_VOICE,
            "CURRICULUM_TASKS": curriculum_tasks,
            "DEFAULT_NOTES_PREAMBLE": DEFAULT_NOTES_PREAMBLE,
            "CONTAINER_EMBODIMENT_TEXT": desc.embodiment_text,
            "CONTAINER_EMBODIMENT_CLAUSE": desc.embodiment_clause,
            "CONTAINER_PRE_CAPABILITY_RULES": desc.pre_capability_rules,
            "CONTAINER_POST_CAPABILITY_RULES": desc.post_capability_rules,
            "CONTAINER_BODY_RULES": desc.body_rules,
            "CONTAINER_DEFAULT_INTERESTS": desc.default_interests,
            "CONTAINER_INITIAL_ORIENTATION_TASK": desc.initial_orientation_task,
            "CONTAINER_CONVERSATION_CONTEXT": desc.conversation_context,
            "CONTAINER_IDENTITY_CONTEXT": desc.identity_context,
            "CONTAINER_IDENTITY_HARNESS_CONTEXT": desc.identity_harness_context,
            "CONTAINER_IDENTITY_ORIENTATION_CONTEXT": desc.identity_orientation_context,
            "CONTAINER_IDENTITY_OPERATING_ENVIRONMENT": desc.identity_operating_environment,
            "CONTAINER_NOTES_PREAMBLE": desc.notes_preamble,
        }

        self.assertEqual(STANDING_GOAL, SEED_STANDING_GOAL)
        self.assertEqual(DEFAULT_NOTES_PREAMBLE, rewrite_notes_preamble)

        for name, expected_hash in EXPECTED_SHA256.items():
            self.assertIn(name, actuals, f"Missing constant: {name}")
            actual_hash = _sha256(actuals[name])
            self.assertEqual(
                actual_hash,
                expected_hash,
                f"SHA256 mismatch for {name}: expected {expected_hash}, got {actual_hash}",
            )


if __name__ == "__main__":
    unittest.main()
