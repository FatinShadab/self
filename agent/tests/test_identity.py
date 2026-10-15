from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from base_tools import ToolRunner
from event_log import EventLogger
from identity import IdentityStore
from llm import LLMResult
from loop import AgentConfig, AgentLoop


class IdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name)
        self.core = self.workspace / "test-core"
        self.core.mkdir()
        source_markers = {
            "loop.py": "STANDING_GOAL = 'map'\nclass AgentLoop: pass\n",
            "base_tools.py": "class ToolRunner: pass\n",
            "hardening.py": "class DailyTokenLedger: pass\nclass CapabilityRequests: pass\n",
            "event_log.py": "class SecretRedactor: pass\nclass EventLogger: pass\n",
            "tool_registry.py": "class ToolRegistry: pass\n",
        }
        for filename, source in source_markers.items():
            (self.core / filename).write_text(source, encoding="utf-8")
        self.logger = EventLogger(self.workspace / "logs" / "actions.jsonl")
        self.identity = IdentityStore(self.workspace, self.logger, core_root=self.core)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_first_awakening_writes_a_to_e_and_evidence_files(self) -> None:
        messages = self.identity.run_first_awakening("session-a")

        self.assertEqual(len(messages), 5)
        identity = json.loads((self.workspace / "state" / "identity.json").read_text(encoding="utf-8"))
        self.assertIsNone(identity["name"])
        self.assertEqual(identity["traits"], [])
        inquiry = (self.workspace / "state" / "self_inquiry.md").read_text(encoding="utf-8")
        explanation = (self.workspace / "state" / "self_code_explanation.md").read_text(encoding="utf-8")
        self.assertIn("**Verified.**", inquiry)
        self.assertIn("**Unverified.**", inquiry)
        self.assertIn(f"{self.core / 'loop.py'}:", explanation)
        self.assertTrue((self.workspace / "self" / "README.md").exists())
        self.assertTrue((self.workspace / "state" / "about_human.md").exists())
        self.assertEqual(self.identity.run_first_awakening("session-b"), [])

    def test_name_human_notes_and_evidence_backed_traits_are_logged(self) -> None:
        self.identity.run_first_awakening("session-a")
        renamed = self.identity.set_name("Atlas", "session-a")
        self.assertEqual(renamed["name"], "Atlas")
        self.assertEqual(renamed["named_by"], "human")
        self.assertEqual(renamed["name_context"]["status"], "matched")
        self.assertIn("mapping", renamed["name_context"]["associations"])
        self.assertFalse(self.identity.awaiting_name())
        self.assertTrue(self.identity.record_human_answer("Please keep updates concise.", "session-a"))
        about_lines = self.identity.about_human_text().splitlines()
        chosen_line = next(index for index, value in enumerate(about_lines, start=1) if "Please keep" in value)
        self.assertIn("Removed line", self.identity.delete_human_line(chosen_line, "session-a"))

        self.logger.log("tool_call", tool="update_environment_map")
        self.logger.log("tool_result", tool="update_environment_map", ok=True)
        traits = self.identity.reflect_session("session-a", "2000-01-01T00:00:00+00:00")
        self.assertIn("evidence-oriented", traits)
        log = (self.workspace / "state" / "identity_log.md").read_text(encoding="utf-8")
        self.assertIn("Name changed from unnamed to Atlas", log)
        self.assertIn("Added trait: evidence-oriented", log)

    def test_core_write_is_rejected_and_patch_is_saved_for_review(self) -> None:
        self.identity.run_first_awakening("session-a")
        runner = ToolRunner(self.logger, self.workspace, core_root=self.core)
        runner.identity = self.identity
        protected = runner.execute(
            "write_file",
            {"path": str(self.core / "loop.py"), "content": "changed\n"},
        )
        self.assertFalse(protected["ok"])
        self.assertIn("propose_core_patch", protected["error"])
        self.assertIn("STANDING_GOAL", (self.core / "loop.py").read_text(encoding="utf-8"))
        managed = runner.execute(
            "write_file",
            {"path": str(self.workspace / "state" / "identity.json"), "content": "{}\n"},
        )
        self.assertFalse(managed["ok"])
        self.assertIn("Identity-managed", managed["error"])

        proposal = runner.execute(
            "propose_core_patch",
            {
                "name": "improve-stop-check",
                "reasoning": "Observed a missing safe-boundary check in a hypothetical test.",
                "diff": "--- a/loop.py\n+++ b/loop.py\n@@\n-old\n+new\n",
            },
        )
        self.assertTrue(proposal["ok"])
        self.assertFalse(proposal["applied"])
        patch = Path(proposal["path"])
        self.assertTrue(patch.exists())
        self.assertIn("human review", patch.read_text(encoding="utf-8"))

    def test_identity_is_loaded_into_each_model_system_prompt(self) -> None:
        self.identity.run_first_awakening("session-a")
        self.identity.set_name("Atlas", "session-a")

        class CapturingLLM:
            def __init__(self) -> None:
                self.systems: list[str] = []

            def call(self, **kwargs: object) -> LLMResult:
                self.systems.append(str(kwargs["system"]))
                return LLMResult(
                    content=[{"type": "text", "text": "Completed a bounded check."}],
                    input_tokens=1,
                    output_tokens=1,
                    stop_reason="end_turn",
                    model="fake",
                )

        fake = CapturingLLM()
        runner = ToolRunner(self.logger, self.workspace, core_root=self.core)
        runner.identity = self.identity
        AgentLoop(
            AgentConfig(
                workspace=self.workspace,
                max_iterations=1,
                token_budget=10_000,
                identity_context_provider=self.identity.prompt_context,
            ),
            self.logger,
            fake,
            runner,
        ).run()
        self.assertEqual(len(fake.systems), 1)
        self.assertIn('"name": "Atlas"', fake.systems[0])
        self.assertIn('"name_context"', fake.systems[0])
        self.assertIn("dependable support", fake.systems[0])
        self.assertIn("not evidence of sentience", fake.systems[0])

    def test_unknown_name_gets_honest_non_inferential_context(self) -> None:
        identity = self.identity.set_name("Xylophonic", "session-a")
        self.assertEqual(identity["name_context"]["status"], "unresolved")
        self.assertIn("Do not infer personality", identity["name_context"]["style_cue"])

    def test_fictional_character_name_loads_character_context(self) -> None:
        identity = self.identity.set_name("Toothless", "session-a")
        context = identity["name_context"]
        self.assertEqual(context["kind"], "fictional_character")
        self.assertEqual(context["franchise"], "How to Train Your Dragon")
        self.assertIn("playful", context["character_traits"])
        self.assertIn("protective", self.identity.prompt_context())


if __name__ == "__main__":
    unittest.main()
