"""Durable, bounded observations about configured primary and helper models."""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.infra.event_log import EventLogger
from agent.infra.file_lock import locked_file


MAX_MODELS = 32
MAX_NAME_CHARS = 160
MAX_ASSESSMENT_CHARS = 2_000
MAX_EVIDENCE_CHARS = 1_000
MAX_NOTES_CHARS = 1_000
MAX_COUNTER = 1_000_000_000
MAX_FILE_BYTES = 1_000_000
MAX_PROBES_PER_SESSION = 2
PROBE_COOLDOWN_SECONDS = 3_600
PROBE_FORMAT_VERSION = 2
LEGACY_PROBE_INVALIDATION_REASON = "Earlier probe output caps did not account for hidden thinking or provider truncation."
RATING_CATEGORIES = ("reasoning", "code", "instruction_following", "summarization", "json_output")
RATING_VALUES = {"low", "medium", "high", "unknown"}


def _env_limit(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        return max(minimum, min(maximum, int(os.getenv(name, str(default)))))
    except ValueError:
        return default


class ModelRegistry:
    """Track configured models, assessments, ratings, and measured use."""

    def __init__(self, workspace: str | Path, logger: EventLogger,
                 base_model: str, available_models: list[str]) -> None:
        self.path = Path(workspace) / "state" / "models.json"
        self.lock_path = self.path.with_suffix(".lock")
        self.logger = logger
        names = list(dict.fromkeys([base_model, *available_models]))
        if not base_model or len(names) > MAX_MODELS or any(
            not name or len(name) > MAX_NAME_CHARS for name in names
        ):
            raise ValueError("Configured model list is empty, too large, or contains an invalid name")
        self.base_model = base_model
        self.names = names
        self.probe_cooldown_seconds = _env_limit(
            "SELF_PROBE_COOLDOWN_SECONDS", PROBE_COOLDOWN_SECONDS, 0, 86_400)
        self.probes_per_model_per_session = _env_limit(
            "SELF_PROBES_PER_MODEL_PER_SESSION", MAX_PROBES_PER_SESSION, 1, 20)
        self._initialize()

    def _blank(self, name: str) -> dict[str, Any]:
        return {
            "name": name,
            "role": "base" if name == self.base_model else "helper",
            "status": "configured",
            "status_message": "",
            "last_failure_at": None,
            "agent_assessment": "",
            "assessment_evidence": "",
            "ratings": None,
            "ratings_at": None,
            "measured_stats": {"calls": 0, "failures": 0, "latency_ms_total": 0,
                               "latency_ms_min": None, "latency_ms_max": None,
                               "consecutive_failures": 0, "probe_passes": 0,
                               "probe_failures": 0, "probe_inconclusive": 0},
            "notes": "",
            "probe_history": [],
            "research": {"status": "not_checked", "source_url": None,
                         "last_checked": None, "last_verified": None, "facts": [],
                         "context_window": None, "pricing": None,
                         "speed": None, "strengths": None},
        }

    def _locked(self):
        return locked_file(self.lock_path)

    def _read(self) -> dict[str, Any]:
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                raw = handle.read(MAX_FILE_BYTES + 1)
            if len(raw) > MAX_FILE_BYTES:
                raise ValueError("Model registry exceeds its size limit")
            value = json.loads(raw)
            if isinstance(value, dict) and isinstance(value.get("models"), list):
                return value
        except (OSError, ValueError):
            pass
        return {"schema_version": 1, "base_model": self.base_model, "models": []}

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".models-{uuid.uuid4().hex}.tmp")
        try:
            content = json.dumps(self.logger.redactor.value(data), ensure_ascii=False, indent=2) + "\n"
            if len(content.encode("utf-8")) > MAX_FILE_BYTES:
                raise ValueError("Model registry exceeds its size limit")
            temporary.write_text(content, encoding="utf-8")
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def _initialize(self) -> None:
        with self._locked():
            prior = self._read()
            old_probe_format = int(prior.get("probe_format_version", 1) or 1)
            existing = {entry.get("name"): entry for entry in prior["models"]
                        if isinstance(entry, dict) and isinstance(entry.get("name"), str)}
            entries = []
            for name in self.names:
                entry = self._blank(name)
                old = existing.get(name, {})
                for field, limit in (("agent_assessment", MAX_ASSESSMENT_CHARS),
                                     ("assessment_evidence", MAX_EVIDENCE_CHARS),
                                     ("notes", MAX_NOTES_CHARS)):
                    entry[field] = str(old.get(field, ""))[:limit]
                prior_ratings = old.get("ratings")
                if (isinstance(prior_ratings, dict) and
                    set(prior_ratings) == set(RATING_CATEGORIES) and
                    all(value in RATING_VALUES for value in prior_ratings.values())):
                    entry["ratings"] = prior_ratings
                    entry["ratings_at"] = old.get("ratings_at")
                if old.get("status") in {"configured", "reachable", "last_call_failed", "not_found"}:
                    entry["status"] = old["status"]
                if old.get("status") == "disabled":
                    entry["status"] = "disabled"
                entry["status_message"] = str(old.get("status_message", ""))[:300]
                entry["last_failure_at"] = old.get("last_failure_at")
                if isinstance(old.get("probe_history"), list):
                    entry["probe_history"] = [
                        {"id": str(item.get("id", ""))[:32],
                         "session_id": str(item.get("session_id", ""))[:80],
                         "at": float(item.get("at", 0) or 0),
                         "status": str(item.get("status", ""))[:20],
                         "invalidated": old_probe_format < PROBE_FORMAT_VERSION or bool(item.get("invalidated", False)),
                         "invalidation_reason": (LEGACY_PROBE_INVALIDATION_REASON if old_probe_format < PROBE_FORMAT_VERSION
                                                 else str(item.get("invalidation_reason", ""))[:300])}
                        for item in old["probe_history"][-32:] if isinstance(item, dict)
                    ]
                invalidated_ids = {item["id"] for item in entry["probe_history"] if item["invalidated"]}
                if any(f"probe:{probe_id}" in entry["assessment_evidence"] for probe_id in invalidated_ids):
                    entry["agent_assessment"] = ""
                    entry["assessment_evidence"] = ""
                    entry["ratings"] = None
                    entry["ratings_at"] = None
                if isinstance(old.get("research"), dict):
                    research = old["research"]
                    entry["research"] = {
                        "status": str(research.get("status", "not_checked"))[:40],
                        "source_url": str(research["source_url"])[:500] if research.get("source_url") else None,
                        "last_checked": str(research["last_checked"])[:80] if research.get("last_checked") else None,
                        "last_verified": str(research["last_verified"])[:80] if research.get("last_verified") else None,
                        "facts": [
                            {"field": str(item.get("field", ""))[:80],
                             "value": str(item.get("value", ""))[:500],
                             "excerpt": str(item.get("excerpt", ""))[:500],
                             "source_url": str(item.get("source_url", ""))[:500],
                             "last_verified": str(item.get("last_verified", ""))[:80]}
                            for item in research.get("facts", [])[:8] if isinstance(item, dict)
                        ],
                        "context_window": None,
                        "pricing": None,
                        "speed": None,
                        "strengths": None,
                    }
                stats = old.get("measured_stats", {})
                if isinstance(stats, dict):
                    for field in ("calls", "failures", "latency_ms_total", "consecutive_failures",
                                  "probe_passes", "probe_failures", "probe_inconclusive"):
                        entry["measured_stats"][field] = min(
                            MAX_COUNTER, max(0, int(stats.get(field, 0) or 0)))
                    if "consecutive_failures" not in stats and entry["status"] == "last_call_failed":
                        entry["measured_stats"]["consecutive_failures"] = 1
                    for field in ("latency_ms_min", "latency_ms_max"):
                        value = stats.get(field)
                        entry["measured_stats"][field] = (
                            min(MAX_COUNTER, max(0, int(value))) if value is not None else None
                        )
                entries.append(entry)
            data = {"schema_version": 1, "probe_format_version": PROBE_FORMAT_VERSION,
                    "base_model": self.base_model, "models": entries}
            if data != prior:
                self._write(data)

    def list_models(self) -> dict[str, Any]:
        """Return all configured models with assessments and measured stats."""
        with self._locked():
            return self.logger.redactor.value(self._read())

    def get_model(self, name: str) -> dict[str, Any]:
        """Return one configured model by name, if present."""
        if name not in self.names:
            raise ValueError("Model is not configured")
        with self._locked():
            return self.logger.redactor.value(next(
                item for item in self._read()["models"] if item["name"] == name))

    def record_model_assessment(self, name: str, assessment: str, evidence: str,
                                ratings: dict[str, str] | None = None) -> dict[str, Any]:
        """Persist the agent's assessment and category ratings for a model."""
        if name not in self.names:
            raise ValueError("Model is not configured")
        if not isinstance(assessment, str) or not assessment.strip():
            raise ValueError("Assessment must be non-empty")
        if not isinstance(evidence, str) or not evidence.strip():
            raise ValueError("Evidence reference must be non-empty")
        if len(assessment) > MAX_ASSESSMENT_CHARS or len(evidence) > MAX_EVIDENCE_CHARS:
            raise ValueError("Assessment or evidence reference exceeds its size limit")
        if ratings is not None and (not isinstance(ratings, dict) or
                                    set(ratings) != set(RATING_CATEGORIES) or
                                    any(not isinstance(value, str) or value not in RATING_VALUES
                                        for value in ratings.values())):
            raise ValueError("Ratings must cover all five categories with low, medium, high, or unknown")
        probe_ids = re.findall(r"\bprobe:([0-9a-f]{32})\b", evidence)
        if "probe:" in evidence and not probe_ids:
            raise ValueError("Assessment contains an invalid probe reference")
        with self._locked():
            data = self._read()
            entry = next(item for item in data["models"] if item["name"] == name)
            for probe_id in probe_ids:
                if not any(item.get("id") == probe_id and not item.get("invalidated")
                           for item in entry["probe_history"]):
                    raise ValueError("Assessment cites an unknown probe id")
            entry["agent_assessment"] = self.logger.redactor.text(assessment.strip())
            entry["assessment_evidence"] = self.logger.redactor.text(evidence.strip())
            if ratings is not None:
                entry["ratings"] = dict(ratings)
                entry["ratings_at"] = datetime.now(timezone.utc).isoformat()
            self._write(data)
        self.logger.log("model_assessment_recorded", name=name, evidence=entry["assessment_evidence"])
        return {"ok": True, "name": name, "assessment": entry["agent_assessment"],
                "evidence": entry["assessment_evidence"],
                "ratings": entry["ratings"], "ratings_at": entry["ratings_at"]}

    def record_probe_outcome(self, name: str, outcome: str) -> None:
        """Update a model's status and probe history from observed results."""
        if outcome not in {"passed", "failed", "inconclusive"}:
            raise ValueError("Invalid probe outcome")
        with self._locked():
            data = self._read()
            entry = next(item for item in data["models"] if item["name"] == name)
            stats = entry["measured_stats"]
            field = {"passed": "probe_passes", "failed": "probe_failures",
                     "inconclusive": "probe_inconclusive"}[outcome]
            stats[field] = min(MAX_COUNTER, stats[field] + 1)
            if outcome == "failed":
                stats["failures"] = min(MAX_COUNTER, stats["failures"] + 1)
            self._write(data)

    def record_call(self, name: str, *, failed: bool, latency_ms: int,
                    not_found: bool = False) -> None:
        """Update measured call, token, latency, and failure statistics."""
        if name not in self.names:
            return
        latency = min(MAX_COUNTER, max(0, int(latency_ms)))
        with self._locked():
            data = self._read()
            entry = next(item for item in data["models"] if item["name"] == name)
            stats = entry["measured_stats"]
            stats["calls"] = min(MAX_COUNTER, stats["calls"] + 1)
            stats["failures"] = min(MAX_COUNTER, stats["failures"] + int(failed))
            stats["consecutive_failures"] = (min(MAX_COUNTER, stats["consecutive_failures"] + 1)
                                             if failed else 0)
            stats["latency_ms_total"] = min(MAX_COUNTER, stats["latency_ms_total"] + latency)
            stats["latency_ms_min"] = latency if stats["latency_ms_min"] is None else min(stats["latency_ms_min"], latency)
            stats["latency_ms_max"] = latency if stats["latency_ms_max"] is None else max(stats["latency_ms_max"], latency)
            entry["status"] = "not_found" if not_found else "last_call_failed" if failed else "reachable"
            entry["status_message"] = (
                "The endpoint did not recognize this configured model name." if not_found else "")
            entry["last_failure_at"] = time.time() if failed else None
            self._write(data)

    def mark_not_found(self, name: str) -> None:
        """Mark a configured model as unavailable after a failed lookup."""
        with self._locked():
            data = self._read()
            entry = next(item for item in data["models"] if item["name"] == name)
            entry["status"] = "not_found"
            entry["status_message"] = "The endpoint did not recognize this configured model name."
            entry["last_failure_at"] = time.time()
            self._write(data)

    def record_output_failure(self, name: str) -> None:
        """Count an unusable response already counted as a successful API call."""
        with self._locked():
            data = self._read()
            entry = next(item for item in data["models"] if item["name"] == name)
            stats = entry["measured_stats"]
            stats["failures"] = min(MAX_COUNTER, stats["failures"] + 1)
            stats["consecutive_failures"] = min(MAX_COUNTER, stats["consecutive_failures"] + 1)
            entry["status"] = "last_call_failed"
            entry["status_message"] = "The last response was empty or truncated."
            entry["last_failure_at"] = time.time()
            self._write(data)

    def begin_probe(self, name: str, session_id: str, *, now: float | None = None) -> str:
        """Mark a model probe as in progress."""
        if name not in self.names:
            raise ValueError("Model is not configured")
        if not session_id or len(session_id) > 80:
            raise ValueError("Probe session id is invalid")
        when = time.time() if now is None else now
        with self._locked():
            data = self._read()
            entry = next(item for item in data["models"] if item["name"] == name)
            if entry["status"] == "disabled":
                raise ValueError("Model is disabled")
            history = entry["probe_history"]
            valid_history = [item for item in history if not item.get("invalidated")]
            if sum(item.get("session_id") == session_id for item in valid_history) >= self.probes_per_model_per_session:
                raise ValueError("Per-session probe cap reached")
            if valid_history and when - float(valid_history[-1].get("at", 0)) < self.probe_cooldown_seconds:
                raise ValueError("Model probe cooldown is active")
            probe_id = uuid.uuid4().hex
            history.append({"id": probe_id, "session_id": session_id,
                            "at": when, "status": "running", "invalidated": False,
                            "invalidation_reason": ""})
            entry["probe_history"] = history[-32:]
            self._write(data)
        self.logger.log("model_probe_started", name=name, probe_id=probe_id, session_id=session_id)
        return probe_id

    def finish_probe(self, name: str, probe_id: str, *, failed: bool,
                     inconclusive: bool = False) -> None:
        """Store the final status of a completed model probe."""
        with self._locked():
            data = self._read()
            entry = next(item for item in data["models"] if item["name"] == name)
            record = next(item for item in entry["probe_history"] if item["id"] == probe_id)
            record["status"] = "failed" if failed else "inconclusive" if inconclusive else "completed"
            self._write(data)

    def record_research(self, name: str, *, status: str, source_url: str | None,
                        facts: list[dict[str, Any]]) -> dict[str, Any]:
        """Store official research evidence for a configured model."""
        if name not in self.names:
            raise ValueError("Model is not configured")
        checked = datetime.now(timezone.utc).isoformat()
        safe_facts = []
        for fact in facts[:8]:
            safe_facts.append({"field": str(fact["field"])[:80],
                               "value": self.logger.redactor.text(str(fact["value"]))[:500],
                               "excerpt": self.logger.redactor.text(str(fact["excerpt"]))[:500],
                               "source_url": source_url, "last_verified": checked})
        with self._locked():
            data = self._read()
            entry = next(item for item in data["models"] if item["name"] == name)
            entry["research"] = {"status": status, "source_url": source_url,
                                 "last_checked": checked,
                                 "last_verified": checked if safe_facts else None,
                                 "facts": safe_facts, "context_window": None,
                                 "pricing": None, "speed": None,
                                 "strengths": None}
            self._write(data)
        self.logger.log("model_research_recorded", name=name, status=status,
                        source_url=source_url, fact_count=len(safe_facts))
        return {"ok": True, "name": name, "research": entry["research"]}
