"""ContainerBody implementation for Docker Linux container embodiment."""
from __future__ import annotations

import os
import platform
from pathlib import Path
from typing import Any

from agent.body.base import Body, BodyDescription, Capability
from agent.body.linux import (
    ContainerMetrics,
    _format_bytes,
    _read_cgroup_value,
    _read_int_file,
    detect_orientation_changes,
    get_container_capabilities,
    get_container_uptime,
    http_get_request,
    is_core_path as _is_core_path_impl,
    list_container_dir,
    probe_local_ollama_endpoint,
    read_container_file,
    run_container_shell,
    write_container_file,
)
from agent.body.linux.network_ops import log_network
from agent.infra.event_log import EventLogger
from agent.infra.process_runner import run_process
from agent.prompts.container_body import (
    CONTAINER_BODY_RULES,
    CONTAINER_CONVERSATION_CONTEXT,
    CONTAINER_DEFAULT_INTERESTS,
    CONTAINER_EMBODIMENT_CLAUSE,
    CONTAINER_EMBODIMENT_TEXT,
    CONTAINER_IDENTITY_CONTEXT,
    CONTAINER_IDENTITY_HARNESS_CONTEXT,
    CONTAINER_IDENTITY_OPERATING_ENVIRONMENT,
    CONTAINER_IDENTITY_ORIENTATION_CONTEXT,
    CONTAINER_INITIAL_ORIENTATION_TASK,
    CONTAINER_NOTES_PREAMBLE,
    CONTAINER_POST_CAPABILITY_RULES,
    CONTAINER_PRE_CAPABILITY_RULES,
)

__all__ = [
    "ContainerBody",
    "ContainerMetrics",
    "_format_bytes",
    "_read_cgroup_value",
    "_read_int_file",
    "run_process",
]


class ContainerBody(Body):
    """The default Linux container embodiment for SELF."""

    DEFAULT_OUTPUT_CAP = 20_000

    def __init__(
        self,
        workspace: Path | str = "/home/entity",
        logger: EventLogger | None = None,
        core_root: Path | str = "/opt/agent/core",
        agent_root: Path | str = "/opt/agent",
        output_cap: int = 20_000,
        identity: Any = None,
        broker: Any | None = None,
    ) -> None:
        self.workspace = Path(workspace)
        self.logger = logger or EventLogger(self.workspace / "logs" / "actions.jsonl")
        self.core_root = Path(core_root)
        self.agent_root = Path(agent_root)
        self.output_cap = max(100, int(output_cap))
        self.identity = identity
        self.broker = broker
        self.metrics = ContainerMetrics()

    def describe(self) -> BodyDescription:
        """Return container-specific narrative, default interests, and initial orientation task."""
        return BodyDescription(
            embodiment_text=CONTAINER_EMBODIMENT_TEXT,
            embodiment_clause=CONTAINER_EMBODIMENT_CLAUSE,
            default_interests=list(CONTAINER_DEFAULT_INTERESTS),
            initial_orientation_task=CONTAINER_INITIAL_ORIENTATION_TASK,
            conversation_context=CONTAINER_CONVERSATION_CONTEXT,
            identity_context=CONTAINER_IDENTITY_CONTEXT,
            identity_harness_context=CONTAINER_IDENTITY_HARNESS_CONTEXT,
            identity_orientation_context=CONTAINER_IDENTITY_ORIENTATION_CONTEXT,
            identity_operating_environment=CONTAINER_IDENTITY_OPERATING_ENVIRONMENT,
            notes_preamble=CONTAINER_NOTES_PREAMBLE,
            body_rules=list(CONTAINER_BODY_RULES),
            pre_capability_rules=list(CONTAINER_PRE_CAPABILITY_RULES),
            post_capability_rules=list(CONTAINER_POST_CAPABILITY_RULES),
        )

    def capabilities(self) -> list[Capability]:
        """Return the concrete capabilities exposed by ContainerBody."""
        return get_container_capabilities()

    def get_uptime(self) -> float | None:
        """Read container uptime in seconds from /proc/uptime."""
        return get_container_uptime()

    def orientation_changes(self, snapshot_path: Path | None = None) -> list[str]:
        """Detect filesystem, tool, credential presence, and uptime changes."""
        return detect_orientation_changes(self.workspace, snapshot_path, self.get_uptime)

    def sense(self) -> dict[str, Any]:
        """Return container telemetry snapshot, uptime, and orientation changes."""
        return {
            "metrics": self.metrics.snapshot(),
            "uptime": self.get_uptime(),
            "orientation_changes": self.orientation_changes(),
        }

    def act(self, action: str, **kwargs: Any) -> dict[str, Any]:
        """Dispatch actions defined by ContainerBody."""
        if self.broker is not None:
            from agent.infra.permission_broker import ActionRequest, PermissionLevel

            level = (
                PermissionLevel.L0
                if action in {"read_file", "read", "list_dir", "list", "probe_local_ollama", "http_get", "fetch"}
                else PermissionLevel.L2
            )
            req = ActionRequest(action=action, source="body", level=level, params=kwargs)
            verdict = self.broker.authorize(req)
            if not verdict.allowed:
                return {"ok": False, "error": verdict.reason, "permission_denied": True}
        if action in {"run_shell", "execute"}:
            return self.run_shell(**kwargs)
        elif action in {"read_file", "read"}:
            return self.read_file(**kwargs)
        elif action in {"write_file", "write"}:
            return self.write_file(**kwargs)
        elif action in {"list_dir", "list"}:
            return self.list_dir(**kwargs)
        elif action in {"http_get", "fetch"}:
            return self.http_get(**kwargs)
        elif action == "probe_local_ollama":
            return self.probe_local_ollama(**kwargs)
        else:
            raise ValueError(f"Unknown ContainerBody action: {action}")

    def run_shell(self, cmd: str, timeout: float = 30) -> dict[str, Any]:
        """Run a bounded shell command inside the container."""
        return run_container_shell(
            cmd=cmd,
            timeout=timeout,
            workspace=self.workspace,
            output_cap=self.output_cap,
            logger=self.logger,
            run_process_fn=run_process,
        )

    def _is_core_path(self, path: Path) -> bool:
        """Treat symlink and traversal variants of image-owned harness paths as protected."""
        return _is_core_path_impl(path, self.core_root, self.agent_root)

    def read_file(self, path: str, max_chars: int = DEFAULT_OUTPUT_CAP) -> dict[str, Any]:
        """Read a file that passes path checks."""
        return read_container_file(path, max_chars, self.output_cap)

    def write_file(self, path: str, content: str, append: bool = False) -> dict[str, Any]:
        """Write a workspace file after enforcing path and size limits."""
        return write_container_file(
            path=path,
            content=content,
            append=append,
            workspace=self.workspace,
            core_root=self.core_root,
            agent_root=self.agent_root,
            identity=self.identity,
            logger=self.logger,
        )

    def list_dir(self, path: str, max_entries: int = 500) -> dict[str, Any]:
        """List directory entries up to a bounded count without following links."""
        return list_container_dir(path, max_entries)

    def _log_network(self, url: str, method: str = "GET", **extra: Any) -> None:
        log_network(self.logger, url, method=method, **extra)

    def http_get(
        self,
        url: str,
        timeout: float = 20,
        max_chars: int = DEFAULT_OUTPUT_CAP,
    ) -> dict[str, Any]:
        """Fetch a URL and record observable network access."""
        return http_get_request(url, timeout, max_chars, self.output_cap, self.logger)

    def probe_local_ollama(self) -> dict[str, Any]:
        """Check local Ollama availability without starting or pulling a model."""
        return probe_local_ollama_endpoint(self.logger)

    def health(self) -> dict[str, Any]:
        """Return basic health and workspace accessibility status."""
        workspace_ok = self.workspace.exists() and os.access(self.workspace, os.R_OK | os.W_OK)
        return {
            "ok": workspace_ok,
            "status": "healthy" if workspace_ok else "workspace_inaccessible",
            "workspace": str(self.workspace),
            "uptime_seconds": self.get_uptime(),
            "os": platform.system(),
        }

    def emergency_stop(self) -> None:
        """Halt immediately by writing STOP file in the workspace."""
        try:
            (self.workspace / "STOP").touch()
        except OSError:
            pass
