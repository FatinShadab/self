"""SELF test conversation module."""
import json
import tempfile
import threading
import unittest
from pathlib import Path

from agent.session.conversation import ConversationManager
from agent.infra.event_log import EventLogger
from agent.infra.hardening import DailyTokenLedger
from agent.identity.identity import IdentityStore
from agent.learning.plan import PlanStore
from agent.llm.client import BudgetExceeded
from agent.llm.llm import LLMResult
from agent.session.human_input import build_conversation_context
from agent.ui.tui.chat_pipeline import queue_chat
from agent.ui.tui.commands.handlers import PluginSlashCommandHandler, StateInfoCommandHandler


class FakeConversationLLM:
    model = "conversation-test"
    provider = "test"

    def call(self, *, system, messages, tools, max_tokens):
        self.last_tools = tools
        return LLMResult([{"type": "text", "text": "The autonomous work is still running."}], 8, 7, "end_turn", self.model)


class FailingBudgetLLM:
    model = "failing-test"
    provider = "test"

    def call(self, *, system, messages, tools, max_tokens):
        raise BudgetExceeded("Daily token limit reached")


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

            # Verify context builder includes loop status and pending human requests
            ident = IdentityStore(root, logger)
            plan_store = PlanStore(root, logger)
            ctx = build_conversation_context(
                ident, {}, plan_store, [], [], [],
                status_summary="Paused waiting on HUMAN_REQUEST.md",
                requests_summary="Docker socket mount needed",
            )
            self.assertIn("Current loop status:\nPaused waiting on HUMAN_REQUEST.md", ctx)
            self.assertIn("Pending requests / reports:\nDocker socket mount needed", ctx)

            # Verify BudgetExceeded fallback provides a user-friendly error message
            failing_mgr = ConversationManager(root, logger, DailyTokenLedger(root, logger, cap=50_000), FailingBudgetLLM(), max_workers=1)
            budget_done = threading.Event()
            budget_result = []

            def budget_cb(thread_id, text, kind):
                budget_result.append((text, kind))
                budget_done.set()

            failing_mgr.submit("check status", lambda: "context", budget_cb)
            self.assertTrue(budget_done.wait(5))
            failing_mgr.close()
            self.assertEqual(len(budget_result), 1)
            self.assertEqual(budget_result[0][1], "error")
            self.assertIn("daily token budget limit has been reached", budget_result[0][0])

            # Verify queue_chat allows conversational messages while stopped
            class DummyApp:
                def __init__(self):
                    self._pending_chat = []
                    self._draining_chat = True
                    self.commands = []
                def _write_command(self, cmd):
                    self.commands.append(cmd)
                def _command_response(self, resp, kind="info"):
                    self.commands.append((resp, kind))
                def _queue_chat(self, role, message, kind):
                    queue_chat(self, dummy_coord, role, message, kind)
                def run_worker(self, coro, exclusive=False):
                    pass

            class DummyCoord:
                def __init__(self, workspace):
                    self.workspace = workspace
                    self.stop_requested = True
                def handle_slash_command(self, text):
                    return None

            dummy_app = DummyApp()
            dummy_coord = DummyCoord(root)
            (root / "STOP").touch()

            # Autonomous cycle message is dropped when stopped
            queue_chat(dummy_app, dummy_coord, "agent", "late cycle update", "cycle")
            self.assertEqual(len(dummy_app._pending_chat), 0)

            # Interactive conversation message is NOT dropped when stopped
            queue_chat(dummy_app, dummy_coord, "agent", "conversation response", "conversation")
            self.assertEqual(len(dummy_app._pending_chat), 1)
            self.assertEqual(dummy_app._pending_chat[0][1], "conversation response")

            # Targets command message is NOT dropped when stopped
            queue_chat(dummy_app, dummy_coord, "agent", "targets response", "targets")
            self.assertEqual(len(dummy_app._pending_chat), 2)

            # Verify unknown slash command handling
            cmd_handler = PluginSlashCommandHandler()
            self.assertTrue(cmd_handler.matches("/unknown_test"))
            self.assertTrue(cmd_handler.handle(dummy_app, dummy_coord, "/unknown_test"))
            self.assertTrue(any("Unknown command '/unknown_test'" in str(c) for c in dummy_app.commands))

            # Verify /help command handling
            help_handler = StateInfoCommandHandler()
            self.assertTrue(help_handler.matches("/help"))
            self.assertTrue(help_handler.handle(dummy_app, dummy_coord, "/help"))
            self.assertTrue(any("Available commands:" in str(c) for c in dummy_app.commands))


if __name__ == "__main__":
    unittest.main()
