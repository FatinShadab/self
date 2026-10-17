"""Startup self-check for agent code version and plan store presence."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

from agent.infra.event_log import EventLogger
from agent.learning.plan import PlanStore


def compute_agent_source_hash(agent_root: str | Path | None = None) -> str:
    """Compute a deterministic SHA-256 hash over all .py files in agent/."""
    if agent_root is None:
        agent_root = Path(__file__).resolve().parent.parent
    else:
        agent_root = Path(agent_root)

    hasher = hashlib.sha256()
    py_files = sorted(agent_root.rglob("*.py"))
    for py_file in py_files:
        if "__pycache__" in py_file.parts:
            continue
        try:
            rel = py_file.relative_to(agent_root).as_posix()
            content = py_file.read_bytes()
            hasher.update(rel.encode("utf-8"))
            hasher.update(content)
        except OSError:
            continue
    return hasher.hexdigest()


def verify_startup_code_version(logger: EventLogger, agent_root: str | Path | None = None) -> dict[str, Any]:
    """Perform startup self-check, log code_version, and warn on suspected stale image."""
    try:
        source_hash = compute_agent_source_hash(agent_root)
    except Exception as exc:
        source_hash = f"error:{type(exc).__name__}"

    plan_store_present = PlanStore is not None

    logger.log("code_version", source_hash=source_hash, plan_store_present=plan_store_present)

    expected_hash = (os.getenv("HOST_AGENT_SOURCE_HASH") or os.getenv("SELF_EXPECTED_CODE_HASH") or "").strip().lower()
    stale_image = False
    if expected_hash and source_hash.lower() != expected_hash:
        stale_image = True
        logger.log(
            "stale_image_suspected",
            expected_hash=expected_hash,
            image_hash=source_hash,
        )
        logger.narrate(
            f"Warning: image source hash {source_hash[:8]} differs from expected host hash {expected_hash[:8]}. "
            "A rebuild may be required."
        )

    return {
        "source_hash": source_hash,
        "plan_store_present": plan_store_present,
        "stale_image_suspected": stale_image,
    }
