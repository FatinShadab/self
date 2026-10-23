"""Core container body execution tool schemas (shell, files, network)."""
from __future__ import annotations

from typing import Any

from agent.tools.permissions import DEFAULT_OUTPUT_CAP

RUN_SHELL_DEFINITION: dict[str, Any] = {
        "name": "run_shell",
        "description": "Run an unrestricted Bash command inside the container as root, with a timeout and bounded returned output.",
        "input_schema": {
            "type": "object",
            "properties": {
                "cmd": {"type": "string", "description": "Bash command to run."},
                "timeout": {"type": "number", "description": "Timeout in seconds.", "default": 30},
            },
            "required": ["cmd"],
        },
    }

READ_FILE_DEFINITION: dict[str, Any] = {
        "name": "read_file",
        "description": "Read a UTF-8 text file from the container, returning bounded content.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "max_chars": {"type": "integer", "default": DEFAULT_OUTPUT_CAP},
            },
            "required": ["path"],
        },
    }

WRITE_FILE_DEFINITION: dict[str, Any] = {
        "name": "write_file",
        "description": "Write or append UTF-8 text inside the container except the image-owned /opt/agent harness (including /opt/agent/core). Use propose_core_patch for a core change. Parent directories are created automatically.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
                "append": {"type": "boolean", "default": False},
            },
            "required": ["path", "content"],
        },
    }

LIST_DIR_DEFINITION: dict[str, Any] = {
        "name": "list_dir",
        "description": "List a directory inside the container.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "max_entries": {"type": "integer", "default": 500},
            },
            "required": ["path"],
        },
    }

HTTP_GET_DEFINITION: dict[str, Any] = {
        "name": "http_get",
        "description": "Make an HTTP or HTTPS GET request. Network logs contain only the host and path, never queries or credentials.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "timeout": {"type": "number", "default": 20},
                "max_chars": {"type": "integer", "default": DEFAULT_OUTPUT_CAP},
            },
            "required": ["url"],
        },
    }
