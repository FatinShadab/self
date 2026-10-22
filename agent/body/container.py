"""ContainerBody implementation for Docker Linux container embodiment."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from agent.body.base import Body, BodyDescription, Capability
from agent.infra.event_log import EventLogger
from agent.infra.process_runner import run_process


def _format_bytes(value: int | None) -> str:
    if value is None or value < 0:
        return "—"
    amount = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if amount < 1024 or unit == "TB":
            return f"{amount:.1f} {unit}" if unit != "B" else f"{int(amount)} B"
        amount /= 1024
    return "—"


def _read_int_file(path: str | Path) -> int | None:
    try:
        return int(Path(path).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _read_cgroup_value(filename: str, *groups: str) -> int | None:
    for group in groups:
        value = _read_int_file(Path("/sys/fs/cgroup") / group / filename)
        if value is not None:
            return value
    return None


class ContainerMetrics:
    """Best-effort live metrics for the current container namespace/cgroup."""

    def __init__(self) -> None:
        self._last_cpu_usage: int | None = None
        self._last_sample = time.monotonic()

    @staticmethod
    def _cpu_usage() -> tuple[int | None, float]:
        stat_path = Path("/sys/fs/cgroup/cpu.stat")
        usage = None
        try:
            values: dict[str, int] = {}
            for line in stat_path.read_text(encoding="utf-8").splitlines():
                key, _, raw = line.partition(" ")
                if key and raw:
                    values[key] = int(raw)
            usage = values.get("usage_usec")
        except (OSError, ValueError):
            usage_ns = _read_cgroup_value("cpuacct.usage", "cpuacct")
            usage = usage_ns // 1_000 if usage_ns is not None else None

        quota_cpus = float(os.cpu_count() or 1)
        try:
            quota, period = Path("/sys/fs/cgroup/cpu.max").read_text(encoding="utf-8").split()
            if quota != "max" and int(period) > 0:
                quota_cpus = max(0.01, int(quota) / int(period))
        except (OSError, ValueError):
            quota = _read_cgroup_value("cpu.cfs_quota_us", "cpu")
            period = _read_cgroup_value("cpu.cfs_period_us", "cpu")
            if quota is not None and quota > 0 and period:
                quota_cpus = max(0.01, quota / period)
        return usage, quota_cpus

    def snapshot(self) -> dict[str, Any]:
        """Return a read-only snapshot of current container resource metrics."""
        now = time.monotonic()
        elapsed = max(0.001, now - self._last_sample)
        cpu_usage, quota_cpus = self._cpu_usage()
        cpu_percent: float | None = None
        if cpu_usage is not None and self._last_cpu_usage is not None:
            cpu_percent = max(0.0, (cpu_usage - self._last_cpu_usage) / 1_000_000 / elapsed / quota_cpus * 100)
        self._last_cpu_usage = cpu_usage
        self._last_sample = now

        ram_used = _read_int_file("/sys/fs/cgroup/memory.current")
        ram_limit: int | None = None
        try:
            raw_limit = Path("/sys/fs/cgroup/memory.max").read_text(encoding="utf-8").strip()
            if raw_limit != "max":
                ram_limit = int(raw_limit)
        except (OSError, ValueError):
            ram_used = ram_used or _read_cgroup_value("memory.usage_in_bytes", "memory")
            ram_limit = _read_cgroup_value("memory.limit_in_bytes", "memory")
            if ram_limit and ram_limit >= 2**60:
                ram_limit = None

        rx_bytes = 0
        tx_bytes = 0
        try:
            for line in Path("/proc/net/dev").read_text(encoding="utf-8").splitlines():
                if ":" not in line:
                    continue
                interface, raw_stats = line.split(":", 1)
                if interface.strip() == "lo":
                    continue
                stats = raw_stats.split()
                if len(stats) >= 9:
                    rx_bytes += int(stats[0])
                    tx_bytes += int(stats[8])
        except (OSError, ValueError):
            rx_bytes = tx_bytes = 0

        disk_read: int | None = None
        try:
            total = 0
            found = False
            for line in Path("/sys/fs/cgroup/io.stat").read_text(encoding="utf-8").splitlines():
                for item in line.split()[1:]:
                    if item.startswith("rbytes="):
                        total += int(item.split("=", 1)[1])
                        found = True
            if found:
                disk_read = total
        except (OSError, ValueError):
            disk_read = None

        return {
            "cpu": f"{cpu_percent:.1f}% / {quota_cpus:g} CPU" if cpu_percent is not None else "—",
            "ram": f"{_format_bytes(ram_used)} / {_format_bytes(ram_limit)}" if ram_limit else _format_bytes(ram_used),
            "network": f"RX {_format_bytes(rx_bytes)} · TX {_format_bytes(tx_bytes)}",
            "disk_read": _format_bytes(disk_read),
            "ram_used_bytes": ram_used,
            "ram_limit_bytes": ram_limit,
            "cpu_percent": cpu_percent,
            "quota_cpus": quota_cpus,
            "rx_bytes": rx_bytes,
            "tx_bytes": tx_bytes,
            "net": f"↓ {_format_bytes(rx_bytes)}  ↑ {_format_bytes(tx_bytes)}",
            "disk": f"{_format_bytes(disk_read)} read" if disk_read is not None else "—",
            "disk_read_bytes": disk_read,
        }


class _LoggingRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, callback: Any) -> None:
        super().__init__()
        self._callback = callback

    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
        self._callback(newurl, "GET", redirect_status=code)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


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
        embodiment_text = (
            "Your body is this Linux container.\n\n"
            "Body-specific rules:\n"
            "- You are root inside the container. The Docker container boundary is the security boundary.\n"
            "- `/opt/agent/core/` is protected image-owned harness code. Read it when useful, but do not modify it with normal tools. Put an evidence-backed unified diff and reasoning in `state/proposed_patches/` with propose_core_patch; only the human may apply it from the host.\n"
            "- `/home/entity/self/` is the editable extension layer for prompts, personality files, planning logic, tool-selection heuristics, and TUI themes. Keep changes there tested and logged."
        )
        pre_capability_rules = [
            "- You are root inside the container. The Docker container boundary is the security boundary.",
        ]
        post_capability_rules = [
            "- `/opt/agent/core/` is protected image-owned harness code. Read it when useful, but do not modify it with normal tools. Put an evidence-backed unified diff and reasoning in `state/proposed_patches/` with propose_core_patch; only the human may apply it from the host.",
            "- `/home/entity/self/` is the editable extension layer for prompts, personality files, planning logic, tool-selection heuristics, and TUI themes. Keep changes there tested and logged.",
        ]
        body_rules = pre_capability_rules + post_capability_rules
        default_interests = [
            "mapping the container accurately",
            "building reliable, tested tools",
            "learning from evidence and human feedback",
        ]
        initial_orientation_task = (
            "Immediately inventory the installed Python packages in this container. "
            "Use the relevant shell/tool action now, record the result with update_environment_map, "
            "and do not spend this cycle only planning."
        )
        conversation_context = "whose operating environment is this Linux container."
        identity_context = (
            "running inside this Linux container. "
            "The container is my operating environment, not a biological body."
        )
        identity_harness_context = "running in a Linux container."
        identity_orientation_context = "running inside this Linux container."
        identity_operating_environment = "The container is my operating environment, not a biological body."
        notes_preamble = (
            "I am SELF, a root process inside a Docker Linux container. "
            "I explore the container, retain verified discoveries, and only register reviewed, tested tools."
        )
        return BodyDescription(
            embodiment_text=embodiment_text,
            embodiment_clause="whose body is this Linux container.",
            default_interests=default_interests,
            initial_orientation_task=initial_orientation_task,
            conversation_context=conversation_context,
            identity_context=identity_context,
            identity_harness_context=identity_harness_context,
            identity_orientation_context=identity_orientation_context,
            identity_operating_environment=identity_operating_environment,
            notes_preamble=notes_preamble,
            body_rules=body_rules,
            pre_capability_rules=pre_capability_rules,
            post_capability_rules=post_capability_rules,
        )


    def capabilities(self) -> list[Capability]:
        """Return the concrete capabilities exposed by ContainerBody."""
        return [
            Capability(
                name="run_shell",
                schema={
                    "type": "object",
                    "properties": {
                        "cmd": {"type": "string", "description": "The command line string to run."},
                        "timeout": {"type": "number", "description": "Execution timeout in seconds; default 30.", "default": 30},
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
                        "max_chars": {"type": "integer", "description": "Maximum characters to return; bounded by output cap.", "default": 20000},
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
                        "append": {"type": "boolean", "description": "If true, append to file instead of overwriting.", "default": False},
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
                        "max_entries": {"type": "integer", "description": "Maximum entries to return; capped at 5000.", "default": 500},
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
                        "timeout": {"type": "number", "description": "Request timeout in seconds; default 20.", "default": 20},
                        "max_chars": {"type": "integer", "description": "Maximum characters to return; bounded by output cap.", "default": 20000},
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

    def get_uptime(self) -> float | None:
        """Read container uptime in seconds from /proc/uptime."""
        try:
            return float(Path("/proc/uptime").read_text(encoding="utf-8").split()[0])
        except (OSError, ValueError, IndexError):
            return None

    def orientation_changes(self, snapshot_path: Path | None = None) -> list[str]:
        """Detect filesystem, tool, credential presence, and uptime changes."""
        if snapshot_path is None:
            snapshot_path = self.workspace / "state" / "wake_snapshot.json"
        old: dict[str, Any] = {}
        if snapshot_path.exists():
            try:
                old = json.loads(snapshot_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                old = {}
        uptime = self.get_uptime()
        tools_dir = self.workspace / "tools"
        tool_names: list[str] = []
        if tools_dir.exists():
            for meta in tools_dir.glob("*/meta.json"):
                try:
                    data = json.loads(meta.read_text(encoding="utf-8"))
                    if data.get("registered"):
                        tool_names.append(str(data.get("name", meta.parent.name)))
                except (OSError, ValueError):
                    pass

        known_credential_env = (
            "OLLAMA_API_KEYS", "OLLAMA_API_KEY", "OLLAM_API_KEYS", "OLLAM_API_KEY",
            "ANTHROPIC_API_KEYS", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "GROQ_API_KEY",
            "OPENROUTER_API_KEY", "MISTRAL_API_KEY", "CEREBRAS_API_KEY", "HF_TOKEN",
            "CLOUDFLARE_API_TOKEN",
        )
        current = {
            "workspace_entries": sorted(path.name for path in self.workspace.iterdir() if path.name not in {"logs", "state"}) if self.workspace.exists() else [],
            "tools": sorted(tool_names),
            "credential_env_present": sorted(name for name in known_credential_env if os.getenv(name)),
            "uptime_seconds": uptime,
        }
        changes: list[str] = []
        for key in ("workspace_entries", "tools", "credential_env_present"):
            if key in old and old.get(key) != current[key]:
                changes.append(f"{key.replace('_', ' ')} changed")
        if old and uptime is not None and old.get("uptime_seconds") is not None and uptime < float(old["uptime_seconds"]):
            changes.append("container uptime reset")
        try:
            snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = snapshot_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            os.replace(temporary, snapshot_path)
        except OSError:
            pass
        return changes or ["no tracked workspace, tool, credential-presence, or uptime change"]

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
            level = PermissionLevel.L0 if action in {"read_file", "read", "list_dir", "list", "probe_local_ollama", "http_get", "fetch"} else PermissionLevel.L2
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

        shell_bin = "/bin/bash" if Path("/bin/bash").exists() else (shutil.which("bash") or "/bin/bash")
        return run_process([shell_bin, "-lc", cmd], cwd=self.workspace,
                           timeout=float(timeout), cap=self.output_cap,
                           on_output=on_output, on_complete=on_complete)

    def _is_core_path(self, path: Path) -> bool:
        """Treat symlink and traversal variants of image-owned harness paths as protected."""
        try:
            candidate = path.resolve(strict=False)
            return any(candidate.is_relative_to(root.resolve(strict=False)) for root in (self.core_root, self.agent_root))
        except OSError:
            return False

    def read_file(self, path: str, max_chars: int = DEFAULT_OUTPUT_CAP) -> dict[str, Any]:
        """Read a file that passes path checks."""
        limit = max(1, min(int(max_chars), self.output_cap))
        file_path = Path(path)
        with file_path.open("r", encoding="utf-8", errors="replace") as handle:
            content = handle.read(limit + 1)
        return {
            "ok": True,
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
        from agent.opencode.sandbox import is_protected_path
        if is_protected_path(file_path, workspace=self.workspace):
            raise PermissionError(
                f"Path '{path}' is protected against direct modification by agent tools."
            )
        if self.identity is not None and getattr(self.identity, "is_managed_path", None) is not None:
            if self.identity.is_managed_path(file_path):
                raise PermissionError(
                    "Identity-managed state cannot be overwritten through write_file. Preserve the append-only identity trail; the human may edit identity.json directly from the host, while the harness records evidence-backed reflection changes."
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
        return {
            "ok": True,
            "path": str(file_path),
            "chars_written": written,
            "bytes_written": written,
            "append": bool(append),
        }

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
                    try:
                        item["size"] = entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        pass
                entries.append(item)
        entries.sort(key=lambda item: (item["type"], item["name"].lower()))
        return {"ok": True, "path": str(path), "entries": entries, "truncated": truncated}

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

    def probe_local_ollama(self) -> dict[str, Any]:
        """Check local Ollama availability without starting or pulling a model."""
        base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
        parsed = urllib.parse.urlsplit(base_url)
        self.logger.log("network_request", method="GET", host=parsed.hostname or "", path=f"{parsed.path}/api/tags", purpose="local_ollama_probe")
        try:
            with urllib.request.urlopen(f"{base_url}/api/tags", timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
            models = [str(item.get("name", "")) for item in payload.get("models", []) if item.get("name")]
            available = bool(models)
            return {
                "ok": available,
                "reachable": True,
                "models": models,
                "message": "Local Ollama reachable." if available else "Ollama is reachable but no model is installed; no download was attempted.",
            }
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            return {
                "ok": False,
                "reachable": False,
                "models": [],
                "message": f"Local Ollama is not reachable on {base_url}: {type(exc).__name__}.",
            }

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
