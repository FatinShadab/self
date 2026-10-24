"""Constants and cryptographic hashing for custom workspace tools."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

CREATE_TOOL_DEFINITION = {
    "name": "create_tool",
    "description": (
        "Create or update a reusable Python tool. Supply code defining synchronous run(...) "
        "with JSON type annotations (str/int/float/bool/list/dict) and test_code defining a "
        "unittest.TestCase subclass (e.g. class TestTool(unittest.TestCase): def test_run(self): ...) "
        "that imports run from tool. An optional literal INPUT_SCHEMA overrides inference. "
        "Tests run with a timeout and a separate LLM critic must approve. Failure diagnostics "
        "permit at most 3 attempts per name per run. Passing updates retain the old version."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "pattern": "^[a-z][a-z0-9_]{0,63}$"},
            "description": {"type": "string"},
            "code": {"type": "string"},
            "test_code": {"type": "string"},
        },
        "required": ["name", "description", "code", "test_code"],
        "additionalProperties": False,
    },
}


def digest(text: str) -> str:
    """Return the SHA-256 digest of text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def timestamp() -> str:
    """Return the current UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()
