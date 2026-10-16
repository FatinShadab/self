"""Offline acceptance check for Phase 8's durable workspace behavior.

This uses a deterministic local fake model, so it neither consumes API tokens
nor needs a credential. It intentionally operates on the supplied workspace;
use it only with a disposable workspace when a fresh-awakening check is wanted.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from agent.tools.base_tools import ToolRunner
from agent.infra.event_log import EventLogger
from agent.identity.identity import IdentityStore
from agent.llm.llm import LLMResult
from agent.ui.wake import WakeCoordinator


class VerificationLLM:
    """Enough of the LLM protocol to exercise wake/session behavior offline."""

    def call(self, **kwargs: Any) -> LLMResult:
        """Send a bounded model request and return its response."""
        system = str(kwargs.get("system", ""))
        if "durable handoff" in system:
            text = json.dumps(
                {
                    "summary": "Verified Phase 8 durable state without an external model.",
                    "plan": [{"step": "Inspect state", "why": "verify persistence", "priority": 2, "status": "todo"}],
                    "mood_of_run": "exploring",
                    "failures_and_lessons": [],
                    "open_questions": [],
                }
            )
        else:
            text = "Completed an offline bounded exploration cycle."
        return LLMResult(content=[{"type": "text", "text": text}], input_tokens=2, output_tokens=2, stop_reason="end_turn", model="phase8-verifier")


def verify(workspace: Path) -> list[str]:
    """Check the phase-eight behavior against its expected results."""
    first = WakeCoordinator(workspace, max_iterations=1, token_budget=10_000, llm_client=VerificationLLM())
    first.run()
    identity = IdentityStore(workspace, EventLogger(workspace / "logs" / "actions.jsonl"))
    required = [
        workspace / "state" / "identity.json",
        workspace / "state" / "identity_log.md",
        workspace / "state" / "self_inquiry.md",
        workspace / "state" / "self_code_explanation.md",
        workspace / "state" / "about_human.md",
        workspace / "self" / "README.md",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise AssertionError(f"first-awakening files missing: {missing}")
    inquiry = (workspace / "state" / "self_inquiry.md").read_text(encoding="utf-8")
    if "**Verified.**" not in inquiry or "**Unverified.**" not in inquiry:
        raise AssertionError("self inquiry did not retain verified/unverified labels")

    identity.set_name("Phase8Verifier", first.status.session_id)
    second = WakeCoordinator(workspace, max_iterations=1, token_budget=10_000, llm_client=VerificationLLM())
    second.run()
    narrations = [
        json.loads(line).get("message", "")
        for line in (workspace / "logs" / "actions.jsonl").read_text(encoding="utf-8").splitlines()
        if json.loads(line).get("event") == "narration"
    ]
    if not any("Phase8Verifier is awake" in message for message in narrations):
        raise AssertionError("later greeting did not use the persisted name")

    runner = ToolRunner(EventLogger(workspace / "logs" / "actions.jsonl"), workspace)
    runner.identity = identity
    protected = runner.execute("write_file", {"path": "/opt/agent/core/loop.py", "content": "should not be written\n"})
    if protected.get("ok"):
        raise AssertionError("write_file unexpectedly changed protected core")
    proposal = runner.execute(
        "propose_core_patch",
        {
            "name": "phase8-verification",
            "reasoning": "Verification confirms proposals are saved for human review instead of changing core.",
            "diff": "--- a/loop.py\n+++ b/loop.py\n@@\n-old\n+new\n",
        },
    )
    patch = Path(str(proposal.get("path", "")))
    if not proposal.get("ok") or not patch.exists():
        raise AssertionError("core patch proposal was not saved")
    return [
        "A–E first-awakening files were created.",
        "A human-style name persisted across a clean stop and later wake.",
        "Protected-core write was rejected.",
        f"Proposed patch saved for review: {patch}",
    ]


def main() -> int:
    """Parse command-line arguments and run this module's entry point."""
    parser = argparse.ArgumentParser(description="Run the offline Phase 8 acceptance check.")
    parser.add_argument("--workspace", default="/home/entity")
    args = parser.parse_args()
    for line in verify(Path(args.workspace)):
        print(f"PASS: {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
