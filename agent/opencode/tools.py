"""Tool definitions and schemas for opencode delegation tools."""
from __future__ import annotations

from typing import Any

from agent.infra.permission_broker import PermissionLevel

OPENCODE_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "opencode_status",
        "description": (
            "Check opencode coding-agent CLI availability, provider health (Groq, Google AI Studio, "
            "Hugging Face), and throttling states without network access or probing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "name": "delegate_coding",
        "description": (
            "Delegate a scoped coding task to the opencode agent in an isolated repository sandbox. "
            "Runs opencode headless with automatic multi-provider fallback, verifies changes remain strictly "
            "inside target_dirs, and runs acceptance_check before completion. Returns a structured result "
            "and preserves the sandbox for review."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "spec": {
                    "type": "string",
                    "description": "Detailed specification of the coding task to accomplish.",
                },
                "route_reasons": {
                    "type": "string",
                    "description": "Required free text explaining why Self chose to delegate instead of doing it itself.",
                },
                "target_dirs": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of directories opencode is allowed to create or modify (must be inside allowed roots).",
                },
                "acceptance_check": {
                    "type": "string",
                    "description": "Shell command run by the harness in the sandbox to verify that the task was completed successfully.",
                },
                "model": {
                    "type": "string",
                    "description": "Optional model identifier in the format 'provider/model' (e.g. 'groq/llama-3.3-70b-versatile').",
                },
                "timeout_seconds": {
                    "type": "integer",
                    "description": "Timeout in seconds for the opencode subprocess (default 1800).",
                },
            },
            "required": ["spec", "route_reasons", "target_dirs", "acceptance_check"],
            "additionalProperties": False,
        },
    },
    {
        "name": "apply_delegation",
        "description": (
            "Apply changes from a completed delegation sandbox to the real repository. "
            "Only allowed when status is 'completed' and scope was clean. Copies changed files, "
            "re-runs the acceptance check against the real tree, and rolls back if it fails."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "delegation_id": {
                    "type": "string",
                    "description": "ID of the completed delegation to apply.",
                },
            },
            "required": ["delegation_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "discard_delegation",
        "description": "Discard a delegation record and delete its sandbox directory.",
        "input_schema": {
            "type": "object",
            "properties": {
                "delegation_id": {
                    "type": "string",
                    "description": "ID of the delegation to discard.",
                },
            },
            "required": ["delegation_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "record_build_route",
        "description": (
            "Record a deliberate decision to build a capability directly ('self') or delegate to 'opencode'. "
            "Writes a decision record using the checkpoint mechanism with origin label 'agent' (or 'forced:<reason>')."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "Task description or capability being built.",
                },
                "route": {
                    "type": "string",
                    "enum": ["self", "opencode"],
                    "description": "Route chosen: 'self' or 'opencode'.",
                },
                "reasons": {
                    "type": "string",
                    "description": "Reasoning explaining why this route was chosen.",
                },
                "expected_effort": {
                    "type": "string",
                    "description": "Estimated effort (e.g. 'low', 'medium', 'high', or token/cycle estimate).",
                },
                "forced_by": {
                    "type": "string",
                    "enum": ["opencode_unavailable", "human_request"],
                    "description": "Optional reason if this route was forced rather than chosen.",
                },
            },
            "required": ["task", "route", "reasons", "expected_effort"],
            "additionalProperties": False,
        },
    },
    {
        "name": "record_build_outcome",
        "description": (
            "Record the final outcome of a build task for route 'self' (e.g. accepted, failed, rejected). "
            "Delegations to opencode record outcomes automatically on apply, discard, or failure."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Task ID matching the recorded build route decision.",
                },
                "result": {
                    "type": "string",
                    "enum": ["accepted", "rejected", "failed", "abandoned", "unavailable"],
                    "description": "Final result of the build task.",
                },
                "notes": {
                    "type": "string",
                    "description": "Optional notes or details on the build outcome.",
                },
            },
            "required": ["task_id", "result"],
            "additionalProperties": False,
        },
    },
    {
        "name": "build_route_stats",
        "description": (
            "Read recent build route history, counts per route, pass rates, median durations, "
            "current opencode usability, and route balance suggestions before choosing a build route."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of recent records to return (default 10).",
                    "default": 10,
                },
            },
            "additionalProperties": False,
        },
    },
]

OPENCODE_TOOL_PERMISSIONS: dict[str, PermissionLevel] = {
    "opencode_status": PermissionLevel.L0,
    "build_route_stats": PermissionLevel.L0,
    "record_build_route": PermissionLevel.L1,
    "record_build_outcome": PermissionLevel.L1,
    "discard_delegation": PermissionLevel.L1,
    "delegate_coding": PermissionLevel.L2,
    "apply_delegation": PermissionLevel.L2,
}
