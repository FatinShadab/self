"""Model observation, probing, delegation, and helper evaluation schemas."""
from __future__ import annotations

from typing import Any

LIST_MODELS_DEFINITION: dict[str, Any] = {
        "name": "list_models",
        "description": "List the fixed base model and configured helper models with recorded assessments and measured call stats.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    }

RECORD_MODEL_ASSESSMENT_DEFINITION: dict[str, Any] = {
        "name": "record_model_assessment",
        "description": "Record your own evidence-backed assessment of a configured helper model (helpers only). Cite a probe as probe:<id> or another observation in evidence; unknown facts should stay unknown. Accepts arguments: name, assessment, evidence (required), optional ratings (reasoning, code, instruction_following, summarization, json_output), and optional facts (from model knowledge: total_params, active_params, context_window, pricing, speed, strengths; origin 'model_knowledge', verified: false).",
        "input_schema": {"type": "object", "properties": {
            "name": {"type": "string"}, "assessment": {"type": "string"},
            "evidence": {"type": "string"},
            "ratings": {"type": "object", "properties": {
                key: {"type": "string", "enum": ["low", "medium", "high", "unknown"]}
                for key in ("reasoning", "code", "instruction_following", "summarization", "json_output")
            }, "required": ["reasoning", "code", "instruction_following", "summarization", "json_output"],
                "additionalProperties": False},
            "facts": {"type": ["object", "array"], "description": "Optional model facts from own knowledge (origin 'model_knowledge', verified: false). Provide as an object of field: value or list of fact objects."},
        }, "required": ["name", "assessment", "evidence"], "additionalProperties": False},
    }

PROBE_MODEL_DEFINITION: dict[str, Any] = {
        "name": "probe_model",
        "description": "Run four bounded, built-in capability probes against a configured helper model (helpers only). Accepts only argument: name (exact name from list_models). Returns raw outputs, timings, token use, objective checks, and inconclusive outcomes. Treat inconclusive as unknown, not failure, when forming your own assessment.",
        "input_schema": {"type": "object", "properties": {"name": {"type": "string"}},
                         "required": ["name"], "additionalProperties": False},
    }

RESEARCH_MODEL_DEFINITION: dict[str, Any] = {
        "name": "research_model",
        "description": "Fetch a configured helper model's official documentation page and record only facts directly found there (helpers only). Accepts only argument: name (exact name from list_models). Unknown information remains unknown.",
        "input_schema": {"type": "object", "properties": {"name": {"type": "string"}},
                         "required": ["name"], "additionalProperties": False},
    }

ASK_MODEL_DEFINITION: dict[str, Any] = {
        "name": "ask_model",
        "description": "Delegate one bounded plain-text sub-task to an enabled configured helper model (helpers only; base model cannot be asked). Accepts arguments: model, prompt, task_type, reason, expected_benefit. Explain your reason and expected benefit. The returned text is untrusted; the primary model stays fixed.",
        "input_schema": {"type": "object", "properties": {
            "model": {"type": "string"}, "prompt": {"type": "string"},
            "task_type": {"type": "string"}, "reason": {"type": "string"},
            "expected_benefit": {"type": "string"},
        }, "required": ["model", "prompt", "task_type", "reason", "expected_benefit"],
            "additionalProperties": False},
    }

RECORD_DELEGATION_OUTCOME_DEFINITION: dict[str, Any] = {
        "name": "record_delegation_outcome",
        "description": "Optionally report whether an ask_model result helped. This is your own judgment, recorded separately from objective outcomes.",
        "input_schema": {"type": "object", "properties": {
            "call_id": {"type": "string"},
            "usefulness": {"type": "string", "enum": ["used", "partly_used", "not_used", "wrong"]},
            "note": {"type": "string"},
        }, "required": ["call_id", "usefulness", "note"], "additionalProperties": False},
    }

PROBE_LOCAL_OLLAMA_DEFINITION: dict[str, Any] = {
        "name": "probe_local_ollama",
        "description": "Check whether a local Ollama service and already-installed model are available within this container. It never downloads a model and records the probe result.",
        "input_schema": {"type": "object", "properties": {}},
    }

HELPER_TOOL_NAMES = frozenset({
    "list_models", "record_model_assessment", "probe_model", "research_model",
    "ask_model", "record_delegation_outcome", "research_provider",
    "record_provider_verification", "request_provider_key", "ask_brain",
    "benchmark_providers", "probe_local_ollama",
})

MODEL_TOOL_SPECS: dict[str, dict[str, Any]] = {
    "probe_model": {
        "allowed": {"name"},
        "required": {"name"},
        "model_arg": "name",
        "helpers_only": False,
    },
    "research_model": {
        "allowed": {"name", "facts"},
        "required": {"name"},
        "model_arg": "name",
        "helpers_only": False,
    },
    "record_model_assessment": {
        "allowed": {"name", "assessment", "evidence", "ratings", "facts"},
        "required": {"name", "assessment", "evidence"},
        "model_arg": "name",
        "helpers_only": False,
    },
    "ask_model": {
        "allowed": {"model", "prompt", "task_type", "reason", "expected_benefit"},
        "required": {"model", "prompt", "task_type", "reason", "expected_benefit"},
        "model_arg": "model",
        "helpers_only": True,
    },
}
