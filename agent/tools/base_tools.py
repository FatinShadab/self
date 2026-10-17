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

from agent.infra.event_log import EventLogger
from agent.llm.llm import BudgetExceeded
from agent.infra.process_runner import run_process


DEFAULT_OUTPUT_CAP = 20_000


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
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "update_plan",
        "description": (
            "Update the persistent plan. Requires an action ('add', 'edit', 'drop', 'mark_done', 'reorder', 'unchanged') "
            "and a required 'reason' citing evidence. Use this to track goals, mark progress, add self-improvement goals "
            "(e.g. 'improve tool X', 'evaluate model Y', 'fix a failing tool'), or adjust next steps."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["add", "edit", "drop", "mark_done", "reorder", "unchanged"],
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
            "kind": {"type": "string", "enum": ["credential", "host_mount", "port", "email", "money", "third_party_account", "external_service"]},
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
    ) -> None:
        self.logger = logger
        self.workspace = Path(workspace)
        self.core_root = Path(core_root)
        self.agent_root = Path(agent_root)
        configured_cap = int(os.getenv("SELF_MAX_OUTPUT_CHARS", str(DEFAULT_OUTPUT_CAP)))
        self.output_cap = max(1_000, output_cap or configured_cap)
        self.registry: Any = None
        self.learning: Any = None
        self.brain_router: Any = None
        self.capabilities: Any = None
        self.identity: Any = None
        self.model_registry: Any = None
        self.model_prober: Any = None
        self.model_decisions: Any = None
        self.plan_store: Any = None
        self.current_cycle: int = 1

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
        stream_id = uuid.uuid4().hex[:12]
        safe_command = self.logger.redactor.text(cmd)
        self.logger.log("command_started", stream_id=stream_id, command=safe_command[:2_000], timeout=float(timeout))

        def on_output(chunk: str) -> None:
            self.logger.log("command_output", stream_id=stream_id,
                            output=self.logger.redactor.text(chunk)[:4_000])

        def on_complete(result: dict[str, Any]) -> None:
            self.logger.log("command_finished", stream_id=stream_id,
                            exit_code=result.get("exit_code"), timed_out=bool(result.get("timed_out")),
                            output_bytes=result.get("output_bytes", 0), truncated=bool(result.get("truncated")))

        return run_process(["/bin/bash", "-lc", cmd], cwd=self.workspace,
                           timeout=float(timeout), cap=self.output_cap,
                           on_output=on_output, on_complete=on_complete)

    def read_plan(self) -> dict[str, Any]:
        """Read the persistent plan state."""
        if self.plan_store is None:
            raise RuntimeError("persistent plan store is not configured")
        return self.plan_store.read_plan()

    def update_plan(self, **arguments: Any) -> dict[str, Any]:
        """Update the persistent plan with a required reason citing evidence."""
        if self.plan_store is None:
            raise RuntimeError("persistent plan store is not configured")
        cycle = arguments.pop("cycle", self.current_cycle)
        return self.plan_store.update_plan(cycle=cycle, **arguments)

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
        return self.brain_router.probe_local_ollama()

    def request_capability(self, kind: str, summary: str, reason: str, provider: str = "", env_names: list[str] | None = None, signup_url: str = "") -> dict[str, Any]:
        """Record a human-facing request for expanded capabilities."""
        return self.capabilities.request(kind, summary, reason, provider, env_names, signup_url)

    def propose_core_patch(self, name: str, diff: str, reasoning: str) -> dict[str, Any]:
        """Reject direct harness changes and record a proposed patch instead."""
        return self.identity.propose_core_patch(name, diff, reasoning)

    def _is_core_path(self, path: Path) -> bool:
        """Treat symlink and traversal variants of image-owned harness paths as protected."""
        try:
            candidate = path.resolve(strict=False)
            return any(candidate.is_relative_to(root.resolve(strict=False)) for root in (self.core_root, self.agent_root))
        except OSError:
            return False

    def read_file(self, path: str, max_chars: int = DEFAULT_OUTPUT_CAP) -> dict[str, Any]:
        """Read a file that passes the runner's path checks."""
        limit = max(1, min(int(max_chars), self.output_cap))
        file_path = Path(path)
        with file_path.open("r", encoding="utf-8", errors="replace") as handle:
            content = handle.read(limit + 1)
        return {
            "path": str(file_path),
            "content": content[:limit],
            "truncated": len(content) > limit,
        }

    def write_file(self, path: str, content: str, append: bool = False) -> dict[str, Any]:
        """Write a workspace file after enforcing path and size limits."""
        file_path = Path(path)
        if self._is_core_path(file_path):
            raise PermissionError(
                "The image-owned /opt/agent harness (including /opt/agent/core) is protected. Save a diff with propose_core_patch so the human can review and apply it from the host."
            )
        if self.identity is not None and self.identity.is_managed_path(file_path):
            raise PermissionError(
                "Identity-managed state cannot be overwritten through write_file. Preserve the append-only identity trail; the human may edit identity.json from the host, while the harness records evidence-backed reflection changes."
            )
        file_path.parent.mkdir(parents=True, exist_ok=True)
        safe_content = self.logger.redactor.known(content)
        with file_path.open("a" if append else "w", encoding="utf-8") as handle:
            written = handle.write(safe_content)
        try:
            relative = file_path.resolve().relative_to((self.workspace / "tools").resolve())
        except ValueError:
            relative = None
        if relative is not None:
            self.logger.log("tool_created" if not append else "tool_updated", path=str(file_path), bytes=written)
        return {"path": str(file_path), "chars_written": written, "append": bool(append)}

    def list_dir(self, path: str, max_entries: int = 500) -> dict[str, Any]:
        """List directory entries up to a bounded count without following links."""
        limit = max(1, min(int(max_entries), 5_000))
        entries: list[dict[str, Any]] = []
        truncated = False
        with os.scandir(path) as iterator:
            for index, entry in enumerate(iterator):
                if index >= limit:
                    truncated = True
                    break
                item: dict[str, Any] = {
                    "name": entry.name,
                    "type": "dir" if entry.is_dir(follow_symlinks=False) else "file",
                }
                if entry.is_symlink():
                    item["type"] = "symlink"
                elif item["type"] == "file":
                    item["size"] = entry.stat(follow_symlinks=False).st_size
                entries.append(item)
        entries.sort(key=lambda item: (item["type"], item["name"].lower()))
        return {"path": str(path), "entries": entries, "truncated": truncated}

    def _log_network(self, url: str, method: str = "GET", **extra: Any) -> None:
        parsed = urllib.parse.urlsplit(url)
        self.logger.log(
            "network_request",
            method=method,
            host=parsed.hostname or "",
            path=parsed.path or "/",
            **extra,
        )

    def http_get(self, url: str, timeout: float = 20, max_chars: int = DEFAULT_OUTPUT_CAP) -> dict[str, Any]:
        """Fetch a URL and record observable network access."""
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("http_get requires an http:// or https:// URL with a host")
        limit = max(1, min(int(max_chars), self.output_cap))
        self._log_network(url)
        opener = urllib.request.build_opener(_LoggingRedirectHandler(self._log_network))
        request = urllib.request.Request(url, headers={"User-Agent": "SELF/0.2"}, method="GET")
        try:
            with opener.open(request, timeout=max(0.1, float(timeout))) as response:
                body = response.read(limit + 1)
                content_type = response.headers.get_content_type()
                charset = response.headers.get_content_charset() or "utf-8"
                status = response.status
                final_url = response.geturl()
        except urllib.error.HTTPError as exc:
            body = exc.read(limit + 1)
            content_type = exc.headers.get_content_type() if exc.headers else "text/plain"
            charset = exc.headers.get_content_charset() if exc.headers else None
            charset = charset or "utf-8"
            status = exc.code
            final_url = exc.geturl()
        final = urllib.parse.urlsplit(final_url)
        return {
            "status": status,
            "host": final.hostname or "",
            "path": final.path or "/",
            "content_type": content_type,
            "body": body[:limit].decode(charset, errors="replace"),
            "truncated": len(body) > limit,
        }
