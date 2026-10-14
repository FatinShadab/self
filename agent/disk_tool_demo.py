"""Live Phase 3 acceptance test: model-written disk tool, then a fresh run."""
from __future__ import annotations

import json
from pathlib import Path

from base_tools import ToolRunner
from event_log import EventLogger
from llm import LLMClient
from loop import AgentConfig, AgentLoop


BUILD_TASK = """Build a reusable tool named disk_usage_summary using create_tool.
Summarize filesystem disk usage with shutil.disk_usage(path): total_bytes,
used_bytes, free_bytes, used_percent. Define run(path: str = '/home/entity').
Use only Python's standard library. Write meaningful unittest tests for a temp
directory and a missing path. On Linux used_bytes + free_bytes may be less than
total_bytes because of reserved filesystem blocks. Do not read environment variables, files, directory
listings, logs, or memories. This focused test exchanges generated source, critic
verdicts, test diagnostics, and numeric filesystem capacity with the configured
LLM provider. Once registered, call disk_usage_summary(path='/home/entity') and
report the numeric result. If it already exists, reuse it without creating a revision.
"""
REUSE_TASK = """Retrieve and call the existing disk_usage_summary tool for
/home/entity, then report its numeric disk usage result. Do not create or update
tools. Do not read environment variables, files, directories, logs, or memories.
"""


def main() -> int:
    workspace = Path("/home/entity")
    logger = EventLogger(workspace / "logs" / "actions.jsonl")
    for task in (BUILD_TASK, REUSE_TASK):
        config = AgentConfig(workspace=workspace, max_iterations=1, token_budget=50000,
                             top_k_tools=1, task=task, base_tool_names=(), retrieve_memories=False)
        start_offset = logger.path.stat().st_size if logger.path.exists() else 0
        loop = AgentLoop(config, logger, LLMClient(logger), ToolRunner(logger, workspace))
        summary = loop.run()
        if summary.reason != "max_iterations":
            raise RuntimeError(f"Acceptance run stopped: {summary.reason}")
        meta_path = workspace / "tools" / "disk_usage_summary" / "meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if not meta.get("registered") or not any(item["passed"] for item in meta["pass_fail_history"]):
            raise RuntimeError("Disk usage tool was not registered with passing tests")
        with logger.path.open("rb") as handle:
            handle.seek(start_offset)
            events = [json.loads(line) for line in handle]
        if not any(e["event"] == "custom_tool_executed" and e.get("name") == "disk_usage_summary" and e["exit_code"] == 0 for e in events):
            raise RuntimeError("Agent did not reuse the disk usage tool in this run")
        if not any(e["event"] == "tool_retrieval" and "disk_usage_summary" in e["selected"] for e in events):
            raise RuntimeError("Disk usage tool was not retrieved")
    logger.narrate("Verified: disk_usage_summary saved, critic-approved, tested, retrieved, and reused in a separate run.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
