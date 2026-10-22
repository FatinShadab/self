"""Opencode delegation wrapper coordinator.

Coordinates provider availability, sandboxing, headless subprocess execution,
acceptance check verification, scope checking, and delegation record management.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from agent.infra.file_lock import locked_file
from agent.opencode.sandbox import (
    DEFAULT_ALLOWED_ROOTS,
    SandboxManager,
    build_opencode_env,
)
from agent.opencode.status import (
    OpencodeStatusTracker,
    classify_failure,
    parse_reset_time,
)

logger = logging.getLogger("agent.opencode.wrapper")

DEFAULT_TIMEOUT_SECONDS = 1800  # 30 minutes
DEFAULT_CHECK_TIMEOUT_SECONDS = 600  # 10 minutes


def _tail(text: str, max_chars: int = 2000) -> str:
    """Return the trailing portion of text up to max_chars."""
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    return f"... [truncated {len(text) - max_chars} chars] ...\n" + text[-max_chars:]


class OpencodeDelegator:
    """Orchestrates delegation of coding tasks to opencode."""

    def __init__(
        self,
        workspace: str | Path | None = None,
        config_path: str | Path | None = None,
        binary_path: str = "/usr/local/bin/opencode",
        sandboxes_dir: str | Path | None = None,
        allowed_roots: list[str] | None = None,
        runner_fn: Callable[..., subprocess.CompletedProcess] | None = None,
        model_decisions: Any | None = None,
    ) -> None:
        self.workspace = Path(workspace) if workspace else Path.cwd()
        self.config_path = (
            Path(config_path)
            if config_path
            else self.workspace / "scripts" / "opencode" / "config.json"
        )
        self.binary_path = binary_path
        self.runner_fn = runner_fn or subprocess.run
        self.model_decisions = model_decisions

        # Initialize status tracker
        self.status_tracker = OpencodeStatusTracker(
            workspace=self.workspace,
            config_path=self.config_path,
            binary_path=self.binary_path,
            runner_fn=self.runner_fn,
        )

        # Initialize sandbox manager
        self.sandbox_manager = SandboxManager(
            repo_root=self.workspace,
            sandboxes_dir=sandboxes_dir,
            allowed_roots=allowed_roots,
        )

        # Delegations state file: state/opencode_delegations.json
        state_dir = self.workspace / "state"
        self.delegations_path = state_dir / "opencode_delegations.json"
        self.delegations_lock = self.delegations_path.with_suffix(".lock")
        self._ensure_delegations_file()

    def _ensure_delegations_file(self) -> None:
        """Create empty delegations state file if absent."""
        if not self.delegations_path.exists():
            self._write_delegations({})

    def _read_delegations(self) -> dict[str, Any]:
        """Read delegations dict under lock."""
        try:
            if self.delegations_path.exists():
                data = json.loads(self.delegations_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
        except (OSError, json.JSONDecodeError):
            pass
        return {}

    def _write_delegations(self, data: dict[str, Any]) -> None:
        """Atomically persist delegations dict under lock."""
        self.delegations_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.delegations_path.with_suffix(f".tmp.{os.getpid()}")
        try:
            tmp_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            os.replace(tmp_path, self.delegations_path)
        except BaseException:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def get_delegation(self, delegation_id: str) -> dict[str, Any] | None:
        """Look up a recorded delegation by ID."""
        with locked_file(self.delegations_lock):
            delegations = self._read_delegations()
            return delegations.get(delegation_id)

    def _save_delegation(self, record: dict[str, Any]) -> None:
        """Save or update a delegation record."""
        with locked_file(self.delegations_lock):
            delegations = self._read_delegations()
            delegations[record["delegation_id"]] = record
            self._write_delegations(delegations)

    def _ensure_model_decisions(self) -> Any:
        """Lazily initialize ModelDecisions for recording build routes and outcomes."""
        if self.model_decisions is None:
            from agent.helper_models.model_decisions import ModelDecisions
            from agent.infra.event_log import EventLogger

            logger = EventLogger(self.workspace / "logs" / "actions.jsonl")
            self.model_decisions = ModelDecisions(self.workspace, logger, None, None, "delegation")
        return self.model_decisions

    def is_installed(self) -> bool:
        """Check if opencode executable is present and accessible."""
        p = Path(self.binary_path)
        if p.exists():
            return True
        import shutil
        return shutil.which(str(self.binary_path)) is not None

    def status(self) -> dict[str, Any]:
        """Return system usability status without network access or probing."""
        installed = self.is_installed()
        if not installed:
            return {
                "ok": True,
                "installed": False,
                "usable": False,
                "reason": "opencode not installed",
                "earliest_retry": None,
                "providers": {},
            }
        u = self.status_tracker.usability()
        return {
            "ok": True,
            "installed": True,
            "usable": u["usable"],
            "reason": u["reason"],
            "earliest_retry": u["earliest_retry"],
            "providers": u["providers"],
        }

    def _load_configured_models(self) -> list[str]:
        """Read ordered models list from config.json."""
        if self.config_path.is_file():
            try:
                data = json.loads(self.config_path.read_text(encoding="utf-8"))
                models = data.get("models", [])
                return [
                    m
                    for m in models
                    if isinstance(m, str) and not m.startswith("_PLACEHOLDER") and "/" in m
                ]
            except (OSError, json.JSONDecodeError):
                pass
        return []

    def _resolve_provider_candidates(
        self, requested_model: str | None, usability_providers: dict[str, Any]
    ) -> list[tuple[str, str | None]]:
        """Order candidate (provider, model) pairs according to usability."""
        candidates: list[tuple[str, str | None]] = []
        seen_providers: set[str] = set()

        def is_provider_usable(pname: str) -> bool:
            pst = usability_providers.get(pname, {}).get("state", "unknown")
            return pst in ("available", "unknown", "probe_due")

        # 1. Requested model first if provided
        if requested_model and "/" in requested_model:
            req_prov = requested_model.split("/", 1)[0].lower()
            if is_provider_usable(req_prov):
                candidates.append((req_prov, requested_model))
                seen_providers.add(req_prov)

        # 2. Configured models in order
        for m in self._load_configured_models():
            p = m.split("/", 1)[0].lower()
            if p not in seen_providers and is_provider_usable(p):
                candidates.append((p, m))
                seen_providers.add(p)

        # 3. Any remaining usable providers without explicit model
        for p in ("groq", "google", "huggingface"):
            if p not in seen_providers and is_provider_usable(p):
                candidates.append((p, None))
                seen_providers.add(p)

        return candidates

    def delegate_coding(
        self,
        spec: str,
        route_reasons: str,
        target_dirs: list[str],
        acceptance_check: str,
        model: str | None = None,
        timeout_seconds: int | None = None,
        check_timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        """Delegate a coding task to opencode within an isolated sandbox."""
        start_time = time.monotonic()
        timeout = timeout_seconds or DEFAULT_TIMEOUT_SECONDS
        check_timeout = check_timeout_seconds or DEFAULT_CHECK_TIMEOUT_SECONDS

        # 1. Validate route_reasons (required free text)
        if not route_reasons or not str(route_reasons).strip():
            return {
                "ok": False,
                "status": "error",
                "error": "route_reasons is required free text explaining why Self chose to delegate.",
            }

        # Auto-record build route decision (route "opencode", origin "agent")
        try:
            self._ensure_model_decisions().record_build_route(
                task=spec,
                route="opencode",
                reasons=route_reasons,
                expected_effort="delegated",
                forced_by=None,
            )
        except Exception as exc:
            logger.warning("Failed to record build route decision: %s", exc)

        # Check installation
        if not self.is_installed():
            try:
                self._ensure_model_decisions().record_build_outcome(
                    task_id=spec[:80],
                    route="opencode",
                    result="unavailable",
                    notes="opencode not installed",
                    acceptance_passed=False,
                    duration=0.0,
                    retries=0,
                )
            except Exception:
                pass
            msg = (
                "opencode is not installed. "
                "You should do the work yourself. "
                "Call record_build_route with forced_by=opencode_unavailable so this is not mistaken for a preference."
            )
            return {
                "ok": False,
                "status": "unavailable",
                "reason": "opencode not installed",
                "earliest_retry": None,
                "providers": {},
                "message": msg,
                "error": msg,
            }

        # 2. Validate target_dirs (must be inside allowed write roots)
        allowed_normalized = [r.replace("\\", "/").strip("/") for r in self.sandbox_manager.allowed_roots]
        for tdir in target_dirs:
            norm_t = str(tdir).replace("\\", "/").strip("/")
            is_allowed = any(norm_t == root or norm_t.startswith(f"{root}/") for root in allowed_normalized)
            if not is_allowed:
                return {
                    "ok": False,
                    "status": "rejected_scope",
                    "error": f"Target directory '{tdir}' is outside allowed write roots: {self.sandbox_manager.allowed_roots}",
                }

        # 3. Clean up old sandboxes
        try:
            self.sandbox_manager.cleanup_old_sandboxes()
        except Exception as exc:
            logger.warning("Sandbox cleanup warning: %s", exc)

        # 4. Check usability and probe any probe_due providers
        u = self.status_tracker.usability()
        for pname, pdata in u["providers"].items():
            if pdata.get("state") == "probe_due":
                logger.info("Provider %s is probe_due; running health probe.", pname)
                self.status_tracker.probe(pname)

        # Re-check usability after probes
        u = self.status_tracker.usability()
        candidates = self._resolve_provider_candidates(model, u["providers"]) if u["usable"] else []

        if not u["usable"] or not candidates:
            reason_text = u["reason"] if not u["usable"] else "No usable providers or models found."
            earliest_time = u.get("earliest_retry") or "an unknown time"
            try:
                self._ensure_model_decisions().record_build_outcome(
                    task_id=spec[:80],
                    route="opencode",
                    result="unavailable",
                    notes=f"Opencode unavailable: {reason_text}",
                    acceptance_passed=False,
                    duration=0.0,
                    retries=0,
                )
            except Exception as exc:
                logger.warning("Failed to record build outcome on unavailable: %s", exc)

            msg = (
                f"opencode is unavailable until about {earliest_time} ({reason_text}). "
                "You should either do the work yourself or postpone. "
                "If you do it yourself, call record_build_route with forced_by=opencode_unavailable "
                "so this is not mistaken for a preference."
            )
            return {
                "ok": False,
                "status": "unavailable",
                "reason": reason_text,
                "earliest_retry": u["earliest_retry"],
                "providers": u["providers"],
                "message": msg,
                "error": msg,
            }

        # 6. Create sandbox
        delegation_id = uuid.uuid4().hex[:12]
        sandbox_path, initial_manifest = self.sandbox_manager.create_sandbox(delegation_id)

        # 7. Formulate opencode prompt
        target_dirs_str = ", ".join(target_dirs)
        prompt_preamble = (
            "You are an automated coding assistant operating inside a repository sandbox.\n"
            f"You may ONLY create, edit, or delete files inside the following directories: {target_dirs_str}.\n"
            "Do NOT modify or touch files outside these directories.\n"
            "Your changes must make the following acceptance check pass:\n"
            f"  {acceptance_check}\n\n"
            f"Task Specification:\n{spec}\n"
        )

        providers_tried: list[str] = []
        chosen_provider: str | None = None
        chosen_model: str | None = None
        opencode_log: str = ""
        isolation_used: str = "none"
        opencode_success = False
        last_failure_category = "error"

        # 8. Run opencode with fallback across usable providers
        for attempt_idx, (pname, mname) in enumerate(candidates):
            providers_tried.append(pname)
            current_prompt = prompt_preamble
            if attempt_idx > 0:
                current_prompt += (
                    "\n\nNOTE: A previous attempt using another provider failed or was interrupted. "
                    "Partial work may already exist in the repository sandbox."
                )

            # Build command: opencode run --auto --standalone [--model <model>] "<prompt>"
            cmd = [self.binary_path, "run", "--auto", "--standalone"]
            if mname:
                cmd.extend(["--model", mname])
            cmd.append(current_prompt)

            # Build environment
            clean_env = build_opencode_env(provider=pname)

            # Execute in sandbox
            res, isolation = self.sandbox_manager.run_in_sandbox(
                cmd,
                sandbox_path=sandbox_path,
                env=clean_env,
                timeout_seconds=timeout,
            )
            isolation_used = isolation
            out = (res.stdout or "") + "\n" + (res.stderr or "")
            opencode_log = out

            if res.returncode == 0:
                # Opencode succeeded
                self.status_tracker.record_success(pname)
                chosen_provider = pname
                chosen_model = mname
                opencode_success = True
                break
            elif res.returncode == 124:
                # Timeout
                last_failure_category = "timeout"
                logger.warning("opencode timed out after %ds on provider %s", timeout, pname)
                break
            else:
                # Classified failure
                cat = classify_failure(res.returncode, out)
                last_failure_category = cat
                reset_sec = parse_reset_time(out)
                self.status_tracker.record_failure(pname, cat, out[:300], reset_sec)
                logger.warning("opencode failed on %s (classified as %s)", pname, cat)
                continue

        duration = round(time.monotonic() - start_time, 2)

        if not opencode_success:
            final_status = "timeout" if last_failure_category == "timeout" else (
                "throttled" if last_failure_category in ("throttled", "quota_daily") else "error"
            )
            try:
                self._ensure_model_decisions().record_build_outcome(
                    task_id=delegation_id,
                    route="opencode",
                    result="failed",
                    notes=f"opencode execution failed with status: {final_status}",
                    acceptance_passed=False,
                    duration=duration,
                    retries=max(0, len(providers_tried) - 1),
                    provider=chosen_provider,
                    model=chosen_model,
                )
            except Exception as exc:
                logger.warning("Failed to record build outcome on failure: %s", exc)

            record = {
                "delegation_id": delegation_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "spec": spec,
                "route_reasons": route_reasons,
                "target_dirs": target_dirs,
                "acceptance_check": acceptance_check,
                "providers_tried": providers_tried,
                "provider_used": chosen_provider,
                "model_used": chosen_model,
                "status": final_status,
                "changed_files": {"added": [], "modified": [], "deleted": []},
                "acceptance_output": "",
                "opencode_log": _tail(opencode_log),
                "duration_seconds": duration,
                "isolation": isolation_used,
                "sandbox_path": str(sandbox_path),
                "applied": False,
                "discarded": False,
            }
            self._save_delegation(record)
            return {
                "ok": False,
                "delegation_id": delegation_id,
                "status": final_status,
                "error": f"opencode execution failed with status: {final_status}",
                "providers_tried": providers_tried,
                "opencode_log_tail": _tail(opencode_log),
                "duration_seconds": duration,
                "isolation": isolation_used,
            }

        # 9. Scope check
        is_clean, changed_files = self.sandbox_manager.check_scope(sandbox_path, initial_manifest)
        if not is_clean:
            try:
                self._ensure_model_decisions().record_build_outcome(
                    task_id=delegation_id,
                    route="opencode",
                    result="rejected",
                    notes="Changes detected outside allowed target directories; delegation rejected.",
                    acceptance_passed=False,
                    duration=duration,
                    retries=max(0, len(providers_tried) - 1),
                    provider=chosen_provider,
                    model=chosen_model,
                )
            except Exception as exc:
                logger.warning("Failed to record build outcome on rejected_scope: %s", exc)

            record = {
                "delegation_id": delegation_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "spec": spec,
                "route_reasons": route_reasons,
                "target_dirs": target_dirs,
                "acceptance_check": acceptance_check,
                "providers_tried": providers_tried,
                "provider_used": chosen_provider,
                "model_used": chosen_model,
                "status": "rejected_scope",
                "changed_files": changed_files,
                "acceptance_output": "",
                "opencode_log": _tail(opencode_log),
                "duration_seconds": duration,
                "isolation": isolation_used,
                "sandbox_path": str(sandbox_path),
                "applied": False,
                "discarded": False,
            }
            self._save_delegation(record)
            return {
                "ok": False,
                "delegation_id": delegation_id,
                "status": "rejected_scope",
                "error": "Changes detected outside allowed target directories; delegation rejected.",
                "changed_files": changed_files,
                "opencode_log_tail": _tail(opencode_log),
                "provider": chosen_provider,
                "model": chosen_model,
                "duration_seconds": duration,
                "isolation": isolation_used,
            }

        # 10. Run acceptance check in sandbox
        check_res, check_iso = self.sandbox_manager.run_in_sandbox(
            acceptance_check,
            sandbox_path=sandbox_path,
            env=build_opencode_env(provider=chosen_provider),
            timeout_seconds=check_timeout,
            shell=True,
        )
        check_out = (check_res.stdout or "") + "\n" + (check_res.stderr or "")

        final_status = "completed" if check_res.returncode == 0 else "check_failed"
        if final_status == "check_failed":
            try:
                self._ensure_model_decisions().record_build_outcome(
                    task_id=delegation_id,
                    route="opencode",
                    result="failed",
                    notes="Acceptance check failed inside sandbox.",
                    acceptance_passed=False,
                    duration=duration,
                    retries=max(0, len(providers_tried) - 1),
                    provider=chosen_provider,
                    model=chosen_model,
                )
            except Exception as exc:
                logger.warning("Failed to record build outcome on check_failed: %s", exc)

        record = {
            "delegation_id": delegation_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "spec": spec,
            "route_reasons": route_reasons,
            "target_dirs": target_dirs,
            "acceptance_check": acceptance_check,
            "providers_tried": providers_tried,
            "provider_used": chosen_provider,
            "model_used": chosen_model,
            "status": final_status,
            "changed_files": changed_files,
            "acceptance_output": _tail(check_out),
            "opencode_log": _tail(opencode_log),
            "duration_seconds": duration,
            "isolation": isolation_used,
            "sandbox_path": str(sandbox_path),
            "applied": False,
            "discarded": False,
        }
        self._save_delegation(record)

        return {
            "ok": final_status == "completed",
            "delegation_id": delegation_id,
            "status": final_status,
            "providers_tried": providers_tried,
            "changed_files": changed_files,
            "acceptance_output_tail": _tail(check_out),
            "opencode_log_tail": _tail(opencode_log),
            "provider": chosen_provider,
            "model": chosen_model,
            "duration_seconds": duration,
            "isolation": isolation_used,
        }

    def apply_delegation(self, delegation_id: str) -> dict[str, Any]:
        """Apply a completed delegation's changes to the real repository.

        Only allowed when status is 'completed' and scope was clean.
        Re-runs acceptance_check on the real tree; rolls back on failure.
        """
        record = self.get_delegation(delegation_id)
        if not record:
            return {"ok": False, "applied": False, "error": f"Delegation '{delegation_id}' not found."}

        if record.get("status") != "completed":
            return {
                "ok": False,
                "applied": False,
                "error": f"Cannot apply delegation with status '{record.get('status')}'; must be 'completed'.",
            }

        if record.get("applied"):
            return {"ok": False, "applied": False, "error": f"Delegation '{delegation_id}' has already been applied."}

        if record.get("discarded"):
            return {"ok": False, "applied": False, "error": f"Delegation '{delegation_id}' has been discarded."}

        sandbox_path = Path(record.get("sandbox_path", ""))
        if not sandbox_path.is_dir():
            return {"ok": False, "applied": False, "error": f"Sandbox directory {sandbox_path} does not exist."}

        changed_files = record.get("changed_files", {})
        added = changed_files.get("added", [])
        modified = changed_files.get("modified", [])
        deleted = changed_files.get("deleted", [])

        # Verify all changes are strictly within allowed write roots before touching real tree
        allowed_normalized = [r.replace("\\", "/").strip("/") for r in self.sandbox_manager.allowed_roots]
        for fpath in added + modified + deleted:
            norm_f = fpath.replace("\\", "/").strip("/")
            if not any(norm_f == root or norm_f.startswith(f"{root}/") for root in allowed_normalized):
                return {
                    "ok": False,
                    "applied": False,
                    "error": f"Change in '{fpath}' is outside allowed roots; application aborted.",
                }

        # Backup files from real tree for potential rollback
        backups: dict[str, bytes | None] = {}
        for fpath in added:
            real_file = self.workspace / fpath
            backups[fpath] = real_file.read_bytes() if real_file.is_file() else None

        for fpath in modified + deleted:
            real_file = self.workspace / fpath
            backups[fpath] = real_file.read_bytes() if real_file.is_file() else None

        def rollback() -> None:
            for rel_str, orig_content in backups.items():
                target = self.workspace / rel_str
                if orig_content is None:
                    target.unlink(missing_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(orig_content)

        # Apply changes from sandbox
        try:
            for fpath in added + modified:
                src = sandbox_path / fpath
                dst = self.workspace / fpath
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)

            for fpath in deleted:
                dst = self.workspace / fpath
                dst.unlink(missing_ok=True)
        except Exception as exc:
            rollback()
            return {"ok": False, "applied": False, "error": f"File copy error during apply: {exc}; rolled back."}

        # Re-run acceptance check against real tree
        check_cmd = record.get("acceptance_check", "")
        if check_cmd:
            try:
                res = subprocess.run(
                    check_cmd,
                    cwd=str(self.workspace),
                    capture_output=True,
                    text=True,
                    timeout=DEFAULT_CHECK_TIMEOUT_SECONDS,
                    shell=True,
                )
                check_out = (res.stdout or "") + "\n" + (res.stderr or "")
                if res.returncode != 0:
                    rollback()
                    logger.warning("Acceptance check failed against real tree; changes rolled back.")
                    try:
                        self._ensure_model_decisions().record_build_outcome(
                            task_id=delegation_id,
                            route="opencode",
                            result="failed",
                            notes="Acceptance check failed against real tree; changes rolled back.",
                            acceptance_passed=False,
                            duration=float(record.get("duration_seconds", 0.0) or 0.0),
                            retries=max(0, len(record.get("providers_tried", [])) - 1),
                            provider=record.get("provider_used"),
                            model=record.get("model_used"),
                        )
                    except Exception as exc:
                        logger.warning("Failed to record build outcome on apply failure: %s", exc)
                    return {
                        "ok": False,
                        "applied": False,
                        "error": "Acceptance check failed against real tree; changes rolled back.",
                        "acceptance_output": _tail(check_out),
                    }
            except Exception as exc:
                rollback()
                try:
                    self._ensure_model_decisions().record_build_outcome(
                        task_id=delegation_id,
                        route="opencode",
                        result="failed",
                        notes=f"Acceptance check error against real tree: {exc}; changes rolled back.",
                        acceptance_passed=False,
                        duration=float(record.get("duration_seconds", 0.0) or 0.0),
                        retries=max(0, len(record.get("providers_tried", [])) - 1),
                        provider=record.get("provider_used"),
                        model=record.get("model_used"),
                    )
                except Exception:
                    pass
                return {
                    "ok": False,
                    "applied": False,
                    "error": f"Acceptance check error against real tree: {exc}; changes rolled back.",
                }

        # Mark delegation as applied
        record["applied"] = True
        record["applied_at"] = datetime.now(timezone.utc).isoformat()
        self._save_delegation(record)

        try:
            self._ensure_model_decisions().record_build_outcome(
                task_id=delegation_id,
                route="opencode",
                result="accepted",
                notes="Delegation changes applied and verified against real tree.",
                acceptance_passed=True,
                duration=float(record.get("duration_seconds", 0.0) or 0.0),
                retries=max(0, len(record.get("providers_tried", [])) - 1),
                provider=record.get("provider_used"),
                model=record.get("model_used"),
            )
        except Exception as exc:
            logger.warning("Failed to record build outcome on apply: %s", exc)

        return {
            "ok": True,
            "applied": True,
            "delegation_id": delegation_id,
            "changed_files": changed_files,
            "message": "Delegation changes applied and verified against real tree.",
        }

    def discard_delegation(self, delegation_id: str) -> dict[str, Any]:
        """Delete sandbox and mark delegation record as discarded."""
        record = self.get_delegation(delegation_id)
        if not record:
            return {"ok": False, "error": f"Delegation '{delegation_id}' not found."}

        sandbox_path = Path(record.get("sandbox_path", ""))
        if sandbox_path.is_dir():
            shutil.rmtree(sandbox_path, ignore_errors=True)

        record["discarded"] = True
        record["discarded_at"] = datetime.now(timezone.utc).isoformat()
        self._save_delegation(record)

        try:
            self._ensure_model_decisions().record_build_outcome(
                task_id=delegation_id,
                route="opencode",
                result="abandoned",
                notes="Delegation discarded by agent.",
                acceptance_passed=False,
                duration=float(record.get("duration_seconds", 0.0) or 0.0),
                retries=max(0, len(record.get("providers_tried", [])) - 1),
                provider=record.get("provider_used"),
                model=record.get("model_used"),
            )
        except Exception as exc:
            logger.warning("Failed to record build outcome on discard: %s", exc)

        return {
            "ok": True,
            "discarded": True,
            "delegation_id": delegation_id,
        }
