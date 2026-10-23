"""Plugin specialization development and cost ledger tool schemas."""
from __future__ import annotations

from typing import Any

READ_COST_LEDGER_DEFINITION: dict[str, Any] = {
        "name": "read_cost_ledger",
        "description": "Read measured cost ledger baselines (median and p90 for tool tokens, LLM calls, wall time, cycles) and totals for active or historical plugin projects.",
        "input_schema": {"type": "object", "properties": {}},
    }

PROPOSE_PLUGIN_DEFINITION: dict[str, Any] = {
        "name": "propose_plugin",
        "description": "Propose developing a new specialization plugin. Requires evidence, alternatives considered, cost estimates citing ledger data, expected benefits, risk-level actions, maintenance burden, stop-loss thresholds, and rollback plan.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Lowercase snake_case name of the proposed plugin."},
                "need": {"type": "string", "description": "The specific capability gap or need justifying a full plugin."},
                "evidence": {"type": "string", "description": "Durable facts or observations demonstrating the need."},
                "alternatives_considered": {"type": "string", "description": "Lower capability ladder rungs considered (existing tools, helper model, tool) and why they were not enough."},
                "estimate": {
                    "type": "object",
                    "description": "Cost estimates with ranges for tokens, cycles, wall time, human review minutes, and derivation citing ledger data.",
                    "properties": {
                        "tokens": {"type": "object", "description": "Estimated token range {min, max}."},
                        "cycles": {"type": "object", "description": "Estimated cycle range {min, max}."},
                        "wall_time": {"type": "object", "description": "Estimated wall time range {min, max}."},
                        "human_review_minutes": {"type": "object", "description": "Estimated human review minutes range {min, max}."},
                        "derivation": {"type": "string", "description": "How estimates were derived citing cost ledger data."}
                    },
                    "required": ["tokens", "cycles", "wall_time", "human_review_minutes", "derivation"]
                },
                "expected_benefit": {"type": "string", "description": "Expected durable benefit to the agent's autonomous goals."},
                "actions_needed_with_risk_levels": {
                    "type": "array",
                    "description": "List of actions/sensors needed with their risk class and permission levels (L0-L3).",
                    "items": {"type": "object"}
                },
                "maintenance_burden": {"type": "string", "description": "Ongoing maintenance, state footprint, and unplug impact."},
                "stop_loss": {"type": "string", "description": "Stop-loss criteria and review triggers at 25%, 50%, and 100% of estimate."},
                "rollback": {"type": "string", "description": "Rollback procedure if plugin development is abandoned or rejected."}
            },
            "required": [
                "name", "need", "evidence", "alternatives_considered", "estimate",
                "expected_benefit", "actions_needed_with_risk_levels",
                "maintenance_burden", "stop_loss", "rollback"
            ]
        },
    }

SCAFFOLD_PLUGIN_DEFINITION: dict[str, Any] = {
        "name": "scaffold_plugin",
        "description": "Scaffold a new plugin draft in workspace/plugin_dev/<name>/ from the starter template. The loader never loads from plugin_dev.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Lowercase snake_case name of the plugin."},
                "kind": {"type": "string", "enum": ["body", "skill", "both"], "default": "skill", "description": "Plugin category."},
                "description": {"type": "string", "description": "Short description of the plugin's purpose."}
            },
            "required": ["name"]
        },
    }

VALIDATE_PLUGIN_DEFINITION: dict[str, Any] = {
        "name": "validate_plugin",
        "description": "Run static validation on a plugin draft in workspace/plugin_dev/<name>/: check manifest, namespacing, declared permissions, secret reads, undeclared network/subprocess use, and prompt injection strings.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name of the plugin draft to validate."}
            },
            "required": ["name"]
        },
    }

TEST_PLUGIN_DEFINITION: dict[str, Any] = {
        "name": "test_plugin",
        "description": "Execute unittests and simulation scenarios for a plugin draft in workspace/plugin_dev/<name>/ in an isolated environment without real resources.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name of the plugin draft to test."},
                "test_type": {"type": "string", "enum": ["unit", "sim"], "default": "unit", "description": "Type of tests to run."}
            },
            "required": ["name"]
        },
    }

REQUEST_PLUGIN_REVIEW_DEFINITION: dict[str, Any] = {
        "name": "request_plugin_review",
        "description": "Request a strict critic review of a validated and tested plugin draft in workspace/plugin_dev/<name>/, generating a diff and permission summary review packet for human inspection.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name of the plugin draft to review."}
            },
            "required": ["name"]
        },
    }
