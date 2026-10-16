"""SELF test coverage module."""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.learning.exploration_coverage import build_coverage, directory_visits, registered_tools


def _event(event: str, tool: str, **values: object) -> str:
    return json.dumps({"event": event, "tool": tool, **values})


class CoverageTests(unittest.TestCase):
    def test_visits_count_successful_listings_and_file_reads_across_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            log = Path(temp) / "actions.jsonl"
            log.write_text("\n".join([
                _event("tool_call", "list_dir", arguments={"path": "/etc"}),
                _event("tool_result", "list_dir", ok=True),
                _event("tool_call", "read_file", arguments={"path": "/etc/passwd"}),
                _event("tool_result", "read_file", ok=True),
                _event("tool_call", "list_dir", arguments={"path": "/etc"}),
                _event("tool_result", "list_dir", ok=True),
                _event("tool_call", "read_file", arguments={"path": "state/map.json"}),
                _event("tool_result", "read_file", ok=True),
                _event("tool_call", "read_file", arguments={"path": "state/missing.json"}),
                _event("tool_result", "read_file", ok=False),
                _event("tool_call", "run_shell", arguments={"cmd": "ls /secret"}),
                _event("tool_result", "run_shell", ok=True),
                "{bad json",
            ]) + "\n", encoding="utf-8")
            self.assertEqual(directory_visits(log), (("/etc", 3), ("/home/entity/state", 1)))

    def test_missing_log_has_no_visits(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(directory_visits(Path(temp) / "missing.jsonl"), ())

    def test_tools_require_registration_valid_name_and_intact_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)

            def save(name: str, *, registered: bool = True, intact: bool = True) -> None:
                folder = root / name
                folder.mkdir()
                code = "def run() -> str:\n    return 'ok'\n"
                tests = "import unittest\n"
                (folder / "tool.py").write_text(code, encoding="utf-8")
                (folder / "test_tool.py").write_text(tests, encoding="utf-8")
                meta = {
                    "name": name, "description": "  Explain   the tool\nbriefly. ",
                    "registered": registered,
                    "code_sha256": hashlib.sha256(code.encode()).hexdigest(),
                    "test_sha256": hashlib.sha256(tests.encode()).hexdigest(),
                }
                if not intact:
                    meta["code_sha256"] = "wrong"
                (folder / "meta.json").write_text(json.dumps(meta), encoding="utf-8")

            save("good_tool")
            save("failed_tool", registered=False)
            save("edited_tool", intact=False)
            save("read_file")
            save("Bad_Name")
            (root / "broken_tool").mkdir()
            (root / "broken_tool" / "meta.json").write_text("{invalid", encoding="utf-8")
            self.assertEqual(registered_tools(root, {"read_file"}), (("good_tool", "Explain the tool briefly."),))
            self.assertEqual(build_coverage(Path(temp)).total_visits, 0)

    def test_coverage_navigation_keeps_main_view_and_activity(self) -> None:
        try:
            from textual.app import App
            from textual.containers import Horizontal, VerticalScroll
            from textual.widgets import Input, Static
        except ImportError:
            self.skipTest("The agent's TUI dependencies are not installed in this test environment")
        fake_anthropic = types.ModuleType("anthropic")
        fake_anthropic.Anthropic = object
        with patch.dict(sys.modules, {"anthropic": fake_anthropic}):
            from agent.ui.wake import WakeCoordinator, run_tui

        with tempfile.TemporaryDirectory() as temp:
            coordinator = WakeCoordinator(temp, llm_client=object())

            async def exercise(app: App) -> None:
                app._start_agent = lambda: False
                async with app.run_test(size=(120, 40)) as pilot:
                    body = app.query_one("#body", Horizontal)
                    worklog = app.query_one("#worklog", VerticalScroll)
                    chat = app.query_one("#chat", Input)
                    await worklog.mount(*(Static(f"prior activity {index}") for index in range(40)))
                    await pilot.pause()
                    worklog.scroll_to(y=5, animate=False)
                    await pilot.pause()
                    previous_scroll = worklog.scroll_y
                    self.assertGreater(previous_scroll, 0)
                    chat.focus()
                    chat.value = "/coverage"
                    await pilot.press("enter")
                    self.assertTrue(app._coverage_open)
                    self.assertEqual(body.styles.display, "none")
                    self.assertEqual(app.query_one("#coverage", VerticalScroll).styles.display, "block")
                    for _ in range(100):
                        if "Directories explored:" in str(app.query_one("#coverage-content", Static).renderable):
                            break
                        await asyncio.sleep(0.01)
                    self.assertIn("Directories explored:", str(app.query_one("#coverage-content", Static).renderable))
                    app._queue_activity("agent kept working")
                    await pilot.pause()
                    chat.value = "/back"
                    await pilot.press("enter")
                    self.assertFalse(app._coverage_open)
                    self.assertIs(app.query_one("#body", Horizontal), body)
                    self.assertEqual(body.styles.display, "block")
                    await pilot.pause()
                    self.assertEqual(worklog.scroll_y, previous_scroll)
                    self.assertTrue(any("agent kept working" in str(item.renderable) for item in worklog.children))
                    self.assertFalse(coordinator.stop_requested)

            def run_test(app: App, **_: object) -> None:
                asyncio.run(exercise(app))

            with patch.object(App, "run", run_test):
                run_tui(coordinator)


if __name__ == "__main__":
    unittest.main()
