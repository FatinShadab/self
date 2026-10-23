"""System-level capability requests and core harness patch schemas."""
from __future__ import annotations

from typing import Any

REQUEST_CAPABILITY_DEFINITION: dict[str, Any] = {
        "name": "request_capability",
        "description": "Request a human-approved expansion beyond the container: credentials, host mounts, ports, email, money, third-party accounts, or external service access. This writes a request and cannot perform the expansion.",
        "input_schema": {"type": "object", "properties": {
            "kind": {"type": "string", "enum": ["credential", "host_mount", "port", "email", "money", "third_party_account", "external_service", "plugin"]},
            "summary": {"type": "string"}, "reason": {"type": "string"}, "provider": {"type": "string"},
            "env_names": {"type": "array", "items": {"type": "string"}}, "signup_url": {"type": "string"},
        }, "required": ["kind", "summary", "reason"]},
    }

PROPOSE_CORE_PATCH_DEFINITION: dict[str, Any] = {
        "name": "propose_core_patch",
        "description": "Save a diff and reasoning for a human-reviewed change to /opt/agent/core. This never applies the patch or changes the core itself.",
        "input_schema": {"type": "object", "properties": {
            "name": {"type": "string", "description": "Short name for the proposed change."},
            "diff": {"type": "string", "description": "Unified diff to be reviewed by the human."},
            "reasoning": {"type": "string", "description": "Evidence and reason the core change is needed."},
        }, "required": ["name", "diff", "reasoning"]},
    }
