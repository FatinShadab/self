"""SELF task prompts."""
from __future__ import annotations

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

CURRICULUM_TASKS: list[str] = [
    "Inventory one environment category and record confidence-backed facts in the environment map.",
    "Compare two available commands or libraries, verify one with a small test, and record the useful capability.",
    "Identify a repetitive observation task and propose or build a carefully tested local tool for it.",
    "Exercise a previously created tool on a new input, verify its limits, and update its lesson or environment map.",
    "Design a bounded experiment combining two existing capabilities, then record verified outcomes and limits.",
]
