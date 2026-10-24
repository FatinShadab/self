"""Sandbox creation, scope checks, environment isolation, and safeguard enforcement.

Creates isolated copies of the repository for delegated coding tasks, verifies that
changes remain strictly within allowed roots, and executes subprocesses under an
unprivileged user when running in a privileged container.
"""
from __future__ import annotations

import hashlib
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("agent.opencode.sandbox")

# Default allowed write roots for opencode delegations.
DEFAULT_ALLOWED_ROOTS = [
    "workspace/tools",
    "workspace/plugin_dev",
    "workspace/plugins",
    "workspace/scratch",
    "tools",
    "plugin_dev",
    "plugins",
    "scratch",
]

# Patterns and directories excluded when copying repository into the sandbox.
SANDBOX_EXCLUDED_DIRS = {
    ".git",
    "vendor",
    "state",
    "sandboxes",
    "__pycache__",
    ".pytest_cache",
}

SANDBOX_EXCLUDED_REL_PATHS = {
    "scripts/opencode",
    "agent/opencode",
    "workspace/state",
    "workspace/memory",
    "workspace/logs",
    "workspace/self",
}

# Protected paths that Self's own file writing tools must refuse.
PROTECTED_WRITE_PATHS = [
    ".env",
    "scripts/opencode",
    "agent/opencode",
    "config",
]


def is_protected_path(path: str | Path, workspace: Path | None = None) -> bool:
    """Return True if *path* matches any protected file or directory pattern."""
    p = Path(path)
    # Check normalized string representation
    norm = str(p).replace("\\", "/").strip()
    norm_lower = norm.lower()

    # 1. Any .env file
    name = p.name.lower()
    if name == ".env" or name.startswith(".env."):
        return True

    # 2. Any lock files or human request pause files
    if (
        name.endswith(".lock")
        or name.endswith(".lock.json")
        or name == "human_request.md"
        or name == "pending_human_request.json"
        or ".self_harness" in norm_lower
    ):
        return True

    # 3. Opencode scripts and wrapper subpackage
    if "scripts/opencode" in norm_lower or "agent/opencode" in norm_lower:
        return True

    # 4. Config directory
    parts = p.parts
    if "config" in parts:
        return True

    # 5. Opencode status state files
    if "opencode_status.json" in name or "opencode_delegations.json" in name:
        return True

    # 6. Check relative to workspace if given
    if workspace:
        try:
            rel = p.resolve().relative_to(workspace.resolve())
            rel_str = str(rel).replace("\\", "/").lower()
            if any(rel_str == prot or rel_str.startswith(f"{prot}/") for prot in ("scripts/opencode", "agent/opencode", "config")):
                return True
        except (ValueError, OSError):
            pass

    return False


def build_opencode_env(
    provider: str | None = None,
    base_env: dict[str, str] | None = None,
    config_dir: str | Path = "/opt/opencode/config",
    opencode_home: str | Path = "/home/opencode",
) -> dict[str, str]:
    """Construct a minimal, sanitized environment for the opencode subprocess.

    Passes ONLY PATH, LANG, HOME, OPENCODE_CONFIG_DIR, and the mapped
    API keys. Never passes Self's own provider keys or other parent variables.
    """
    source = base_env if base_env is not None else os.environ

    # Resolve home directory for opencode
    home_dir = str(opencode_home) if Path(str(opencode_home)).is_dir() else str(Path.home())

    clean_env: dict[str, str] = {
        "PATH": source.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "LANG": source.get("LANG", "C.UTF-8"),
        "HOME": home_dir,
        "OPENCODE_CONFIG_DIR": str(config_dir),
    }

    # Pass test simulation mode if present
    if "FAKE_OPENCODE_MODE" in source:
        clean_env["FAKE_OPENCODE_MODE"] = source["FAKE_OPENCODE_MODE"]

    # Map the 3 namespaced keys to standard names
    key_mappings = {
        "groq": ("OPENCODE_GROQ_API_KEY", "GROQ_API_KEY"),
        "google": ("OPENCODE_GOOGLE_API_KEY", "GEMINI_API_KEY"),
        "huggingface": ("OPENCODE_HF_TOKEN", "HF_TOKEN"),
    }

    if provider:
        mapping = key_mappings.get(provider.lower())
        if mapping:
            namespaced_var, standard_var = mapping
            val = source.get(namespaced_var, "").strip()
            if val:
                clean_env[standard_var] = val
    else:
        for namespaced_var, standard_var in key_mappings.values():
            val = source.get(namespaced_var, "").strip()
            if val:
                clean_env[standard_var] = val

    return clean_env


def compute_file_hash(path: Path) -> str:
    """Compute SHA-256 digest of a file."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def compute_manifest(root: Path) -> dict[str, str]:
    """Walk *root* and return a mapping of normalized relative path to sha256."""
    manifest: dict[str, str] = {}
    for p in root.rglob("*"):
        if p.is_file():
            try:
                rel = p.relative_to(root).as_posix()
                manifest[rel] = compute_file_hash(p)
            except (OSError, ValueError):
                pass
    return manifest


def _should_exclude(rel_path: str) -> bool:
    """Return True if relative path should be excluded from sandbox copy."""
    norm = rel_path.replace("\\", "/").strip("/")
    parts = norm.split("/")

    # Exclude .env and any .env.*
    filename = parts[-1].lower()
    if filename == ".env" or filename.startswith(".env."):
        return True

    # Exclude blacklisted directory names anywhere in path
    for excluded_dir in SANDBOX_EXCLUDED_DIRS:
        if excluded_dir in parts:
            return True

    # Exclude specific relative path prefixes
    for excluded_prefix in SANDBOX_EXCLUDED_REL_PATHS:
        if norm == excluded_prefix or norm.startswith(f"{excluded_prefix}/"):
            return True

    return False


class SandboxManager:
    """Manages creation, execution, scope verification, and cleanup of sandboxes."""

    def __init__(
        self,
        repo_root: str | Path | None = None,
        sandboxes_dir: str | Path | None = None,
        allowed_roots: list[str] | None = None,
    ) -> None:
        self.repo_root = Path(repo_root) if repo_root else Path.cwd()
        self.sandboxes_dir = (
            Path(sandboxes_dir)
            if sandboxes_dir
            else self.repo_root / "workspace" / "sandboxes"
        )
        self.allowed_roots = list(allowed_roots) if allowed_roots is not None else list(DEFAULT_ALLOWED_ROOTS)

    def create_sandbox(self, delegation_id: str) -> tuple[Path, dict[str, str]]:
        """Create a sandbox copy of repo_root, excluding sensitive paths.

        Returns (sandbox_path, initial_manifest).
        """
        self.sandboxes_dir.mkdir(parents=True, exist_ok=True)
        sandbox_path = self.sandboxes_dir / f"sandbox_{delegation_id}"
        if sandbox_path.exists():
            shutil.rmtree(sandbox_path, ignore_errors=True)
        sandbox_path.mkdir(parents=True, exist_ok=True)

        # Copy allowed files from repo_root
        resolved_sandboxes = self.sandboxes_dir.resolve()
        for src_path in self.repo_root.rglob("*"):
            if not src_path.is_file():
                continue
            try:
                if src_path.resolve().is_relative_to(resolved_sandboxes):
                    continue
            except (ValueError, OSError):
                pass
            try:
                rel = src_path.relative_to(self.repo_root).as_posix()
            except ValueError:
                continue

            if _should_exclude(rel):
                continue

            dest_path = sandbox_path / rel
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(src_path, dest_path)
            except OSError as exc:
                logger.warning("Could not copy %s into sandbox: %s", src_path, exc)

        # Compute initial manifest
        manifest = compute_manifest(sandbox_path)

        # Attempt to set ownership to unprivileged opencode user if running as root
        self._chown_to_opencode_if_root(sandbox_path)

        return sandbox_path, manifest

    def _chown_to_opencode_if_root(self, path: Path) -> str:
        """If root on POSIX, chown *path* to opencode:opencode."""
        if os.name != "posix" or not hasattr(os, "geteuid") or os.geteuid() != 0:
            return "none"
        try:
            import pwd
            pw = pwd.getpwnam("opencode")
            uid, gid = pw.pw_uid, pw.pw_gid
            for root_dir, dirnames, filenames in os.walk(str(path)):
                os.chown(root_dir, uid, gid)
                for f in filenames:
                    os.chown(os.path.join(root_dir, f), uid, gid)
            return "user:opencode"
        except (KeyError, OSError, ImportError):
            return "none"

    def check_scope(
        self,
        sandbox_path: Path,
        initial_manifest: dict[str, str],
        allowed_roots: list[str] | None = None,
    ) -> tuple[bool, dict[str, list[str]]]:
        """Compare sandbox files against manifest.

        Returns (is_clean, {"added": [...], "modified": [...], "deleted": [...]}).
        If any changed file is outside allowed_roots, is_clean is False.
        """
        effective_allowed = self.allowed_roots if allowed_roots is None else allowed_roots
        normalized_allowed = [r.replace("\\", "/").strip("/") for r in effective_allowed]

        current_manifest = compute_manifest(sandbox_path)

        added: list[str] = []
        modified: list[str] = []
        deleted: list[str] = []

        # Check added and modified
        for path_rel, new_hash in current_manifest.items():
            if path_rel not in initial_manifest:
                added.append(path_rel)
            elif initial_manifest[path_rel] != new_hash:
                modified.append(path_rel)

        # Check deleted
        for path_rel in initial_manifest:
            if path_rel not in current_manifest:
                deleted.append(path_rel)

        all_changes = added + modified + deleted
        is_clean = True

        for changed in all_changes:
            norm_c = changed.replace("\\", "/").strip("/")
            # Check if this changed file falls under any allowed root
            in_allowed = False
            for root in normalized_allowed:
                if norm_c == root or norm_c.startswith(f"{root}/"):
                    in_allowed = True
                    break
            if not in_allowed:
                is_clean = False
                logger.warning("Scope violation: file changed outside allowed roots: %s", changed)

        return is_clean, {
            "added": sorted(added),
            "modified": sorted(modified),
            "deleted": sorted(deleted),
        }

    def run_in_sandbox(
        self,
        cmd: list[str] | str,
        sandbox_path: Path,
        env: dict[str, str],
        timeout_seconds: int = 1800,
        shell: bool = False,
    ) -> tuple[subprocess.CompletedProcess, str]:
        """Execute a command inside the sandbox as unprivileged user if possible.

        Returns (completed_process, isolation_level).
        """
        isolation = "none"
        extra_kwargs: dict[str, Any] = {}

        if os.name == "posix" and hasattr(os, "geteuid") and os.geteuid() == 0:
            try:
                import pwd
                pw = pwd.getpwnam("opencode")
                extra_kwargs["user"] = pw.pw_uid
                extra_kwargs["group"] = pw.pw_gid
                isolation = "user:opencode"
            except (KeyError, ImportError):
                isolation = "none"

        try:
            res = subprocess.run(
                cmd,
                cwd=str(sandbox_path),
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                shell=shell,
                **extra_kwargs,
            )
            return res, isolation
        except subprocess.TimeoutExpired as exc:
            return (
                subprocess.CompletedProcess(
                    args=cmd,
                    returncode=124,
                    stdout=exc.stdout or "",
                    stderr=f"Timed out after {timeout_seconds} seconds.",
                ),
                isolation,
            )

    def cleanup_old_sandboxes(self, max_age_days: int = 7) -> int:
        """Delete sandboxes older than max_age_days. Returns count of removed sandboxes."""
        if not self.sandboxes_dir.exists():
            return 0

        cutoff = time.time() - (max_age_days * 86400)
        removed = 0

        for item in self.sandboxes_dir.iterdir():
            if item.is_dir() and item.name.startswith("sandbox_"):
                try:
                    mtime = item.stat().st_mtime
                    if mtime < cutoff:
                        shutil.rmtree(item, ignore_errors=True)
                        removed += 1
                except (OSError, FileNotFoundError):
                    pass

        return removed
