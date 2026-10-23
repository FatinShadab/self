"""Concrete capabilities exposed by ContainerBody."""
from __future__ import annotations

from agent.body.base import Capability


def get_container_capabilities() -> list[Capability]:
    """Return the concrete capabilities exposed by ContainerBody."""
    return [
        Capability(
            name="run_shell",
            schema={
                "type": "object",
                "properties": {
                    "cmd": {"type": "string", "description": "The command line string to run."},
                    "timeout": {
                        "type": "number",
                        "description": "Execution timeout in seconds; default 30.",
                        "default": 30,
                    },
                },
                "required": ["cmd"],
                "additionalProperties": False,
            },
            risk_class="executes",
            reversible=False,
        ),
        Capability(
            name="read_file",
            schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute or workspace-relative path to read."},
                    "max_chars": {
                        "type": "integer",
                        "description": "Maximum characters to return; bounded by output cap.",
                        "default": 20000,
                    },
                },
                "required": ["path"],
                "additionalProperties": False,
            },
            risk_class="reads",
            reversible=True,
        ),
        Capability(
            name="write_file",
            schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Workspace-relative or non-core path to write."},
                    "content": {"type": "string", "description": "Content to write or append."},
                    "append": {
                        "type": "boolean",
                        "description": "If true, append to file instead of overwriting.",
                        "default": False,
                    },
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
            risk_class="writes",
            reversible=False,
        ),
        Capability(
            name="list_dir",
            schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path to list."},
                    "max_entries": {
                        "type": "integer",
                        "description": "Maximum entries to return; capped at 5000.",
                        "default": 500,
                    },
                },
                "required": ["path"],
                "additionalProperties": False,
            },
            risk_class="reads",
            reversible=True,
        ),
        Capability(
            name="http_get",
            schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "HTTP or HTTPS URL to fetch."},
                    "timeout": {
                        "type": "number",
                        "description": "Request timeout in seconds; default 20.",
                        "default": 20,
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": "Maximum characters to return; bounded by output cap.",
                        "default": 20000,
                    },
                },
                "required": ["url"],
                "additionalProperties": False,
            },
            risk_class="network",
            reversible=True,
        ),
        Capability(
            name="probe_local_ollama",
            schema={"type": "object", "properties": {}, "additionalProperties": False},
            risk_class="reads",
            reversible=True,
        ),
    ]
