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
from agent.llm.registry import (
    DEFAULT_MODEL_OUTPUT_CEILING,
    LEGACY_PROBE_INVALIDATION_REASON,
    MAX_ASSESSMENT_CHARS,
    MAX_COUNTER,
    MAX_EVIDENCE_CHARS,
    MAX_FILE_BYTES,
    MAX_MODELS,
    MAX_NAME_CHARS,
    MAX_NOTES_CHARS,
    MAX_PROBES_PER_SESSION,
    PROBE_COOLDOWN_SECONDS,
    PROBE_FORMAT_VERSION,
    RATING_CATEGORIES,
    RATING_VALUES,
    SCHEMA_VERSION,
    env_limit as _env_limit,
    get_helpers_needing_evaluation,
)
from agent.llm.registry.initialization import blank_model_entry, initialize_registry_data
from agent.llm.registry.probes import (
    begin_probe_record,
    finish_probe_record,
    record_probe_outcome_stats,
)
from agent.llm.registry.research import record_facts_entry, record_research_entry
from agent.llm.registry.telemetry import (
    mark_not_found_status,
    record_call_stats,
    record_network_error_stats,
    record_output_failure_stats,
    record_truncated_call_stats,
)

__all__ = [
    "DEFAULT_MODEL_OUTPUT_CEILING",
    "LEGACY_PROBE_INVALIDATION_REASON",
    "MAX_ASSESSMENT_CHARS",
    "MAX_COUNTER",
    "MAX_EVIDENCE_CHARS",
    "MAX_FILE_BYTES",
    "MAX_MODELS",
    "MAX_NAME_CHARS",
    "MAX_NOTES_CHARS",
    "MAX_PROBES_PER_SESSION",
    "ModelRegistry",
    "PROBE_COOLDOWN_SECONDS",
    "PROBE_FORMAT_VERSION",
    "RATING_CATEGORIES",
    "RATING_VALUES",
    "SCHEMA_VERSION",
    "_env_limit",
    "get_helpers_needing_evaluation",
]


class ModelRegistry:
    """Track configured models, assessments, ratings, and measured use."""

    def __init__(
        self,
        workspace: str | Path,
        logger: EventLogger,
        base_model: str,
        available_models: list[str],
    ) -> None:
        self.path = Path(workspace) / "state" / "models.json"
        self.lock_path = self.path.with_suffix(".lock")
        self.logger = logger
        names = list(dict.fromkeys([base_model, *available_models]))
        if (
            not base_model
            or len(names) > MAX_MODELS
            or any(not name or len(name) > MAX_NAME_CHARS for name in names)
        ):
            raise ValueError("Configured model list is empty, too large, or contains an invalid name")
        self.base_model = base_model
        self.names = names
        self._logged_assumed_ceilings: set[str] = set()
        self.probe_cooldown_seconds = _env_limit(
            "SELF_PROBE_COOLDOWN_SECONDS", PROBE_COOLDOWN_SECONDS, 0, 86_400
        )
        self.probes_per_model_per_session = _env_limit(
            "SELF_PROBES_PER_MODEL_PER_SESSION", MAX_PROBES_PER_SESSION, 1, 20
        )
        self._initialize()

    def _blank(self, name: str) -> dict[str, Any]:
        return blank_model_entry(name, self.base_model)

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
        return {
            "schema_version": SCHEMA_VERSION,
            "probe_format_version": PROBE_FORMAT_VERSION,
            "base_model": self.base_model,
            "models": [],
        }

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
            data = initialize_registry_data(prior, self.base_model, self.names)
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
            self.logger.log(
                "assumed_output_ceiling",
                model=name,
                ceiling=ceiling,
                reason="Maximum output length not in registry or env; using assumed ceiling.",
            )
        return ceiling

    def validate_model_name(self, name: str, *, helpers_only: bool = False) -> tuple[bool, str]:
        """Validate model name against registry with alias hints and helpers-only rule."""
        if not isinstance(name, str) or not name.strip():
            valid_names = sorted(n for n in self.names if not helpers_only or n != self.base_model)
            return False, f"Model name must be a non-empty string. Valid models are: {', '.join(valid_names)}."
        cleaned = name.strip()
        if helpers_only and cleaned == self.base_model:
            enabled_helpers = sorted(
                m["name"]
                for m in self.list_models()["models"]
                if m.get("configured", True) and m["role"] == "helper" and m["status"] != "disabled"
            )
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
            return self.logger.redactor.value(
                next(item for item in self._read()["models"] if item["name"] == name)
            )

    def record_model_assessment(
        self,
        name: str,
        assessment: str,
        evidence: str,
        ratings: dict[str, str] | None = None,
        facts: list[dict[str, Any]] | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Persist the agent's assessment, category ratings, and optional knowledge facts for a model."""
        if name not in self.names:
            raise ValueError("Model is not configured")
        if not isinstance(assessment, str) or not assessment.strip():
            raise ValueError("Assessment must be non-empty")
        if not isinstance(evidence, str) or not evidence.strip():
            raise ValueError("Evidence reference must be non-empty")
        if len(assessment) > MAX_ASSESSMENT_CHARS or len(evidence) > MAX_EVIDENCE_CHARS:
            raise ValueError("Assessment or evidence reference exceeds its size limit")
        if ratings is not None and (
            not isinstance(ratings, dict)
            or set(ratings) != set(RATING_CATEGORIES)
            or any(
                not isinstance(value, str) or value not in RATING_VALUES
                for value in ratings.values()
            )
        ):
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
                if not any(
                    item.get("id") == probe_id and not item.get("invalidated")
                    for item in entry["probe_history"]
                ):
                    raise ValueError("Assessment cites an unknown probe id")
            entry["agent_assessment"] = self.logger.redactor.text(assessment.strip())
            entry["assessment_evidence"] = self.logger.redactor.text(evidence.strip())
            if ratings is not None:
                entry["ratings"] = dict(ratings)
                entry["ratings_at"] = datetime.now(timezone.utc).isoformat()
            self._write(data)
        self.logger.log("model_assessment_recorded", name=name, evidence=entry["assessment_evidence"])
        return {
            "ok": True,
            "name": name,
            "assessment": entry["agent_assessment"],
            "evidence": entry["assessment_evidence"],
            "ratings": entry["ratings"],
            "ratings_at": entry["ratings_at"],
        }

    def record_probe_outcome(self, name: str, outcome: str) -> None:
        """Update a model's status and probe history from observed results."""
        with self._locked():
            data = self._read()
            record_probe_outcome_stats(data, name, outcome)
            self._write(data)

    def record_call(
        self,
        name: str,
        *,
        failed: bool,
        latency_ms: int,
        not_found: bool = False,
    ) -> None:
        """Update measured call, token, latency, and failure statistics."""
        if name not in self.names:
            return
        with self._locked():
            data = self._read()
            record_call_stats(data, name, failed, latency_ms, not_found)
            self._write(data)

    def mark_not_found(self, name: str) -> None:
        """Mark a configured model as unavailable after a failed lookup."""
        with self._locked():
            data = self._read()
            mark_not_found_status(data, name)
            self._write(data)

    def record_output_failure(self, name: str) -> None:
        """Count an unusable response already counted as a successful API call."""
        with self._locked():
            data = self._read()
            record_output_failure_stats(data, name)
            self._write(data)

    def record_truncated_call(self, name: str) -> None:
        """Count a response that ended in max_tokens/truncation without marking clean success."""
        if name not in self.names:
            return
        with self._locked():
            data = self._read()
            record_truncated_call_stats(data, name)
            self._write(data)

    def record_network_error(self, name: str, *, latency_ms: int = 0) -> None:
        """Record a transient network/connection error without counting it as a model failure."""
        if name not in self.names:
            return
        with self._locked():
            data = self._read()
            record_network_error_stats(data, name, latency_ms=latency_ms)
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
            probe_id = begin_probe_record(
                data=data,
                name=name,
                session_id=session_id,
                when=when,
                probes_per_session=self.probes_per_model_per_session,
                cooldown_seconds=self.probe_cooldown_seconds,
            )
            self._write(data)
        self.logger.log("model_probe_started", name=name, probe_id=probe_id, session_id=session_id)
        return probe_id

    def finish_probe(
        self,
        name: str,
        probe_id: str,
        *,
        failed: bool,
        inconclusive: bool = False,
        latency_ms: int | None = None,
    ) -> None:
        """Store the final status of a completed model probe."""
        with self._locked():
            data = self._read()
            finish_probe_record(
                data=data,
                name=name,
                probe_id=probe_id,
                failed=failed,
                inconclusive=inconclusive,
                latency_ms=latency_ms,
            )
            self._write(data)

    def record_facts(
        self,
        name: str,
        facts: list[dict[str, Any]] | dict[str, Any],
        *,
        origin: str = "model_knowledge",
    ) -> dict[str, Any]:
        """Store agent-supplied facts (e.g. from model knowledge, verified=False)."""
        if name not in self.names:
            raise ValueError("Model is not configured")
        with self._locked():
            data = self._read()
            entry = next(item for item in data["models"] if item["name"] == name)
            facts_result, count = record_facts_entry(
                entry=entry,
                facts=facts,
                origin=origin,
                redactor=self.logger.redactor,
                blank_research=self._blank(name)["research"],
            )
            self._write(data)
        self.logger.log("model_facts_recorded", name=name, origin=origin, count=count)
        return {"ok": True, "name": name, "facts": facts_result}

    def record_research(
        self,
        name: str,
        *,
        status: str,
        source_url: str | None,
        facts: list[dict[str, Any]],
        status_message: str = "",
        urls_tried: list[str] | None = None,
        total_params: str | None = None,
        active_params: str | None = None,
        context_window: str | None = None,
        pricing: str | None = None,
        speed: str | None = None,
        strengths: str | None = None,
    ) -> dict[str, Any]:
        """Store official research evidence for a configured model."""
        if name not in self.names:
            raise ValueError("Model is not configured")
        with self._locked():
            data = self._read()
            entry = next(item for item in data["models"] if item["name"] == name)
            research, safe_facts, tried = record_research_entry(
                entry=entry,
                status=status,
                source_url=source_url,
                facts=facts,
                status_message=status_message,
                urls_tried=urls_tried,
                total_params=total_params,
                active_params=active_params,
                context_window=context_window,
                pricing=pricing,
                speed=speed,
                strengths=strengths,
                redactor=self.logger.redactor,
            )
            self._write(data)
        self.logger.log(
            "model_research_recorded",
            name=name,
            status=status,
            source_url=source_url,
            fact_count=len(safe_facts),
            urls_tried=tried,
        )
        return {"ok": True, "name": name, "research": research}
