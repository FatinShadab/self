"""Core patch proposal persistence and review queue management."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from agent.identity.store.schema import safe_text
from agent.infra.event_log import EventLogger


def list_proposed_patches(proposals_path: Path) -> list[Path]:
    """Return proposed source changes sorted newest first."""
    try:
        return sorted(proposals_path.glob("*.patch"), key=lambda path: path.name, reverse=True)
    except OSError:
        return []


def save_proposed_core_patch(
    proposals_path: Path,
    log_change_fn: Callable[[str, str, str], None],
    logger: EventLogger,
    redactor: Any,
    name: str,
    diff: str,
    reasoning: str,
    session_id: str = "",
) -> dict[str, Any]:
    """Save a proposed core patch file for human host-side review."""
    slug = re.sub(r"[^a-z0-9]+", "-", safe_text(name, redactor, 100).lower()).strip("-") or "core-change"
    safe_diff = redactor.known(diff) if hasattr(redactor, "known") else diff
    safe_reasoning = safe_text(reasoning, redactor, 3_000)
    if not safe_diff.strip():
        raise ValueError("A proposed core patch needs a non-empty diff.")
    if len(safe_diff.encode("utf-8")) > 100_000:
        raise ValueError("Proposed core patch is too large (100 KB limit).")

    proposals_path.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = proposals_path / f"{timestamp}-{slug}.patch"
    suffix = 1
    while path.exists():
        path = proposals_path / f"{timestamp}-{slug}-{suffix}.patch"
        suffix += 1

    session_label = safe_text(session_id, redactor, 120) or "not yet assigned"
    proposal = (
        f"# SELF proposed core patch — {timestamp}\n"
        f"# Session: {session_label}\n"
        f"# Reasoning: {safe_reasoning}\n"
        "# This proposal has not been applied. It requires human review; apply it from the host only if approved.\n\n"
        f"{safe_diff.rstrip()}\n"
    )
    redacted_proposal = redactor.text(proposal) if hasattr(redactor, "text") else proposal
    path.write_text(redacted_proposal, encoding="utf-8")
    log_change_fn(
        f"Proposed core patch {path.name}.",
        safe_reasoning or "The agent identified a possible core improvement for human review.",
        session_id,
    )
    logger.log(
        "core_patch_proposed",
        path=str(path),
        name=slug,
        diff_chars=len(safe_diff),
    )
    return {"ok": True, "status": "human_review_required", "path": str(path), "applied": False}
