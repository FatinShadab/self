"""Characterization tests: sha256 digests for all static prompt constants."""
from __future__ import annotations

import hashlib
import json
import unittest

from agent.body.container import ContainerBody
from agent.helper_models.model_probe import PROBE_CASES
from agent.identity.identity import IdentityStore
from agent.identity.migration import AUTONOMOUS_VOICE
from agent.infra.untrusted import PERMISSION_RULE, STOP_RULE, UNTRUSTED_DATA_RULE
from agent.learning.plan import SEED_STANDING_GOAL
from agent.plugins.self_dev import PLUGIN_CRITIC_PROMPT
from agent.runtime.loop import (
    CORE_CAPABILITY_RULE,
    CORE_IDENTITY_RULES,
    CORE_SYSTEM_PROMPT_HEAD,
    OFF_PROMPT_PREFIXES,
    OPENCODE_CAPABILITY_PROMPT,
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
    "CORE_SYSTEM_PROMPT_HEAD": "0e4c30fe9a939ce631985b1d4f3460214256b0afecefecc2a6aafa2115bcaf7c",
    "CORE_CAPABILITY_RULE": "e9139688d69d8c1b3300e433b1415d536788d4d8cc810e8384ba7091536e172e",
    "CORE_IDENTITY_RULES": "a23bd1349172e70bfe11e33514210e0aa14874fc14eb8fa3f29cfe2e023b55e8",
    "OFF_PROMPT_PREFIXES": "bcfb8705ff5e452c09f69c3d4ce5dec154da48765d969a1def19ca897764d411",
    "UNTRUSTED_DATA_RULE": "c2e31495f9eea0dbd288dab3663229c198c8b48ca6329dffb9666753d7fe5708",
    "STOP_RULE": "a369ebc021502fcd22d17823561bd445c2443bad20ff7f7f2906fca7787df9ab",
    "PERMISSION_RULE": "4f1e3474f00dc69579f5501bf7a91b720cf0638dc1e46051154a9d852644b792",
    "CRITIC_PROMPT": "2e4fbf1586a287a79bcef6108e6f7017577276c2cb114f884b7fdc0a9485850a",
    "PLUGIN_CRITIC_PROMPT": "278bf6e76bfb50baa35b81cbc31c52969ebee2cf12a62522f419ab664142cef6",
    "PROBE_SYSTEM": "94428a7a7098bfc40c7fad28005b9c0a0b3dae101df8e7db064197abde085fd8",
    "PROBE_CASES": "76b3283ce17fc76b43c11febd856f362dd4c70797b5895b253d99ccafa1d823d",
    "BUILD_TASK": "84557175ceccaaa7dbb7e3b34ba892b0e4b6761fb07be5cac03a92042584be29",
    "REUSE_TASK": "d2a43896fc37b3191dc817ed61b8b4caf7d4991ba21c1651936a23db5ecac527",
    "AUTONOMOUS_VOICE": "5a0201f370cfc50f0a4f47af37a5ececf1903b0a29ca213be628b337c272fc8a",
    "CURRICULUM_TASKS": "4da81b6f988dfc8366ce7d20f9f9f643ed014402ca97b380f8fdae513fdec8f8",
    "DEFAULT_NOTES_PREAMBLE": "577d75c2349647155fc153047f03d07aa99c4dfca586c3a0b6c2ba58a8719a2f",
    "CONTAINER_EMBODIMENT_TEXT": "4906f776e0cec871ebe08240b6c45bdb81d5fc787e0b3dff25bfdea306a8431d",
    "CONTAINER_EMBODIMENT_CLAUSE": "417193c1afaef4d186147f416f39cf4ca571c65dd9c904d3bfe59acab324b9dd",
    "CONTAINER_PRE_CAPABILITY_RULES": "666fe1f42a51d585b4297538c1adf4bf4be5a744a29003d7e70be704b78fb0f4",
    "CONTAINER_POST_CAPABILITY_RULES": "3ef770968bb76fdb798d541aa2fee6152d93ab2acd358a43ccc4a4e0bb254075",
    "CONTAINER_BODY_RULES": "61535e86735d28c374c3f99a994c01c2fc68a282bed62ad2e42118739b3bce68",
    "CONTAINER_DEFAULT_INTERESTS": "2afd7d3a12f933ea89fd161f752188d036866a6bae57d3aa04c4a09caaa11813",
    "CONTAINER_INITIAL_ORIENTATION_TASK": "839fc5d51e48b3ecc121b1140ff224ab70fa619518b4312b0a2ecb2ad9c98c29",
    "CONTAINER_CONVERSATION_CONTEXT": "8e60bb0fbf54d8c8d83f3abb7099ed49ca47b812b7b7cd46fbde22071010e4bf",
    "CONTAINER_IDENTITY_CONTEXT": "cbafbdafbdb3b36601840322faebfed790a4d868ce5b7ab71d86c77c5cc3077d",
    "CONTAINER_IDENTITY_HARNESS_CONTEXT": "85c31ecaaed62dcc14b9388ba3cfa0eb8ed0d5f79fc61090c9e52cd8ebd0aa20",
    "CONTAINER_IDENTITY_ORIENTATION_CONTEXT": "13e151f67f5ecdbba8be838dd233ff3cfd60b97c3c7125e0d0fd8b73952105db",
    "CONTAINER_IDENTITY_OPERATING_ENVIRONMENT": "38cf4b90297ffc5257d1a5d3ff24a91c6a8f39461b07560e7b2979ac89251e37",
    "CONTAINER_NOTES_PREAMBLE": "577d75c2349647155fc153047f03d07aa99c4dfca586c3a0b6c2ba58a8719a2f",
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
        rewrite_notes_preamble = "I am SELF, a root process inside a Docker Linux container. I explore the container, retain verified discoveries, and only register reviewed, tested tools."

        actuals = {
            "STANDING_GOAL": STANDING_GOAL,
            "SEED_STANDING_GOAL": SEED_STANDING_GOAL,
            "OPENCODE_CAPABILITY_PROMPT": OPENCODE_CAPABILITY_PROMPT,
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
            "DEFAULT_NOTES_PREAMBLE": rewrite_notes_preamble,
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
        self.assertEqual(desc.notes_preamble, rewrite_notes_preamble)

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
