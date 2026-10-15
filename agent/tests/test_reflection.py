from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any

from event_log import EventLogger
from hardening import DailyTokenLedger
from llm import LLMResult
from reflection import ReflectionManager
from wake import WakeCoordinator


class ReflectionLLM:
    model = "reflection-test"
    provider = "test"

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.calls: list[dict[str, Any]] = []

    def call(self, **kwargs: Any) -> LLMResult:
        self.calls.append(kwargs)
        text = self.replies.pop(0) if self.replies else '{"post": false, "message": "", "question": null}'
        return LLMResult([{"type": "text", "text": text}], 5, 7, "end_turn", self.model)


class BlockingReflectionLLM(ReflectionLLM):
    def __init__(self) -> None:
        super().__init__([
            '{"post": false, "message": "", "question": null}',
            '{"post": true, "message": "A later observation is useful.", "question": null}',
        ])
        self.started = threading.Event()
        self.release = threading.Event()

    def call(self, **kwargs: Any) -> LLMResult:
        if not self.started.is_set():
            self.started.set()
            self.release.wait(5)
        return super().call(**kwargs)


def _candidate(manager: ReflectionManager, cycle: int, callback: Any) -> bool:
    return manager.submit(
        session_id="session-a",
        cycle=cycle,
        report="Updated the environment map after a successful probe.",
        actions=[{"name": "update_environment_map", "ok": True}],
        triggers=["verified environment map updated"],
        context_provider=lambda *_: "Verified report and bounded state.",
        on_result=callback,
    )


class ReflectionTests(unittest.TestCase):
    def test_post_persists_question_and_reply_enters_human_inbox(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            llm = ReflectionLLM(['{"post": true, "message": "The map now has a verified disk fact.", "question": "Which area should I inspect next?"}'])
            coordinator = WakeCoordinator(root, llm_client=llm)
            coordinator.status.session_id = "session-a"
            coordinator.reflections.begin_session("session-a")
            complete = threading.Event()
            posted: list[dict[str, Any]] = []
            _candidate(coordinator.reflections, 1, lambda value: (posted.append(value), complete.set()))
            self.assertTrue(complete.wait(5))
            self.assertEqual(llm.calls[0]["tools"], [])
            self.assertEqual(posted[0]["question"], "Which area should I inspect next?")

            # A later coordinator sees the open question from durable state.
            resumed = WakeCoordinator(root, llm_client=ReflectionLLM([]))
            self.assertEqual(resumed.reflections.open_question(), {
                "thread_id": posted[0]["thread_id"],
                "question": "Which area should I inspect next?",
            })
            reply = resumed.accept_reflection_reply("Inspect network reachability.")
            self.assertIsNotNone(reply)
            inbox = resumed.inbox.consume()
            self.assertEqual(len(inbox), 1)
            self.assertIn("Inspect network reachability.", inbox[0])
            self.assertIsNone(resumed.reflections.open_question())

            records = [json.loads(line) for line in (root / "state" / "reflection_threads.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual([record["role"] for record in records], ["agent", "human"])
            self.assertEqual(records[0]["thread_id"], records[1]["thread_id"])
            coordinator.reflections.close()
            coordinator.conversations.close()
            resumed.reflections.close()
            resumed.conversations.close()

    def test_malformed_and_budget_limited_reflections_are_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logger = EventLogger(root / "logs" / "actions.jsonl")
            malformed = ReflectionManager(root, logger, DailyTokenLedger(root, logger, cap=50_000), ReflectionLLM(["not JSON"]))
            malformed.begin_session("session-a")
            result = malformed._reflect({
                "session_id": "session-a", "cycle": 1, "report": "report", "actions": [], "triggers": ["failure"],
                "context_provider": lambda *_: "state", "on_result": lambda _: None,
            })
            self.assertIsNone(result)
            malformed.close()

            constrained = ReflectionLLM(['{"post": true, "message": "never called", "question": null}'])
            limited = ReflectionManager(root, logger, DailyTokenLedger(root, logger, cap=1), constrained)
            limited.begin_session("session-b")
            result = limited._reflect({
                "session_id": "session-b", "cycle": 1, "report": "report", "actions": [], "triggers": ["failure"],
                "context_provider": lambda *_: "state", "on_result": lambda _: None,
            })
            self.assertIsNone(result)
            self.assertEqual(constrained.calls, [])
            limited.close()

    def test_newest_candidate_runs_after_a_busy_declined_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logger = EventLogger(root / "logs" / "actions.jsonl")
            llm = BlockingReflectionLLM()
            manager = ReflectionManager(root, logger, DailyTokenLedger(root, logger, cap=50_000), llm, min_cycles=1)
            manager.begin_session("session-a")
            done = threading.Event()
            posted: list[dict[str, Any]] = []
            self.assertTrue(_candidate(manager, 1, lambda value: (posted.append(value), done.set())))
            self.assertTrue(llm.started.wait(5))
            self.assertTrue(_candidate(manager, 2, lambda value: (posted.append(value), done.set())))
            llm.release.set()
            self.assertTrue(done.wait(5))
            self.assertEqual(len(llm.calls), 2)
            self.assertEqual(posted[0]["cycle"], 2)
            manager.close()

    def test_trigger_selection_is_deterministic_and_stop_suppresses_schedule(self) -> None:
        actions = [
            {"name": "update_environment_map", "ok": True},
            {"name": "create_tool", "ok": True},
            {"name": "shell", "ok": False},
            {"name": "list_dir", "ok": True},
        ]
        self.assertEqual(
            WakeCoordinator._reflection_triggers(actions),
            ["verified environment map updated", "tested tool created", "tool failed: shell"],
        )
        with tempfile.TemporaryDirectory() as temp:
            coordinator = WakeCoordinator(temp, llm_client=ReflectionLLM([]))
            coordinator.stop_requested = True
            coordinator._event_listener({"event": "cycle_completed", "cycle": 1, "report": "x", "actions": actions})
            self.assertFalse((Path(temp) / "state" / "reflection_threads.jsonl").exists())
            coordinator.reflections.close()
            coordinator.conversations.close()


if __name__ == "__main__":
    unittest.main()
