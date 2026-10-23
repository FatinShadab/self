"""Opencode delegation wrapper coordinator (facade)."""
from __future__ import annotations

import logging
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from agent.opencode.delegation.application import (
    apply_delegation_to_repo,
    discard_delegation_from_repo,
)
from agent.opencode.delegation.execution import execute_candidate_attempts
from agent.opencode.delegation.provider_resolution import (
    is_opencode_installed,
    load_configured_models,
    resolve_provider_candidates,
)
from agent.opencode.delegation.records import (
    ensure_delegations_file,
    get_delegation_record,
    read_delegations,
    save_delegation_record,
    tail_text,
    write_delegations_atomic,
)
from agent.opencode.sandbox import SandboxManager, build_opencode_env
from agent.opencode.status import OpencodeStatusTracker

logger = logging.getLogger("agent.opencode.wrapper")

DEFAULT_TIMEOUT_SECONDS = 1800  # 30 minutes
DEFAULT_CHECK_TIMEOUT_SECONDS = 600  # 10 minutes

_tail = tail_text


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

        self.status_tracker = OpencodeStatusTracker(
            workspace=self.workspace,
            config_path=self.config_path,
            binary_path=self.binary_path,
            runner_fn=self.runner_fn,
        )

        self.sandbox_manager = SandboxManager(
            repo_root=self.workspace,
            sandboxes_dir=sandboxes_dir,
            allowed_roots=allowed_roots,
        )

        state_dir = self.workspace / "state"
        self.delegations_path = state_dir / "opencode_delegations.json"
        self.delegations_lock = self.delegations_path.with_suffix(".lock")
        self._ensure_delegations_file()

    def _ensure_delegations_file(self) -> None:
        """Create empty delegations state file if absent."""
        ensure_delegations_file(self.delegations_path)

    def _read_delegations(self) -> dict[str, Any]:
        """Read delegations dict."""
        return read_delegations(self.delegations_path)

    def _write_delegations(self, data: dict[str, Any]) -> None:
        """Atomically persist delegations dict."""
        write_delegations_atomic(self.delegations_path, data)

    def get_delegation(self, delegation_id: str) -> dict[str, Any] | None:
        """Look up a recorded delegation by ID."""
        return get_delegation_record(self.delegations_path, self.delegations_lock, delegation_id)

    def _save_delegation(self, record: dict[str, Any]) -> None:
        """Save or update a delegation record."""
        save_delegation_record(self.delegations_path, self.delegations_lock, record)

    def _ensure_model_decisions(self) -> Any:
        """Lazily initialize ModelDecisions for recording build routes and outcomes."""
        if self.model_decisions is None:
            from agent.helper_models.model_decisions import ModelDecisions
            from agent.infra.event_log import EventLogger

            logger_inst = EventLogger(self.workspace / "logs" / "actions.jsonl")
            self.model_decisions = ModelDecisions(self.workspace, logger_inst, None, None, "delegation")
        return self.model_decisions

    def is_installed(self) -> bool:
        """Check if opencode executable is present and accessible."""
        return is_opencode_installed(self.binary_path)

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
        return load_configured_models(self.config_path)

    def _resolve_provider_candidates(
        self, requested_model: str | None, usability_providers: dict[str, Any]
    ) -> list[tuple[str, str | None]]:
        """Order candidate (provider, model) pairs according to usability."""
        return resolve_provider_candidates(
            requested_model=requested_model,
            usability_providers=usability_providers,
            configured_models=self._load_configured_models(),
        )

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

        if not route_reasons or not str(route_reasons).strip():
            return {
                "ok": False,
                "status": "error",
                "error": "route_reasons is required free text explaining why Self chose to delegate.",
            }

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

        try:
            self.sandbox_manager.cleanup_old_sandboxes()
        except Exception as exc:
            logger.warning("Sandbox cleanup warning: %s", exc)

        u = self.status_tracker.usability()
        for pname, pdata in u["providers"].items():
            if pdata.get("state") == "probe_due":
                logger.info("Provider %s is probe_due; running health probe.", pname)
                self.status_tracker.probe(pname)

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

        delegation_id = uuid.uuid4().hex[:12]
        sandbox_path, initial_manifest = self.sandbox_manager.create_sandbox(delegation_id)

        (
            opencode_success,
            chosen_provider,
            chosen_model,
            providers_tried,
            opencode_log,
            isolation_used,
            last_failure_category,
        ) = execute_candidate_attempts(
            binary_path=self.binary_path,
            sandbox_manager=self.sandbox_manager,
            status_tracker=self.status_tracker,
            sandbox_path=sandbox_path,
            candidates=candidates,
            target_dirs=target_dirs,
            acceptance_check=acceptance_check,
            spec=spec,
            timeout=timeout,
        )

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
        """Apply a completed delegation's changes to the real repository."""
        record = self.get_delegation(delegation_id)
        return apply_delegation_to_repo(
            workspace=self.workspace,
            record=record,
            allowed_roots=self.sandbox_manager.allowed_roots,
            delegation_id=delegation_id,
            save_record_fn=self._save_delegation,
            record_outcome_fn=self._ensure_model_decisions().record_build_outcome,
            check_timeout=DEFAULT_CHECK_TIMEOUT_SECONDS,
        )

    def discard_delegation(self, delegation_id: str) -> dict[str, Any]:
        """Delete sandbox and mark delegation record as discarded."""
        record = self.get_delegation(delegation_id)
        return discard_delegation_from_repo(
            record=record,
            delegation_id=delegation_id,
            save_record_fn=self._save_delegation,
            record_outcome_fn=self._ensure_model_decisions().record_build_outcome,
        )


__all__ = [
    "OpencodeDelegator",
    "DEFAULT_TIMEOUT_SECONDS",
    "DEFAULT_CHECK_TIMEOUT_SECONDS",
    "_tail",
]
