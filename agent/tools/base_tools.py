"""SELF base tools module."""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from agent.body.base import Body
from agent.infra.event_log import EventLogger
from agent.infra.permission_broker import ActionRequest, PermissionBroker, PermissionLevel
from agent.llm.llm import BudgetExceeded
from agent.infra.process_runner import run_process


DEFAULT_OUTPUT_CAP = 20_000

TOOL_PERMISSION_LEVELS: dict[str, PermissionLevel] = {
    # L0: observe
    "read_file": PermissionLevel.L0,
    "list_dir": PermissionLevel.L0,
    "http_get": PermissionLevel.L0,
    "probe_local_ollama": PermissionLevel.L0,
    "read_plan": PermissionLevel.L0,
    "list_models": PermissionLevel.L0,
    "probe_model": PermissionLevel.L0,
    "research_model": PermissionLevel.L0,
    "ask_model": PermissionLevel.L0,
    "research_provider": PermissionLevel.L0,
    "ask_brain": PermissionLevel.L0,
    "benchmark_providers": PermissionLevel.L0,
    # L1: reversible change
    "update_plan": PermissionLevel.L1,
    "update_environment_map": PermissionLevel.L1,
    "record_model_assessment": PermissionLevel.L1,
    "record_delegation_outcome": PermissionLevel.L1,
    "record_provider_verification": PermissionLevel.L1,
    "request_provider_key": PermissionLevel.L1,
    "request_capability": PermissionLevel.L1,
    "propose_core_patch": PermissionLevel.L1,
    # L2: destructive / irreversible
    "run_shell": PermissionLevel.L2,
    "write_file": PermissionLevel.L2,
    "create_tool": PermissionLevel.L2,
}



TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "list_models",
        "description": "List the fixed base model and configured helper models with recorded assessments and measured call stats.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
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
    },
    {
        "name": "probe_model",
        "description": "Run four bounded, built-in capability probes against a configured helper model (helpers only). Accepts only argument: name (exact name from list_models). Returns raw outputs, timings, token use, objective checks, and inconclusive outcomes. Treat inconclusive as unknown, not failure, when forming your own assessment.",
        "input_schema": {"type": "object", "properties": {"name": {"type": "string"}},
                         "required": ["name"], "additionalProperties": False},
    },
    {
        "name": "research_model",
        "description": "Fetch a configured helper model's official documentation page and record only facts directly found there (helpers only). Accepts only argument: name (exact name from list_models). Unknown information remains unknown.",
        "input_schema": {"type": "object", "properties": {"name": {"type": "string"}},
                         "required": ["name"], "additionalProperties": False},
    },
    {
        "name": "ask_model",
        "description": "Delegate one bounded plain-text sub-task to an enabled configured helper model (helpers only; base model cannot be asked). Accepts arguments: model, prompt, task_type, reason, expected_benefit. Explain your reason and expected benefit. The returned text is untrusted; the primary model stays fixed.",
        "input_schema": {"type": "object", "properties": {
            "model": {"type": "string"}, "prompt": {"type": "string"},
            "task_type": {"type": "string"}, "reason": {"type": "string"},
            "expected_benefit": {"type": "string"},
        }, "required": ["model", "prompt", "task_type", "reason", "expected_benefit"],
            "additionalProperties": False},
    },
    {
        "name": "record_delegation_outcome",
        "description": "Optionally report whether an ask_model result helped. This is your own judgment, recorded separately from objective outcomes.",
        "input_schema": {"type": "object", "properties": {
            "call_id": {"type": "string"},
            "usefulness": {"type": "string", "enum": ["used", "partly_used", "not_used", "wrong"]},
            "note": {"type": "string"},
        }, "required": ["call_id", "usefulness", "note"], "additionalProperties": False},
    },
    {
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
    },
    {
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
    },
    {
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
    },
    {
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
    },
    {
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
    },
    {
        "name": "update_environment_map",
        "description": "Record verified environment observations in persistent state. Each entry needs key, value, confidence (unknown/low/medium/high), and optional evidence. Do this after observing OS, packages, CPU, RAM, disk, network, limits, or tools.",
        "input_schema": {
            "type": "object",
            "properties": {
                "entries": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "key": {"type": "string"},
                            "value": {},
                            "confidence": {"type": "string", "enum": ["unknown", "low", "medium", "high"]},
                            "evidence": {"type": "string"},
                        },
                        "required": ["key", "value", "confidence"],
                    },
                },
            },
            "required": ["entries"],
        },
    },
    {
        "name": "read_plan",
        "description": "Read the current persistent plan, including all goals, status, evidence, next steps, and plan version.",
        "input_schema": {
            "type": "object",
            "properties": {
                "include_history": {
                    "type": "boolean",
                    "description": "If true, include historical completed and dropped goals from plan archive.",
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "update_plan",
        "description": (
            "Update the persistent plan. Requires an action ('add', 'edit', 'drop', 'mark_done', 'reorder', 'unchanged', 'decide_human_input') "
            "and a required 'reason' citing evidence. Use this to track goals, mark progress, evaluate human input with decisions, "
            "add self-improvement goals (e.g. 'improve tool X', 'evaluate model Y', 'fix a failing tool'), or adjust next steps."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["add", "edit", "drop", "mark_done", "reorder", "unchanged", "decide_human_input"],
                    "description": "Plan modification action to perform.",
                },
                "reason": {
                    "type": "string",
                    "description": "Required reason citing evidence (observations, tool results, errors) for this change.",
                },
                "goal": {"type": "string", "description": "Goal or step description (for add/edit)."},
                "id": {"type": "string", "description": "Target goal id (e.g. 'goal-1') to edit, drop, or mark done."},
                "evidence": {"type": "string", "description": "Evidence reference or observation supporting this update."},
                "next_steps": {"type": "string", "description": "Specific actionable next steps for this goal."},
                "priority": {"type": "integer", "description": "Priority (1=high, 2=medium, 3=low).", "default": 2},
                "status": {
                    "type": "string",
                    "enum": ["todo", "in_progress", "done", "dropped", "blocked", "stale"],
                    "description": "Status for the goal (for edit).",
                },
                "order": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of goal IDs in new order (for reorder).",
                },
                "input": {
                    "type": "string",
                    "description": "Human input text being evaluated (for decide_human_input).",
                },
                "decision": {
                    "type": "string",
                    "enum": ["accepted", "modified", "declined", "deferred", "noted"],
                    "description": "Decision on human input (for decide_human_input).",
                },
                "source": {
                    "type": "string",
                    "enum": ["agent", "human"],
                    "description": "Origin of the plan goal (default 'agent', or 'human' when adopting human input).",
                },
            },
            "required": ["action", "reason"],
        },
    },
    {
        "name": "research_provider",
        "description": "Fetch a configured provider's official documentation, log only host/path, and store a bounded research excerpt for human/agent review. Never signs up or creates an account.",
        "input_schema": {"type": "object", "properties": {"provider": {"type": "string"}}, "required": ["provider"]},
    },
    {
        "name": "record_provider_verification",
        "description": "After reading official provider documentation, record models, strengths, source URL, and explicit free-tier RPM/tokens-per-day limits (null only if unpublished).",
        "input_schema": {"type": "object", "properties": {
            "provider": {"type": "string"}, "free_tier": {"type": "object"}, "models": {"type": "array", "items": {"type": "string"}},
            "strengths": {"type": "array", "items": {"type": "string"}}, "source_url": {"type": "string"},
        }, "required": ["provider", "free_tier", "models", "strengths", "source_url"]},
    },
    {
        "name": "request_provider_key",
        "description": "Write a human-only API-key request for a provider. This never creates an account and does not halt unrelated agent work.",
        "input_schema": {"type": "object", "properties": {"provider": {"type": "string"}}, "required": ["provider"]},
    },
    {
        "name": "ask_brain",
        "description": "Use a safely routed supplementary provider for plain-text reasoning, simple work, or summarization. It uses only configured keys, respects recorded limits, backs off on 429, and falls back safely.",
        "input_schema": {"type": "object", "properties": {
            "prompt": {"type": "string"}, "task_type": {"type": "string", "enum": ["reasoning", "simple", "summarization"], "default": "simple"},
            "model": {"type": "string"}, "preferred_provider": {"type": "string"}, "max_tokens": {"type": "integer", "default": 512},
        }, "required": ["prompt"]},
    },
    {
        "name": "benchmark_providers",
        "description": "Run the small built-in local eval set only against configured providers that are safely within verified free limits, saving quality/latency data to state/provider_scores.json.",
        "input_schema": {"type": "object", "properties": {"providers": {"type": "array", "items": {"type": "string"}}}},
    },
    {
        "name": "probe_local_ollama",
        "description": "Check whether a local Ollama service and already-installed model are available within this container. It never downloads a model and records the probe result.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "request_capability",
        "description": "Request a human-approved expansion beyond the container: credentials, host mounts, ports, email, money, third-party accounts, or external service access. This writes a request and cannot perform the expansion.",
        "input_schema": {"type": "object", "properties": {
            "kind": {"type": "string", "enum": ["credential", "host_mount", "port", "email", "money", "third_party_account", "external_service", "plugin"]},
            "summary": {"type": "string"}, "reason": {"type": "string"}, "provider": {"type": "string"},
            "env_names": {"type": "array", "items": {"type": "string"}}, "signup_url": {"type": "string"},
        }, "required": ["kind", "summary", "reason"]},
    },
    {
        "name": "propose_core_patch",
        "description": "Save a diff and reasoning for a human-reviewed change to /opt/agent/core. This never applies the patch or changes the core itself.",
        "input_schema": {"type": "object", "properties": {
            "name": {"type": "string", "description": "Short name for the proposed change."},
            "diff": {"type": "string", "description": "Unified diff to be reviewed by the human."},
            "reasoning": {"type": "string", "description": "Evidence and reason the core change is needed."},
        }, "required": ["name", "diff", "reasoning"]},
    },
    {
        "name": "read_cost_ledger",
        "description": "Read measured cost ledger baselines (median and p90 for tool tokens, LLM calls, wall time, cycles) and totals for active or historical plugin projects.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
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
    },
    {
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
    },
    {
        "name": "validate_plugin",
        "description": "Run static validation on a plugin draft in workspace/plugin_dev/<name>/: check manifest, namespacing, declared permissions, secret reads, undeclared network/subprocess use, and prompt injection strings.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name of the plugin draft to validate."}
            },
            "required": ["name"]
        },
    },
    {
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
    },
    {
        "name": "request_plugin_review",
        "description": "Request a strict critic review of a validated and tested plugin draft in workspace/plugin_dev/<name>/, generating a diff and permission summary review packet for human inspection.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name of the plugin draft to review."}
            },
            "required": ["name"]
        },
    },
]

# Fixed experiment arms remove model-discovery and supplementary-provider paths
# from the actor's tool list. The execution check below also rejects direct calls.
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


class _LoggingRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, callback: Any) -> None:
        super().__init__()
        self._callback = callback

    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
        self._callback(newurl, "GET", redirect_status=code)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class ToolRunner:
    """Execute built-in tools subject to workspace and harness boundaries."""

    def __init__(
        self,
        logger: EventLogger,
        workspace: str | Path = "/home/entity",
        output_cap: int | None = None,
        core_root: str | Path = "/opt/agent/core",
        agent_root: str | Path = "/opt/agent",
        body: Body | None = None,
        broker: PermissionBroker | None = None,
        plugin_dev: Any = None,
    ) -> None:
        self.logger = logger
        self.workspace = Path(workspace)
        self.core_root = Path(core_root)
        self.agent_root = Path(agent_root)
        self.broker = broker
        self.plugin_dev = plugin_dev
        configured_cap = int(os.getenv("SELF_MAX_OUTPUT_CHARS", str(DEFAULT_OUTPUT_CAP)))
        self.output_cap = max(1_000, output_cap or configured_cap)
        if body is None:
            from agent.body.container import ContainerBody
            body = ContainerBody(
                workspace=self.workspace,
                logger=self.logger,
                core_root=self.core_root,
                agent_root=self.agent_root,
                output_cap=self.output_cap,
            )
        self.body = body
        self.registry: Any = None
        self.learning: Any = None
        self.brain_router: Any = None
        self.capabilities: Any = None
        self._identity: Any = None
        self.model_registry: Any = None
        self.model_prober: Any = None
        self.model_decisions: Any = None
        self.plan_store: Any = None
        self.plugins: Any = None
        self.current_cycle: int = 1
        from agent.infra.cost_ledger import CostLedger
        self.cost_ledger = CostLedger(self.workspace)
        self.review_call: Any = None

    @property
    def identity(self) -> Any:
        return self._identity

    @identity.setter
    def identity(self, value: Any) -> None:
        self._identity = value
        if hasattr(self.body, "identity"):
            self.body.identity = value

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute a named tool with its supplied arguments."""
        if os.getenv("SELF_HELPER_MODELS", "on").strip().lower() != "on" and name in HELPER_TOOL_NAMES:
            return {"ok": False, "error": f"{name} is disabled in this experiment arm"}
        logged_arguments = dict(arguments)
        if name == "http_get" and "url" in logged_arguments:
            parsed = urllib.parse.urlsplit(str(logged_arguments["url"]))
            logged_arguments["url"] = {
                "host": parsed.hostname or "",
                "path": parsed.path or "/",
            }
        for key in ("content", "code", "test_code", "prompt"):
            if key in logged_arguments:
                content = self.logger.redactor.known(str(logged_arguments.pop(key)))
                logged_arguments[key + "_chars"] = len(content)
                logged_arguments[key + "_sha256"] = hashlib.sha256(content.encode("utf-8")).hexdigest()
        self.logger.log("tool_call", tool=name, arguments=logged_arguments)
        started = time.monotonic()
        result: dict[str, Any] | None = None
        action_request: ActionRequest | None = None

        if self.broker is not None:
            source = "core"
            if name in {"run_shell", "read_file", "write_file", "list_dir", "http_get", "probe_local_ollama"}:
                source = "body"
            elif self.plugins is not None and (self.plugins.is_plugin_tool(name) or self.plugins.is_vanished_or_disabled_tool(name)):
                source = f"plugins.{self.plugins.get_plugin_for_tool(name)}"

            level = TOOL_PERMISSION_LEVELS.get(name, PermissionLevel.L2)
            reversible = name in {
                "update_plan", "update_environment_map", "record_model_assessment",
                "record_delegation_outcome", "record_provider_verification",
                "request_provider_key", "request_capability", "propose_core_patch",
            }
            if source.startswith("plugins.") and self.plugins is not None:
                p_name = self.plugins.get_plugin_for_tool(name)
                plugin_obj = self.plugins.active_plugins.get(p_name) or self.plugins.discovered.get(p_name)
                if plugin_obj is not None:
                    for act in plugin_obj.manifest.actions:
                        if act.name == name or f"{p_name}.{act.name}" == name:
                            level = PermissionLevel.from_value(act.required_permission_level)
                            reversible = act.reversible
                            break
                    for sens in plugin_obj.manifest.sensors:
                        if sens.name == name or f"{p_name}.{sens.name}" == name:
                            level = PermissionLevel.from_value(sens.required_permission_level)
                            reversible = sens.reversible
                            break

            dry_run = bool(arguments.get("dry_run", False))
            action_request = ActionRequest(
                action=name,
                source=source,
                level=level,
                params=arguments,
                dry_run=dry_run,
                reversible=reversible,
            )
            verdict = self.broker.authorize(action_request)
            if not verdict.allowed:
                result = {"ok": False, "error": verdict.reason, "permission_denied": True}
            elif verdict.dry_run:
                result = {"ok": True, "dry_run": True, "message": f"Action '{name}' authorized in dry-run mode."}

        if name in MODEL_TOOL_SPECS:
            spec = MODEL_TOOL_SPECS[name]
            allowed = spec["allowed"]
            required = spec["required"]
            unexpected = sorted(set(arguments) - allowed)
            if unexpected:
                result = {
                    "ok": False,
                    "error": f"Unexpected argument(s) {unexpected} for {name}. Valid arguments are: {sorted(allowed)}."
                }
            else:
                missing = sorted(required - set(arguments))
                if missing:
                    result = {
                        "ok": False,
                        "error": f"Missing required argument(s) {missing} for {name}. Valid arguments are: {sorted(allowed)}."
                    }
                elif self.model_registry is not None:
                    model_val = arguments.get(spec["model_arg"])
                    valid, err_msg = self.model_registry.validate_model_name(
                        model_val, helpers_only=spec["helpers_only"])
                    if not valid:
                        result = {"ok": False, "error": err_msg}

        if result is None:
            try:
                if name == "create_tool" and self.registry is not None:
                    result = self.registry.create_tool(**arguments)
                elif name in {"list_models", "record_model_assessment"}:
                    if self.model_registry is None:
                        raise RuntimeError("model registry is not configured")
                    result = getattr(self.model_registry, name)(**arguments)
                elif name in {"probe_model", "research_model"}:
                    if self.model_prober is None:
                        raise RuntimeError("model probes are not configured")
                    result = getattr(self.model_prober, name)(**arguments)
                elif name == "ask_model":
                    if self.model_decisions is None:
                        raise RuntimeError("model decisions are not configured")
                    result = self.model_decisions.ask_model(**arguments)
                elif name == "record_delegation_outcome":
                    if self.model_decisions is None:
                        raise RuntimeError("model decisions are not configured")
                    result = self.model_decisions.record_delegation_outcome(**arguments)
                elif name in {"research_provider", "record_provider_verification", "request_provider_key", "ask_brain", "benchmark_providers", "probe_local_ollama"}:
                    if self.brain_router is None:
                        raise RuntimeError("brain router is not configured")
                    result = getattr(self, name)(**arguments)
                elif name == "request_capability":
                    if self.capabilities is None:
                        raise RuntimeError("capability request system is not configured")
                    result = self.request_capability(**arguments)
                elif name == "propose_core_patch":
                    if self.identity is None:
                        raise RuntimeError("identity and core-patch system is not configured")
                    result = self.propose_core_patch(**arguments)
                elif name in {definition["name"] for definition in TOOL_DEFINITIONS}:
                    result = getattr(self, name)(**arguments)
                elif self.plugins is not None and self.plugins.is_plugin_tool(name):
                    result = self.plugins.execute_plugin_tool(name, arguments)
                elif self.plugins is not None and self.plugins.is_vanished_or_disabled_tool(name):
                    result = self.plugins.execute_plugin_tool(name, arguments)
                elif "." in name:
                    plugin_name = name.split(".", 1)[0]
                    result = {"ok": False, "error": f"tool no longer available: plugin {plugin_name} disabled"}
                elif self.registry is not None:
                    result = self.registry.execute(name, arguments)
                else:
                    raise ValueError(f"Unknown tool: {name}")
                result.setdefault("ok", True)
            except BudgetExceeded:
                raise
            except Exception as exc:  # Tool errors are observations for the next model turn.
                result = {"ok": False, "error": self.logger.redactor.text(exc)}
        safe_result = self.logger.redactor.value(result)
        if self.broker is not None and action_request is not None and not action_request.dry_run:
            self.broker.record_execution(
                action_request,
                success=bool(safe_result.get("ok", False)),
                reversible=action_request.reversible,
                error=safe_result.get("error"),
            )
        serialized = json.dumps(safe_result, ensure_ascii=False)
        self.logger.log(
            "tool_result",
            tool=name,
            ok=bool(safe_result.get("ok")),
            duration_ms=round((time.monotonic() - started) * 1000, 2),
            result_chars=len(serialized),
            result_sha256=hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
            preview=serialized[:2_000],
        )
        return safe_result

    def run_shell(self, cmd: str, timeout: float = 30) -> dict[str, Any]:
        """Run a bounded shell command inside the container."""
        return self.body.run_shell(cmd=cmd, timeout=timeout)

    def read_plan(self, include_history: bool = False, **arguments: Any) -> dict[str, Any]:
        """Read the persistent plan state."""
        if self.plan_store is None:
            raise RuntimeError("persistent plan store is not configured")
        history = bool(include_history or arguments.get("history", False))
        return self.plan_store.read_plan(include_history=history)

    def update_plan(self, **arguments: Any) -> dict[str, Any]:
        """Update the persistent plan with a required reason citing evidence."""
        if self.plan_store is None:
            raise RuntimeError("persistent plan store is not configured")
        cycle = arguments.pop("cycle", self.current_cycle)
        res = self.plan_store.update_plan(cycle=cycle, **arguments)
        if res.get("ok"):
            act = str(arguments.get("action", "")).lower()
            dec = str(arguments.get("decision", "")).lower()
            proj = str(arguments.get("project") or arguments.get("id") or arguments.get("goal") or "").strip()
            reason_text = str(arguments.get("reason", ""))
            if act in {"decide_plugin_review", "plugin_project_review"} or (dec in {"continue", "reduce_scope", "abandon"} and proj):
                ledger_summary = self.cost_ledger.get_summary()
                pdata = ledger_summary.get("plugin_projects", {}).get(proj, {})
                thresh = int(arguments.get("threshold", 25))
                if self.plugin_dev is not None and hasattr(self.plugin_dev, "record_review_decision"):
                    self.plugin_dev.record_review_decision(proj, thresh)
                self.logger.log(
                    "plugin_project_review",
                    project=proj,
                    threshold=thresh,
                    decision=dec or "continue",
                    reason=reason_text,
                    tokens_spent=pdata.get("tokens", 0),
                    cycles_spent=pdata.get("cycles", 0),
                    token_estimate=pdata.get("token_estimate", 0),
                    cycle_estimate=pdata.get("cycle_estimate", 0),
                )
        return res

    def update_environment_map(self, entries: list[dict[str, Any]]) -> dict[str, Any]:
        """Record observed environment facts through the learning store."""
        if self.learning is None:
            raise RuntimeError("persistent learning store is not configured")
        return self.learning.update_map(entries, source="agent tool observation")

    def research_provider(self, provider: str) -> dict[str, Any]:
        """Fetch official provider information through the router."""
        return self.brain_router.research_provider(provider)

    def record_provider_verification(self, provider: str, free_tier: dict[str, Any], models: list[str], strengths: list[str], source_url: str) -> dict[str, Any]:
        """Store provider limits verified against its official source."""
        return self.brain_router.record_provider_verification(provider, free_tier, models, strengths, source_url)

    def request_provider_key(self, provider: str) -> dict[str, Any]:
        """Ask the human to configure a missing provider credential."""
        return self.brain_router.request_key(provider)

    def ask_brain(self, prompt: str, task_type: str = "simple", model: str | None = None, preferred_provider: str | None = None, max_tokens: int = 512) -> dict[str, Any]:
        """Send a bounded plain-text request through a supplemental provider."""
        return self.brain_router.chat([{"role": "user", "content": prompt}], model, max(32, min(int(max_tokens), 4_096)), task_type, preferred_provider)

    def benchmark_providers(self, providers: list[str] | None = None) -> dict[str, Any]:
        """Run the small built-in provider comparison and persist scores."""
        from agent.tools.benchmark import run_benchmark
        return run_benchmark(self.workspace, self.logger, self.brain_router, providers)

    def probe_local_ollama(self) -> dict[str, Any]:
        """Check local Ollama availability without starting or pulling a model."""
        return self.body.probe_local_ollama()

    def request_capability(self, kind: str, summary: str, reason: str, provider: str = "", env_names: list[str] | None = None, signup_url: str = "") -> dict[str, Any]:
        """Record a human-facing request for expanded capabilities."""
        return self.capabilities.request(kind, summary, reason, provider, env_names, signup_url)

    def propose_core_patch(self, name: str, diff: str, reasoning: str) -> dict[str, Any]:
        """Reject direct harness changes and record a proposed patch instead."""
        return self.identity.propose_core_patch(name, diff, reasoning)

    def _is_core_path(self, path: Path) -> bool:
        """Treat symlink and traversal variants of image-owned harness paths as protected."""
        checker = getattr(self.body, "_is_core_path", None)
        if callable(checker):
            return bool(checker(path))
        try:
            candidate = path.resolve(strict=False)
            if any(candidate.is_relative_to(root.resolve(strict=False)) for root in (self.core_root, self.agent_root)):
                return True
            for cfg in (Path("/config"), self.workspace / "config", self.workspace.parent / "config"):
                try:
                    if candidate.is_relative_to(cfg.resolve(strict=False)):
                        return True
                except (OSError, ValueError):
                    pass
            return False
        except OSError:
            return False

    def read_file(self, path: str, max_chars: int = DEFAULT_OUTPUT_CAP) -> dict[str, Any]:
        """Read a file that passes the runner's path checks."""
        return self.body.read_file(path=path, max_chars=max_chars)

    def write_file(self, path: str, content: str, append: bool = False) -> dict[str, Any]:
        """Write a workspace file after enforcing path and size limits."""
        if self._identity is not None and getattr(self.body, "identity", None) is None:
            self.body.identity = self._identity
        return self.body.write_file(path=path, content=content, append=append)

    def list_dir(self, path: str, max_entries: int = 500) -> dict[str, Any]:
        """List directory entries up to a bounded count without following links."""
        return self.body.list_dir(path=path, max_entries=max_entries)

    def http_get(self, url: str, timeout: float = 20, max_chars: int = DEFAULT_OUTPUT_CAP) -> dict[str, Any]:
        """Fetch a URL and record observable network access."""
        return self.body.http_get(url=url, timeout=timeout, max_chars=max_chars)

    def read_cost_ledger(self) -> dict[str, Any]:
        """Read measured cost ledger baselines and plugin project totals."""
        return self.cost_ledger.get_summary()

    def propose_plugin(
        self,
        name: str,
        need: str,
        evidence: str,
        alternatives_considered: Any,
        estimate: Any,
        expected_benefit: str,
        actions_needed_with_risk_levels: Any,
        maintenance_burden: str,
        stop_loss: Any,
        rollback: str,
    ) -> dict[str, Any]:
        """Propose developing a specialization plugin."""
        if self.plugin_dev is None:
            return {"ok": False, "error": "Plugin development is not configured on ToolRunner."}
        return self.plugin_dev.propose_plugin(
            name=name,
            need=need,
            evidence=evidence,
            alternatives_considered=alternatives_considered,
            estimate=estimate,
            expected_benefit=expected_benefit,
            actions_needed_with_risk_levels=actions_needed_with_risk_levels,
            maintenance_burden=maintenance_burden,
            stop_loss=stop_loss,
            rollback=rollback,
            plan_store=self.plan_store,
            cycle=self.current_cycle,
        )

    def scaffold_plugin(self, name: str, kind: str = "skill", description: str = "") -> dict[str, Any]:
        """Scaffold a plugin draft in workspace/plugin_dev/<name>/."""
        if self.plugin_dev is None:
            return {"ok": False, "error": "Plugin development is not configured on ToolRunner."}
        return self.plugin_dev.scaffold_plugin(name=name, kind=kind, description=description)

    def validate_plugin(self, name: str) -> dict[str, Any]:
        """Run static validation on a plugin draft in workspace/plugin_dev/<name>/."""
        if self.plugin_dev is None:
            return {"ok": False, "error": "Plugin development is not configured on ToolRunner."}
        return self.plugin_dev.validate_plugin(name=name)

    def test_plugin(self, name: str, test_type: str = "unit") -> dict[str, Any]:
        """Execute unittests for a plugin draft in workspace/plugin_dev/<name>/."""
        if self.plugin_dev is None:
            return {"ok": False, "error": "Plugin development is not configured on ToolRunner."}
        return self.plugin_dev.test_plugin(name=name, test_type=test_type)

    def request_plugin_review(self, name: str) -> dict[str, Any]:
        """Request strict critic review of a validated plugin draft."""
        if self.plugin_dev is None:
            return {"ok": False, "error": "Plugin development is not configured on ToolRunner."}
        return self.plugin_dev.request_plugin_review(name=name)

