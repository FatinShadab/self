import json
import tempfile
import threading
import unittest
from pathlib import Path

from conversation import ConversationManager
from event_log import EventLogger
from hardening import DailyTokenLedger
from llm import LLMResult


class FakeConversationLLM:
    model = "conversation-test"
    provider = "test"

    def call(self, *, system, messages, tools, max_tokens):
        self.last_tools = tools
        return LLMResult([{"type": "text", "text": "The autonomous work is still running."}], 8, 7, "end_turn", self.model)


class ConversationTests(unittest.TestCase):
    def test_messages_run_in_bounded_read_only_threads_and_persist(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logger = EventLogger(root / "logs" / "actions.jsonl")
            fake = FakeConversationLLM()
            manager = ConversationManager(root, logger, DailyTokenLedger(root, logger, cap=50_000), fake, max_workers=2)
            done = []
            finished = threading.Event()

            def callback(thread_id, text, kind):
                done.append((thread_id, text, kind))
                if len(done) == 2:
                    finished.set()

            long_context = "state snapshot " * 900
            first = manager.submit("where are you?", lambda: long_context, callback)
            second = manager.submit("what is pending?", lambda: long_context, callback)
            self.assertTrue(finished.wait(5))
            manager.close()
            self.assertNotEqual(first, second)
            self.assertEqual({item[2] for item in done}, {"assistant"})
            records = [json.loads(line) for line in (root / "state" / "conversation_threads.jsonl").read_text().splitlines()]
            self.assertEqual(len(records), 4)
            self.assertEqual(fake.last_tools, [])


if __name__ == "__main__":
    unittest.main()
