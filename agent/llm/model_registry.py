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
SCHEMA_VERSION = 3
PROBE_FORMAT_VERSION = 2
LEGACY_PROBE_INVALIDATION_REASON = "Earlier probe output caps did not account for hidden thinking or provider truncation."
RATING_CATEGORIES = ("reasoning", "code", "instruction_following", "summarization", "json_output")
RATING_VALUES = {"low", "medium", "high", "unknown"}


def _env_limit(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        return max(minimum, min(maximum, int(os.getenv(name, str(default)))))
    except ValueError:
        return default


def get_helpers_needing_evaluation(data_or_registry: dict[str, Any] | ModelRegistry) -> list[str]:
    """Compute helpers that need evaluation from models.json data or a ModelRegistry.

    A helper needs evaluation if it has no probe in probe_history at the current probe_format_version,
    or its latest probe is invalidated, or research.status is not_checked, or it has no agent_assessment.
    """
    if hasattr(data_or_registry, "list_models"):
        data = data_or_registry.list_models()
    elif isinstance(data_or_registry, dict):
        data = data_or_registry
    else:
        return []
    format_version = int(data.get("probe_format_version", PROBE_FORMAT_VERSION) or PROBE_FORMAT_VERSION)
    needing: list[str] = []
    for model in data.get("models", []):
        if not isinstance(model, dict):
            continue
        if model.get("role") == "base" or model.get("status") == "disabled" or model.get("configured") is False:
            continue
        name = model.get("name")
        if not name:
            continue
        history = [item for item in model.get("probe_history", []) if isinstance(item, dict)]
        has_current_probe = any(
            not item.get("invalidated") and int(item.get("format_version", format_version) or format_version) == format_version
            for item in history
        )
        latest_invalidated = bool(history and history[-1].get("invalidated"))
        research = model.get("research", {})
        research_status = research.get("status", "not_checked") if isinstance(research, dict) else "not_checked"
        has_assessment = bool(str(model.get("agent_assessment", "")).strip())

        if not has_current_probe or latest_invalidated or research_status == "not_checked" or not has_assessment:
            needing.append(name)
    return needing


DEFAULT_MODEL_OUTPUT_CEILING = 32_768


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
        self._logged_assumed_ceilings: set[str] = set()
        self.probe_cooldown_seconds = _env_limit(
            "SELF_PROBE_COOLDOWN_SECONDS", PROBE_COOLDOWN_SECONDS, 0, 86_400)
        self.probes_per_model_per_session = _env_limit(
            "SELF_PROBES_PER_MODEL_PER_SESSION", MAX_PROBES_PER_SESSION, 1, 20)
        self._initialize()

    def _blank(self, name: str) -> dict[str, Any]:
        return {
            "name": name,
            "role": "base" if name == self.base_model else "helper",
            "configured": True,
            "status": "configured",
            "status_message": "",
            "last_failure_at": None,
            "agent_assessment": "",
            "assessment_evidence": "",
            "ratings": None,
            "ratings_at": None,
            "measured_stats": {"calls": 0, "failures": 0, "truncated_calls": 0, "network_errors": 0,
                               "latency_ms_total": 0,
                               "latency_ms_min": None, "latency_ms_max": None,
                               "consecutive_failures": 0, "probe_passes": 0,
                               "probe_failures": 0, "probe_inconclusive": 0},
            "notes": "",
            "probe_history": [],
            "research": {"status": "not_checked", "status_message": "", "source_url": None,
                         "urls_tried": [],
                         "last_checked": None, "last_verified": None, "facts": [],
                         "total_params": None, "active_params": None,
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
        return {"schema_version": SCHEMA_VERSION, "probe_format_version": PROBE_FORMAT_VERSION,
                "base_model": self.base_model, "models": []}

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
                old = existing.pop(name, None)
                if old is not None:
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
                             "latency_ms": int(item["latency_ms"]) if item.get("latency_ms") is not None else None,
                             "format_version": int(item.get("format_version", old_probe_format) or old_probe_format),
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
                        facts_raw = [
                            {"field": str(item.get("field", ""))[:80],
                             "value": str(item.get("value", ""))[:500],
                             "excerpt": str(item.get("excerpt", ""))[:500],
                             "source_url": str(item.get("source_url", ""))[:500] if item.get("source_url") else None,
                             "origin": str(item.get("origin", "web"))[:20],
                             "verified": bool(item.get("verified", item.get("origin") != "model_knowledge")),
                             "last_verified": str(item.get("last_verified", ""))[:80] if item.get("last_verified") else None}
                            for item in research.get("facts", [])[:16]
                            if isinstance(item, dict) and item.get("field") != "model_name_mentioned"
                        ]
                        old_status = str(research.get("status", "not_checked"))[:40]
                        if old_status == "verified_mention":
                            status = "facts_found" if facts_raw else "fetched_no_model_fact"
                        else:
                            status = old_status
                        urls_tried = research.get("urls_tried")
                        if not isinstance(urls_tried, list):
                            urls_tried = [research["source_url"]] if research.get("source_url") else []

                        entry["research"] = {
                            "status": status,
                            "status_message": str(research.get("status_message", ""))[:300],
                            "source_url": str(research["source_url"])[:500] if research.get("source_url") else None,
                            "urls_tried": [str(u)[:500] for u in urls_tried][:10],
                            "last_checked": str(research["last_checked"])[:80] if research.get("last_checked") else None,
                            "last_verified": str(research["last_verified"])[:80] if research.get("last_verified") else None,
                            "facts": facts_raw,
                            "total_params": str(research.get("total_params", ""))[:40] if research.get("total_params") else None,
                            "active_params": str(research.get("active_params", ""))[:40] if research.get("active_params") else None,
                            "context_window": str(research.get("context_window", ""))[:40] if research.get("context_window") else None,
                            "pricing": str(research.get("pricing", ""))[:80] if research.get("pricing") else None,
                            "speed": str(research.get("speed", ""))[:40] if research.get("speed") else None,
                            "strengths": str(research.get("strengths", ""))[:120] if research.get("strengths") else None,
                        }
                    stats = old.get("measured_stats", {})
                    if isinstance(stats, dict):
                        for field in ("calls", "failures", "truncated_calls", "network_errors", "latency_ms_total", "consecutive_failures",
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
            for old_name, old_entry in existing.items():
                # Preserve renamed or discontinued model history without attaching to new entries
                preserved = dict(old_entry)
                preserved["configured"] = False
                preserved["status"] = "unconfigured"
                preserved["status_message"] = (
                    f"Model '{old_name}' is no longer configured in the registry; historical assessment and probes belong to this discontinued name."
                )
                entries.append(preserved)
            data = {"schema_version": SCHEMA_VERSION, "probe_format_version": PROBE_FORMAT_VERSION,
                    "base_model": self.base_model, "models": entries}
            if data != prior:
                self._write(data)

    def helpers_needing_evaluation(self) -> list[str]:
        """Return helper models needing evaluation."""
        return get_helpers_needing_evaluation(self)

    def get_output_cap(self, name: str, default_cap: int | None = None) -> int:
        """Return configured per-model output cap override if set, else registry ceiling, else 32768."""
        env_key = "SELF_OUTPUT_CAP_" + re.sub(r"[^A-Za-z0-9]", "_", name).upper()
        env_val = os.getenv(env_key)
        if env_val:
            try:
                val = int(env_val)
                if val > 0:
                    return val
            except ValueError:
                pass
        with self._locked():
            data = self._read()
            entry = next((item for item in data.get("models", []) if item.get("name") == name), None)
            if entry:
                cap = entry.get("output_cap") or entry.get("max_tokens")
                if isinstance(cap, int) and cap > 0:
                    return cap
        if default_cap is not None and default_cap > 0 and default_cap != 1024:
            return default_cap
        ceiling = int(os.getenv("SELF_DEFAULT_OUTPUT_CEILING", str(DEFAULT_MODEL_OUTPUT_CEILING)))
        if name not in self._logged_assumed_ceilings:
            self._logged_assumed_ceilings.add(name)
            self.logger.log("assumed_output_ceiling", model=name, ceiling=ceiling,
                            reason="Maximum output length not in registry or env; using assumed ceiling.")
        return ceiling

    def validate_model_name(self, name: str, *, helpers_only: bool = False) -> tuple[bool, str]:
        """Validate model name against registry with alias hints and helpers-only rule."""
        if not isinstance(name, str) or not name.strip():
            valid_names = sorted(n for n in self.names if not helpers_only or n != self.base_model)
            return False, f"Model name must be a non-empty string. Valid models are: {', '.join(valid_names)}."
        cleaned = name.strip()
        if helpers_only and cleaned == self.base_model:
            enabled_helpers = sorted(m["name"] for m in self.list_models()["models"]
                                     if m.get("configured", True) and m["role"] == "helper" and m["status"] != "disabled")
            return False, (
                f"The base model '{cleaned}' cannot be asked via ask_model. "
                f"ask_model is for helper models only. Enabled helper models are: {', '.join(enabled_helpers)}."
            )
        if cleaned not in self.names:
            valid_names = sorted(n for n in self.names if not helpers_only or n != self.base_model)
            alias_hint = ""
            if cleaned.endswith("-cloud") and cleaned[:-6] in self.names:
                alias_hint = f" Note: '{cleaned[:-6]}' is configured without the '-cloud' suffix; results will not be attached to '{cleaned[:-6]}'."
            elif f"{cleaned}-cloud" in self.names:
                alias_hint = f" Note: '{cleaned}-cloud' is configured with the '-cloud' suffix; results will not be attached to '{cleaned}-cloud'."
            return False, f"Model '{cleaned}' is not in the registry. Valid models are: {', '.join(valid_names)}.{alias_hint}"
        return True, ""

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
                                ratings: dict[str, str] | None = None,
                                facts: list[dict[str, Any]] | dict[str, Any] | None = None) -> dict[str, Any]:
        """Persist the agent's assessment, category ratings, and optional knowledge facts for a model."""
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
        if facts:
            self.record_facts(name, facts, origin="model_knowledge")
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

    def record_truncated_call(self, name: str) -> None:
        """Count a response that ended in max_tokens/truncation without marking clean success."""
        if name not in self.names:
            return
        with self._locked():
            data = self._read()
            entry = next((item for item in data["models"] if item["name"] == name), None)
            if entry is not None:
                stats = entry["measured_stats"]
                stats["truncated_calls"] = min(MAX_COUNTER, stats.get("truncated_calls", 0) + 1)
                self._write(data)

    def record_network_error(self, name: str, *, latency_ms: int = 0) -> None:
        """Record a transient network/connection error without counting it as a model failure."""
        if name not in self.names:
            return
        latency = min(MAX_COUNTER, max(0, int(latency_ms)))
        with self._locked():
            data = self._read()
            entry = next((item for item in data["models"] if item["name"] == name), None)
            if entry is not None:
                stats = entry["measured_stats"]
                stats["network_errors"] = min(MAX_COUNTER, stats.get("network_errors", 0) + 1)
                stats["calls"] = min(MAX_COUNTER, stats["calls"] + 1)
                stats["latency_ms_total"] = min(MAX_COUNTER, stats["latency_ms_total"] + latency)
                if stats["latency_ms_min"] is None:
                    stats["latency_ms_min"] = latency
                else:
                    stats["latency_ms_min"] = min(stats["latency_ms_min"], latency)
                stats["latency_ms_max"] = max(stats.get("latency_ms_max") or 0, latency)
                # Note: We do NOT increment failures or consecutive_failures, nor set status to last_call_failed
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
                            "at": when, "status": "running", "format_version": PROBE_FORMAT_VERSION,
                            "invalidated": False,
                            "invalidation_reason": ""})
            entry["probe_history"] = history[-32:]
            self._write(data)
        self.logger.log("model_probe_started", name=name, probe_id=probe_id, session_id=session_id)
        return probe_id

    def finish_probe(self, name: str, probe_id: str, *, failed: bool,
                     inconclusive: bool = False, latency_ms: int | None = None) -> None:
        """Store the final status of a completed model probe."""
        with self._locked():
            data = self._read()
            entry = next(item for item in data["models"] if item["name"] == name)
            record = next(item for item in entry["probe_history"] if item["id"] == probe_id)
            record["status"] = "failed" if failed else "inconclusive" if inconclusive else "completed"
            if latency_ms is not None:
                record["latency_ms"] = latency_ms
            self._write(data)

    def record_facts(self, name: str, facts: list[dict[str, Any]] | dict[str, Any],
                     *, origin: str = "model_knowledge") -> dict[str, Any]:
        """Store agent-supplied facts (e.g. from model knowledge, verified=False)."""
        if name not in self.names:
            raise ValueError("Model is not configured")
        facts_list: list[dict[str, Any]] = []
        if isinstance(facts, dict):
            for k, v in facts.items():
                if v is not None:
                    facts_list.append({"field": str(k), "value": str(v),
                                       "excerpt": f"agent model knowledge: {k}={v}"})
        elif isinstance(facts, list):
            for item in facts:
                if isinstance(item, dict) and item.get("field") and item.get("value") is not None:
                    facts_list.append({
                        "field": str(item["field"]),
                        "value": str(item["value"]),
                        "excerpt": str(item.get("excerpt", f"agent model knowledge: {item['field']}={item['value']}")),
                    })
        else:
            raise ValueError("Facts must be a list of objects or a key-value dictionary")

        is_model_knowledge = origin == "model_knowledge"
        verified = not is_model_knowledge
        with self._locked():
            data = self._read()
            entry = next(item for item in data["models"] if item["name"] == name)
            research = entry.setdefault("research", self._blank(name)["research"])
            existing_facts = list(research.get("facts", []))
            for f in facts_list:
                fld = f["field"][:80]
                val = self.logger.redactor.text(str(f["value"]))[:500]
                exc = self.logger.redactor.text(str(f["excerpt"]))[:500]
                fact_obj = {
                    "field": fld,
                    "value": val,
                    "excerpt": exc,
                    "source_url": None,
                    "origin": origin,
                    "verified": verified,
                    "last_verified": None,
                }
                idx = next((i for i, ef in enumerate(existing_facts)
                            if ef.get("field") == fld and ef.get("origin") == origin), None)
                if idx is not None:
                    existing_facts[idx] = fact_obj
                else:
                    existing_facts.append(fact_obj)

                if fld in {"total_params", "active_params", "context_window", "pricing", "speed", "strengths"}:
                    if not research.get(fld):
                        research[fld] = val[:40] if fld in {"total_params", "active_params", "context_window", "speed"} else val[:120]

            research["facts"] = existing_facts[:16]
            self._write(data)
        self.logger.log("model_facts_recorded", name=name, origin=origin, count=len(facts_list))
        return {"ok": True, "name": name, "facts": research["facts"]}

    def record_research(self, name: str, *, status: str, source_url: str | None,
                        facts: list[dict[str, Any]], status_message: str = "",
                        urls_tried: list[str] | None = None,
                        total_params: str | None = None, active_params: str | None = None,
                        context_window: str | None = None, pricing: str | None = None,
                        speed: str | None = None, strengths: str | None = None) -> dict[str, Any]:
        """Store official research evidence for a configured model."""
        if name not in self.names:
            raise ValueError("Model is not configured")
        checked = datetime.now(timezone.utc).isoformat()
        safe_facts = []
        for fact in facts[:16]:
            origin = str(fact.get("origin", "web"))[:20]
            is_model_knowledge = origin == "model_knowledge"
            verified = bool(fact.get("verified", not is_model_knowledge))
            safe_facts.append({"field": str(fact["field"])[:80],
                               "value": self.logger.redactor.text(str(fact["value"]))[:500],
                               "excerpt": self.logger.redactor.text(str(fact.get("excerpt", "")))[:500],
                               "source_url": fact.get("source_url") or (None if is_model_knowledge else source_url),
                               "origin": origin,
                               "verified": verified,
                               "last_verified": checked if verified else None})
        tried = [str(u)[:500] for u in urls_tried][:10] if urls_tried else ([source_url] if source_url else [])
        with self._locked():
            data = self._read()
            entry = next(item for item in data["models"] if item["name"] == name)
            entry["research"] = {
                "status": status,
                "status_message": str(status_message)[:300],
                "source_url": source_url,
                "urls_tried": tried,
                "last_checked": checked,
                "last_verified": checked if any(f["verified"] for f in safe_facts) else None,
                "facts": safe_facts,
                "total_params": str(total_params)[:40] if total_params else None,
                "active_params": str(active_params)[:40] if active_params else None,
                "context_window": str(context_window)[:40] if context_window else None,
                "pricing": str(pricing)[:80] if pricing else None,
                "speed": str(speed)[:40] if speed else None,
                "strengths": str(strengths)[:120] if strengths else None,
            }
            self._write(data)
        self.logger.log("model_research_recorded", name=name, status=status,
                        source_url=source_url, fact_count=len(safe_facts),
                        urls_tried=tried)
        return {"ok": True, "name": name, "research": entry["research"]}
