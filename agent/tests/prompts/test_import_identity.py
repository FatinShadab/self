"""Identity tests: verify that old import paths still resolve to the exact same objects."""
from __future__ import annotations

import unittest
from typing import Any

# Import from original modules
from agent.body.container import ContainerBody
from agent.helper_models.model_probe import PROBE_CASES as ORIG_PROBE_CASES
from agent.identity.identity import IdentityStore
from agent.identity.migration import AUTONOMOUS_VOICE as ORIG_AUTONOMOUS_VOICE
from agent.infra.untrusted import (
    PERMISSION_RULE as ORIG_PERMISSION_RULE,
    STOP_RULE as ORIG_STOP_RULE,
    UNTRUSTED_DATA_RULE as ORIG_UNTRUSTED_DATA_RULE,
)
from agent.learning.plan import SEED_STANDING_GOAL as ORIG_SEED_STANDING_GOAL
from agent.plugins.self_dev import PLUGIN_CRITIC_PROMPT as ORIG_PLUGIN_CRITIC_PROMPT
from agent.runtime.loop import (
    CORE_CAPABILITY_RULE as ORIG_CORE_CAPABILITY_RULE,
    CORE_IDENTITY_RULES as ORIG_CORE_IDENTITY_RULES,
    CORE_SYSTEM_PROMPT_HEAD as ORIG_CORE_SYSTEM_PROMPT_HEAD,
    OFF_PROMPT_PREFIXES as ORIG_OFF_PROMPT_PREFIXES,
    OPENCODE_CAPABILITY_PROMPT as ORIG_OPENCODE_CAPABILITY_PROMPT,
    STANDING_GOAL as ORIG_STANDING_GOAL,
    assemble_system_prompt as orig_assemble_system_prompt,
)
from agent.session.conversation import (
    assemble_conversation_system_prompt as orig_assemble_conversation_system_prompt,
)
from agent.tools.tool_registry import CRITIC_PROMPT as ORIG_CRITIC_PROMPT
from agent.ui.disk_tool_demo import (
    BUILD_TASK as ORIG_BUILD_TASK,
    REUSE_TASK as ORIG_REUSE_TASK,
)

try:
    import agent.prompts
    import agent.prompts.container_body
    import agent.prompts.conversation
    import agent.prompts.critics
    import agent.prompts.cycle
    import agent.prompts.delegation
    import agent.prompts.identity
    import agent.prompts.model_selection
    import agent.prompts.probes
    import agent.prompts.reflection
    import agent.prompts.safety
    import agent.prompts.system
    import agent.prompts.tasks
    HAS_PROMPTS = True
except ImportError:
    HAS_PROMPTS = False


class ImportIdentityTests(unittest.TestCase):
    """Verify that all old import paths continue to work and resolve identically."""

    def test_original_symbols_exist_and_are_non_empty(self) -> None:
        self.assertTrue(ORIG_STANDING_GOAL)
        self.assertTrue(ORIG_SEED_STANDING_GOAL)
        self.assertTrue(ORIG_OPENCODE_CAPABILITY_PROMPT)
        self.assertTrue(ORIG_CORE_SYSTEM_PROMPT_HEAD)
        self.assertTrue(ORIG_CORE_CAPABILITY_RULE)
        self.assertTrue(ORIG_CORE_IDENTITY_RULES)
        self.assertTrue(ORIG_OFF_PROMPT_PREFIXES)
        self.assertTrue(ORIG_UNTRUSTED_DATA_RULE)
        self.assertTrue(ORIG_STOP_RULE)
        self.assertTrue(ORIG_PERMISSION_RULE)
        self.assertTrue(ORIG_CRITIC_PROMPT)
        self.assertTrue(ORIG_PLUGIN_CRITIC_PROMPT)
        self.assertTrue(ORIG_PROBE_CASES)
        self.assertTrue(ORIG_BUILD_TASK)
        self.assertTrue(ORIG_REUSE_TASK)
        self.assertTrue(ORIG_AUTONOMOUS_VOICE)

    def test_new_and_old_resolve_to_same_objects(self) -> None:
        if not HAS_PROMPTS:
            self.skipTest("agent.prompts package not yet created (Phase 2 baseline)")

        from agent.prompts.safety import (
            UNTRUSTED_DATA_RULE,
            STOP_RULE,
            PERMISSION_RULE,
        )
        from agent.prompts.system import (
            STANDING_GOAL,
            OPENCODE_CAPABILITY_PROMPT,
            CORE_SYSTEM_PROMPT_HEAD,
            CORE_CAPABILITY_RULE,
            CORE_IDENTITY_RULES,
            OFF_PROMPT_PREFIXES,
        )
        from agent.prompts.critics import CRITIC_PROMPT, PLUGIN_CRITIC_PROMPT
        from agent.prompts.probes import PROBE_CASES
        from agent.prompts.tasks import BUILD_TASK, REUSE_TASK
        from agent.prompts.identity import AUTONOMOUS_VOICE

        self.assertIs(ORIG_UNTRUSTED_DATA_RULE, UNTRUSTED_DATA_RULE)
        self.assertIs(ORIG_STOP_RULE, STOP_RULE)
        self.assertIs(ORIG_PERMISSION_RULE, PERMISSION_RULE)
        self.assertIs(ORIG_STANDING_GOAL, STANDING_GOAL)
        self.assertIs(ORIG_SEED_STANDING_GOAL, STANDING_GOAL)
        self.assertIs(ORIG_OPENCODE_CAPABILITY_PROMPT, OPENCODE_CAPABILITY_PROMPT)
        self.assertIs(ORIG_CORE_SYSTEM_PROMPT_HEAD, CORE_SYSTEM_PROMPT_HEAD)
        self.assertIs(ORIG_CORE_CAPABILITY_RULE, CORE_CAPABILITY_RULE)
        self.assertIs(ORIG_CORE_IDENTITY_RULES, CORE_IDENTITY_RULES)
        self.assertIs(ORIG_OFF_PROMPT_PREFIXES, OFF_PROMPT_PREFIXES)
        self.assertIs(ORIG_CRITIC_PROMPT, CRITIC_PROMPT)
        self.assertIs(ORIG_PLUGIN_CRITIC_PROMPT, PLUGIN_CRITIC_PROMPT)
        self.assertIs(ORIG_PROBE_CASES, PROBE_CASES)
        self.assertIs(ORIG_BUILD_TASK, BUILD_TASK)
        self.assertIs(ORIG_REUSE_TASK, REUSE_TASK)
        self.assertIs(ORIG_AUTONOMOUS_VOICE, AUTONOMOUS_VOICE)


if __name__ == "__main__":
    unittest.main()
