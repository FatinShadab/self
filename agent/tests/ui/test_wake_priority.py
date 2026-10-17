"""Test startup priority ordering between helper model evaluation and package inventory."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from agent.infra.event_log import EventLogger
from agent.llm.llm import LLMResult
from agent.ui.wake import WakeCoordinator


class FakeHelperModelRegistry:
    def __init__(self, needing: list[str]) -> None:
        self._needing = needing

    def helpers_needing_evaluation(self) -> list[str]:
        return list(self._needing)


class FakeLLMWithRegistry:
    def __init__(self, needing: list[str]) -> None:
        self.model_registry = FakeHelperModelRegistry(needing)
        self.tokens_used = 0

    def call(self, **kwargs: Any) -> LLMResult:
        return LLMResult(
            content=[{"type": "text", "text": "OK"}],
            input_tokens=10,
            output_tokens=5,
            stop_reason="end_turn",
            model="mock",
        )


class WakePriorityTests(unittest.TestCase):
    def test_helper_model_onboarding_comes_before_package_inventory(self) -> None:
        """Requirement D: When helper models need evaluation, onboarding must come first."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fake_llm = FakeLLMWithRegistry(needing=["helper-alpha", "helper-beta"])
            coord = WakeCoordinator(root, llm_client=fake_llm, max_iterations=0)

            # Packages are uninventoried (packages entry missing from map.json)
            # Boot and run session (max_iterations=0 performs startup checks without starting loop cycles)
            coord.run()

            # Check narrations
            events = [
                json.loads(line) for line in (root / "logs" / "actions.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            narrations = [e.get("message", "") for e in events if e.get("event") == "narration"]
            helper_narration_idx = next(
                (i for i, text in enumerate(narrations) if "helper models needing evaluation" in text), None
            )
            package_narration_idx = next(
                (i for i, text in enumerate(narrations) if "inventory installed Python packages" in text), None
            )

            self.assertIsNotNone(helper_narration_idx, "Helper model evaluation narration not found")
            self.assertIsNotNone(package_narration_idx, "Package inventory narration not found")
            self.assertLess(
                helper_narration_idx,
                package_narration_idx,
                "Helper model onboarding must be narrated before package inventory",
            )


if __name__ == "__main__":
    unittest.main()
