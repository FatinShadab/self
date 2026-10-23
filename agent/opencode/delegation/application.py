"""Applying and discarding delegation changes against the real repository."""
from __future__ import annotations

import logging
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from agent.opencode.delegation.records import tail_text

logger = logging.getLogger("agent.opencode.delegation.application")


def apply_delegation_to_repo(
    workspace: Path,
    record: dict[str, Any] | None,
    allowed_roots: list[str],
    delegation_id: str,
    save_record_fn: Callable[[dict[str, Any]], None],
    record_outcome_fn: Callable[..., None],
    check_timeout: float = 600.0,
) -> dict[str, Any]:
    """Apply a completed delegation's changes to the real repository with rollback protection."""
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

    allowed_normalized = [r.replace("\\", "/").strip("/") for r in allowed_roots]
    for fpath in added + modified + deleted:
        norm_f = fpath.replace("\\", "/").strip("/")
        if not any(norm_f == root or norm_f.startswith(f"{root}/") for root in allowed_normalized):
            return {
                "ok": False,
                "applied": False,
                "error": f"Change in '{fpath}' is outside allowed roots; application aborted.",
            }

    backups: dict[str, bytes | None] = {}
    for fpath in added:
        real_file = workspace / fpath
        backups[fpath] = real_file.read_bytes() if real_file.is_file() else None

    for fpath in modified + deleted:
        real_file = workspace / fpath
        backups[fpath] = real_file.read_bytes() if real_file.is_file() else None

    def rollback() -> None:
        for rel_str, orig_content in backups.items():
            target = workspace / rel_str
            if orig_content is None:
                target.unlink(missing_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(orig_content)

    try:
        for fpath in added + modified:
            src = sandbox_path / fpath
            dst = workspace / fpath
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

        for fpath in deleted:
            dst = workspace / fpath
            dst.unlink(missing_ok=True)
    except Exception as exc:
        rollback()
        return {"ok": False, "applied": False, "error": f"File copy error during apply: {exc}; rolled back."}

    check_cmd = record.get("acceptance_check", "")
    if check_cmd:
        try:
            res = subprocess.run(
                check_cmd,
                cwd=str(workspace),
                capture_output=True,
                text=True,
                timeout=check_timeout,
                shell=True,
            )
            check_out = (res.stdout or "") + "\n" + (res.stderr or "")
            if res.returncode != 0:
                rollback()
                logger.warning("Acceptance check failed against real tree; changes rolled back.")
                try:
                    record_outcome_fn(
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
                    "acceptance_output": tail_text(check_out),
                }
        except Exception as exc:
            rollback()
            try:
                record_outcome_fn(
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

    record["applied"] = True
    record["applied_at"] = datetime.now(timezone.utc).isoformat()
    save_record_fn(record)

    try:
        record_outcome_fn(
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


def discard_delegation_from_repo(
    record: dict[str, Any] | None,
    delegation_id: str,
    save_record_fn: Callable[[dict[str, Any]], None],
    record_outcome_fn: Callable[..., None],
) -> dict[str, Any]:
    """Delete sandbox and mark delegation record as discarded."""
    if not record:
        return {"ok": False, "error": f"Delegation '{delegation_id}' not found."}

    sandbox_path = Path(record.get("sandbox_path", ""))
    if sandbox_path.is_dir():
        shutil.rmtree(sandbox_path, ignore_errors=True)

    record["discarded"] = True
    record["discarded_at"] = datetime.now(timezone.utc).isoformat()
    save_record_fn(record)

    try:
        record_outcome_fn(
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
