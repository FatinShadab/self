"""Persistent, evidence-backed identity and first-awakening support for SELF (facade)."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from agent.identity.name_context import resolve_name_context
from agent.identity.store.constants import (
    IDENTITY_CONTEXT_MAX_CHARS,
    IDENTITY_MAX_BYTES,
    NAME_MAX_CHARS,
    clean_line,
    now,
)
from agent.identity.store.core_proposals import (
    list_proposed_patches,
    save_proposed_core_patch,
)
from agent.identity.store.first_awakening import (
    core_reference,
    ensure_editable_layer,
    initialize_human_file,
    write_code_explanation,
    write_self_inquiry,
)
from agent.identity.store.human_context import (
    append_human_answer,
    delete_about_human_line,
    read_about_human_text,
    save_human_name,
)
from agent.identity.store.prompting import (
    build_identity_prompt_context,
    format_self_panel_text,
)
from agent.identity.store.schema import (
    get_default_identity,
    normalize_identity,
    safe_text,
    sanitize_name_context,
)
from agent.identity.store.traits_reflections import (
    add_trait_to_identity,
    compact_identity_record,
    identity_has_trait,
    reflect_on_session,
)
from agent.infra.event_log import EventLogger
from agent.prompts.identity import NO_IDENTITY_RECORD_CONTEXT

_clean_line = clean_line


class IdentityStore:
    """Own SELF's durable identity files while preserving an audit trail."""

    def __init__(
        self,
        workspace: str | Path = "/home/entity",
        logger: EventLogger | None = None,
        *,
        core_root: str | Path = "/opt/agent/core",
        max_bytes: int = IDENTITY_MAX_BYTES,
        body: Any | None = None,
    ) -> None:
        self.workspace = Path(workspace)
        self.state = self.workspace / "state"
        self.self_root = self.workspace / "self"
        self.core_root = Path(core_root)
        self.max_bytes = max(2_000, max_bytes)
        self.logger = logger or EventLogger(self.workspace / "logs" / "actions.jsonl")
        self.body = body
        self.path = self.state / "identity.json"
        self.log_path = self.state / "identity_log.md"
        self.inquiry_path = self.state / "self_inquiry.md"
        self.explanation_path = self.state / "self_code_explanation.md"
        self.human_path = self.state / "about_human.md"
        self.awakening_path = self.state / "first_awakening.json"
        self.awakening_notes_path = self.state / "first_awakening.md"
        self.reflections_path = self.state / "identity_reflections.jsonl"
        self.proposals_path = self.state / "proposed_patches"

    @property
    def exists(self) -> bool:
        """Return whether a persistent identity record exists."""
        return self.path.exists()

    @classmethod
    def default_identity(cls, body: Any | None = None) -> dict[str, Any]:
        """Return a new identity record with default fields."""
        return get_default_identity(body)

    def _safe(self, value: Any, limit: int = 4_000) -> str:
        return safe_text(value, self.logger.redactor, limit)

    def _read_json(self, path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _atomic_json(self, path: Path, value: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(self.logger.redactor.value(value), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)

    def _append_text(self, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            os.write(fd, self.logger.redactor.text(text).encode("utf-8"))
        finally:
            os.close(fd)

    def _append_identity_log(self, change: str, why: str, session_id: str = "") -> None:
        session = self._safe(session_id, 120) or "not yet assigned"
        entry = (
            f"## {now()} — session {session}\n"
            f"- Change: {self._safe(change)}\n"
            f"- Why: {self._safe(why)}\n\n"
        )
        self._append_text(self.log_path, entry)
        self.logger.log("identity_changed", change=self._safe(change, 500), session_id=session)

    def load(self) -> dict[str, Any]:
        """Return a type-safe compact identity without mutating hand-edited state."""
        raw = self._read_json(self.path)
        base = self.default_identity(self.body)
        return normalize_identity(raw, base, self.logger.redactor)

    def _safe_name_context(self, context: dict[str, Any]) -> dict[str, Any]:
        """Keep name context bounded and data-only before putting it in prompts."""
        return sanitize_name_context(context, self.logger.redactor)

    def initialize(self, session_id: str = "") -> dict[str, Any]:
        """Create the initial identity exactly once, preserving human edits thereafter."""
        if self.path.exists():
            return self.load()
        identity = self.default_identity(self.body)
        self._atomic_json(self.path, identity)
        self._append_identity_log(
            "Created the initial identity record with no name and no asserted traits.",
            "This is the first persisted awakening state; the record distinguishes operating notes from sentience claims.",
            session_id,
        )
        self.logger.log("identity_initialized", session_id=self._safe(session_id, 120))
        return identity

    def ensure_editable_layer(self) -> None:
        """Create the intentionally writable extension layer without overwriting it."""
        ensure_editable_layer(self.self_root, self.logger)

    def _mark_stage(self, stage: str, session_id: str, learned: str) -> None:
        marker = self._read_json(self.awakening_path)
        stages = [str(item) for item in marker.get("completed_stages", [])]
        if stage not in stages:
            stages.append(stage)
        marker.update({"completed_stages": stages, "last_session_id": self._safe(session_id, 120), "updated_at": now()})
        self._atomic_json(self.awakening_path, marker)
        self._append_text(
            self.awakening_notes_path,
            f"## Stage {stage} — {now()}\n{self._safe(learned, 4_000)}\n\n",
        )
        self.logger.log("first_awakening_stage_completed", stage=stage, session_id=self._safe(session_id, 120))

    def _core_reference(self, filename: str, needle: str = "") -> str:
        """Return a file:line reference after reading the actual source when possible."""
        return core_reference(filename, needle, self.core_root)

    def _write_self_inquiry(self) -> None:
        write_self_inquiry(self.inquiry_path, self.core_root, self.body, self.logger.redactor, self_root=self.self_root)

    def _write_code_explanation(self) -> None:
        write_code_explanation(self.explanation_path, self.core_root, self.self_root, self.logger.redactor)

    def _record_body_independent_orientation(self) -> None:
        """Execute body-independent environment discovery orientation in Stage A."""
        (self.workspace / "state").mkdir(parents=True, exist_ok=True)
        self.logger.narrate("Orientation: No body profile configured; relying on tool-based environment discovery.")
        self.logger.log("orientation_discovery_initiated", mode="environment_neutral")

    def _initialize_human_file(self) -> None:
        initialize_human_file(self.human_path)

    def run_first_awakening(self, session_id: str) -> list[str]:
        """Perform/resume A–E exactly for a newly created identity record."""
        marker = self._read_json(self.awakening_path)
        fresh = not self.path.exists()
        resumable = bool(marker) and not bool(marker.get("completed"))
        if not fresh and not resumable:
            return []

        self.initialize(session_id)
        self.ensure_editable_layer()
        completed = {str(item) for item in marker.get("completed_stages", [])}
        narration: list[str] = []

        if "A" not in completed:
            orient_ctx = (
                self.body.describe().identity_orientation_context
                if self.body and hasattr(self.body, "describe") and self.body.describe().identity_orientation_context
                else "operating with an environment to discover and verify."
            )
            op_env = (
                self.body.describe().identity_operating_environment
                if self.body and hasattr(self.body, "describe") and self.body.describe().identity_operating_environment
                else "The operating environment is not a biological body."
            )
            if self.body and hasattr(self.body, "sense"):
                try:
                    self.body.sense()
                except Exception:
                    pass
            else:
                self._record_body_independent_orientation()
            message = (
                f"A — Orientation: I am an LLM-driven agent {orient_ctx} "
                "I have a standing exploration goal, no name yet, and no memory before the files created now. "
                f"{op_env}"
            )
            self._mark_stage("A", session_id, message)
            narration.append(message)

        if "B" not in completed:
            self._write_self_inquiry()
            message = "B — I wrote checked and open self-questions to state/self_inquiry.md, marking each answer verified or unverified."
            self._mark_stage("B", session_id, message)
            narration.append(message)
        if "C" not in completed:
            self._write_code_explanation()
            message = "C — I read the core and editable-layer structure and wrote a file-and-line-backed explanation to state/self_code_explanation.md."
            self._mark_stage("C", session_id, message)
            narration.append(message)
        if "D" not in completed:
            self._initialize_human_file()
            message = (
                "D — Hello. I am currently unnamed. Please choose a name with `/rename <name>` if you want one, "
                "and tell me only what you wish about your goals, worries, preferred updates, or speaking style. "
                "I will store only what you choose to say."
            )
            self._mark_stage("D", session_id, message)
            narration.append(message)
        if "E" not in completed:
            message = (
                "E — I am beginning early exploration. I will add no trait merely because it sounds good; "
                "any future trait must cite observed behavior from a completed session."
            )
            try:
                from agent.opencode.wrapper import OpencodeDelegator
                opencode = OpencodeDelegator(workspace=self.workspace)
                op_st = opencode.status()
                if not op_st.get("installed", True):
                    message += " Note: opencode is not installed."
                elif not opencode._read_delegations():
                    message += " Note: opencode has never been used; I may choose to run one trivial delegation to learn how it behaves."
            except Exception:
                pass
            self._mark_stage("E", session_id, message)
            narration.append(message)
        marker = self._read_json(self.awakening_path)
        marker.update({"completed": True, "completed_at": now(), "awaiting_name": self.load().get("name") is None})
        self._atomic_json(self.awakening_path, marker)
        return narration

    def display_name(self) -> str:
        """Return the identity name shown to the human."""
        return str(self.load().get("name") or "unnamed")

    def awaiting_name(self) -> bool:
        """Whether the first-meeting name prompt is still open."""
        return bool(self._read_json(self.awakening_path).get("awaiting_name")) and self.load().get("name") is None

    def human_name(self) -> str | None:
        """Return the human's explicitly supplied preferred name, if known."""
        value = self.load().get("human_name")
        return str(value) if value else None

    def set_human_name(self, name: str, session_id: str = "") -> str:
        """Persist the human's explicitly supplied preferred name."""
        identity = self.initialize(session_id)
        identity, cleaned = save_human_name(
            identity=identity,
            human_path=self.human_path,
            log_change_fn=self._append_identity_log,
            logger=self.logger,
            redactor=self.logger.redactor,
            name=name,
            session_id=session_id,
        )
        self._atomic_json(self.path, identity)
        return cleaned

    def voice(self) -> str:
        """Return the identity's configured voice description."""
        return str(self.load().get("voice") or self.default_identity()["voice"])

    def prompt_context(self, active_plugins: Any = None) -> str:
        """Bounded identity context for every model call, including hand-edited state."""
        if not self.path.exists():
            return NO_IDENTITY_RECORD_CONTEXT
        return build_identity_prompt_context(self.load(), active_plugins, self.logger.redactor)

    def set_plugin_embodiment(self, plugin_name: str, notes: str) -> None:
        """Record or update embodiment notes for a plugin in the single identity record."""
        identity = self.load()
        embodiments = identity.setdefault("plugin_embodiments", {})
        embodiments[plugin_name] = notes
        self._atomic_json(self.path, identity)

    def remove_plugin_embodiment(self, plugin_name: str) -> None:
        """Remove a plugin's embodiment notes from the single identity record."""
        identity = self.load()
        embodiments = identity.get("plugin_embodiments", {})
        if plugin_name in embodiments:
            del embodiments[plugin_name]
            self._atomic_json(self.path, identity)

    def is_managed_path(self, path: str | Path) -> bool:
        """Whether a file is identity-managed and must not be generically overwritten."""
        try:
            candidate = Path(path).resolve(strict=False)
            managed = (self.path, self.log_path, self.human_path, self.awakening_path, self.reflections_path)
            return any(candidate == item.resolve(strict=False) for item in managed)
        except OSError:
            return False

    def set_name(self, name: str, session_id: str = "", named_by: str = "human") -> dict[str, Any]:
        """Update SELF's display name with an audit entry."""
        cleaned = self._safe(name, NAME_MAX_CHARS)
        if not cleaned or len(cleaned) > NAME_MAX_CHARS:
            raise ValueError(f"Name must contain 1-{NAME_MAX_CHARS} visible characters.")
        if named_by not in {"human", "self"}:
            raise ValueError("named_by must be human or self")
        identity = self.initialize(session_id)
        previous = identity.get("name")
        context = resolve_name_context(cleaned)
        identity.update({"name": cleaned, "named_by": named_by, "named_at": now(), "name_context": context})
        self._atomic_json(self.path, identity)
        reason = "The human chose this name." if named_by == "human" else "The human explicitly authorized SELF to choose this name."
        self._append_identity_log(
            f"Name changed from {previous or 'unnamed'} to {cleaned}.",
            reason,
            session_id,
        )
        self._append_identity_log(
            f"Resolved name context for {cleaned}: {context.get('status')}.",
            "Stored a bounded symbolic context so the model can adapt style without treating the name as proof of personality.",
            session_id,
        )
        self.logger.log("name_context_resolved", name=cleaned, status=context.get("status"), source=context.get("source", ""))
        marker = self._read_json(self.awakening_path)
        if marker:
            marker["awaiting_name"] = False
            marker["updated_at"] = now()
            self._atomic_json(self.awakening_path, marker)
        return identity

    def record_human_answer(self, text: str, session_id: str = "") -> bool:
        """Persist only a voluntarily supplied first-meeting answer, with no inference."""
        return append_human_answer(
            human_path=self.human_path,
            init_human_file_fn=self._initialize_human_file,
            logger=self.logger,
            redactor=self.logger.redactor,
            text=text,
            session_id=session_id,
        )

    def about_human_text(self, limit: int = 6_000) -> str:
        """Return the identity's human-facing context."""
        return read_about_human_text(self.human_path, self.logger.redactor, limit=limit)

    def delete_human_line(self, line_number: int, session_id: str = "") -> str:
        """Remove one line of human context while preserving the audit trail."""
        return delete_about_human_line(
            human_path=self.human_path,
            log_change_fn=self._append_identity_log,
            logger=self.logger,
            redactor=self.logger.redactor,
            line_number=line_number,
            session_id=session_id,
        )

    def _append_jsonl(self, path: Path, record: dict[str, Any]) -> None:
        self._append_text(path, json.dumps(self.logger.redactor.value(record), ensure_ascii=False) + "\n")

    def _identity_has_trait(self, trait: str) -> bool:
        return identity_has_trait(self.load().get("traits", []), trait)

    def add_trait(self, trait: str, evidence: str, session_id: str) -> bool:
        """Record an evidence-backed identity trait."""
        identity = self.initialize(session_id)
        ok = add_trait_to_identity(
            identity=identity,
            log_change_fn=self._append_identity_log,
            redactor=self.logger.redactor,
            trait=trait,
            evidence=evidence,
            session_id=session_id,
        )
        if ok:
            self._atomic_json(self.path, identity)
        return ok

    def reflect_session(self, session_id: str, started_at: str, summary: str = "") -> list[str]:
        """Record evidence-only answers to the session reflection questions."""
        return reflect_on_session(
            workspace=self.workspace,
            identity=self.load(),
            reflections_path=self.reflections_path,
            add_trait_fn=lambda t, e, s: self.add_trait(t, e, s),
            append_jsonl_fn=self._append_jsonl,
            log_change_fn=self._append_identity_log,
            compact_fn=self.compact_if_needed,
            redactor=self.logger.redactor,
            session_id=session_id,
            started_at=started_at,
            summary=summary,
        )

    def compact_if_needed(self, session_id: str = "") -> bool:
        """Only compact a genuinely oversize identity, logging any removal visibly."""
        return compact_identity_record(
            identity_path=self.path,
            load_fn=self.load,
            atomic_json_fn=self._atomic_json,
            log_change_fn=self._append_identity_log,
            max_bytes=self.max_bytes,
            session_id=session_id,
        )

    def proposed_patches(self) -> list[Path]:
        """Return proposed source changes from identity state."""
        return list_proposed_patches(self.proposals_path)

    def propose_core_patch(self, name: str, diff: str, reasoning: str, session_id: str = "") -> dict[str, Any]:
        """Save, but never apply, a core patch for the human to review on the host."""
        return save_proposed_core_patch(
            proposals_path=self.proposals_path,
            log_change_fn=self._append_identity_log,
            logger=self.logger,
            redactor=self.logger.redactor,
            name=name,
            diff=diff,
            reasoning=reasoning,
            session_id=session_id,
        )

    def self_panel_text(self) -> str:
        """Return identity text for the terminal UI panel."""
        return format_self_panel_text(self.load(), self.log_path)


__all__ = [
    "IDENTITY_MAX_BYTES",
    "IDENTITY_CONTEXT_MAX_CHARS",
    "NAME_MAX_CHARS",
    "now",
    "clean_line",
    "_clean_line",
    "IdentityStore",
]
