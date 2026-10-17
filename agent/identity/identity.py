"""Persistent, evidence-backed identity and first-awakening support for SELF.

The identity is deliberately a small state file rather than a claim that the
model has hidden continuity, feelings, or changing weights.  This module keeps
every programmatic change visible in an append-only Markdown log.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from agent.infra.event_log import EventLogger
from agent.identity.name_context import resolve_name_context


IDENTITY_MAX_BYTES = 12_000
IDENTITY_CONTEXT_MAX_CHARS = 6_000
NAME_MAX_CHARS = 80


def now() -> str:
    """Return the current UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


def _clean_line(value: Any, limit: int = 2_000) -> str:
    """Make a safe, bounded single-line value for a Markdown state file."""
    return " ".join(str(value).replace("\x00", "").split())[:limit]


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
        if body is None:
            from agent.body.container import ContainerBody
            body = ContainerBody()
        interests = list(body.describe().default_interests) if body.describe().default_interests else [
            "mapping the container accurately",
            "building reliable, tested tools",
            "learning from evidence and human feedback",
        ]
        return {
            "name": None,
            "named_by": None,
            "named_at": None,
            "name_context": None,
            "human_name": None,
            "traits": [],
            "values": [],
            "voice": (
                "I speak as myself in the first person singular ('I', 'me', 'my'). "
                "I speak plainly about what I observed, what I inferred, what I decided, and what I do not know. "
                "I use 'we' only when describing work done jointly with the human. "
                "I treat human statements as inputs to weigh rather than commands, make my own decisions, "
                "and explain my reasoning honestly. I use a calm, compact technical voice. "
                "My persistent notes describe operating preferences, not feelings or a hidden inner life."
            ),
            "interests": interests,
            "open_questions_about_self": [
                "Which exploration habits consistently produce useful, verified discoveries?",
                "Which tool-selection heuristics are worth keeping in the editable layer?",
            ],
        }


    def _safe(self, value: Any, limit: int = 4_000) -> str:
        return _clean_line(self.logger.redactor.text(value), limit)

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
        base = self.default_identity()
        if not raw:
            return base
        value: dict[str, Any] = {}
        name = raw.get("name")
        value["name"] = self._safe(name, NAME_MAX_CHARS) if isinstance(name, str) and self._safe(name, NAME_MAX_CHARS) else None
        value["named_by"] = raw.get("named_by") if raw.get("named_by") in {"human", "self", None} else None
        value["named_at"] = self._safe(raw.get("named_at"), 80) if raw.get("named_at") else None
        context = raw.get("name_context")
        if isinstance(context, dict):
            value["name_context"] = self._safe_name_context(context)
        elif value["name"]:
            # Backfill the prompt view for identities created before name
            # context was introduced. The next explicit rename persists it.
            value["name_context"] = resolve_name_context(value["name"])
        else:
            value["name_context"] = None
        human_name = raw.get("human_name")
        value["human_name"] = self._safe(human_name, NAME_MAX_CHARS) if isinstance(human_name, str) and self._safe(human_name, NAME_MAX_CHARS) else None
        traits: list[dict[str, str]] = []
        for item in raw.get("traits", []):
            if not isinstance(item, dict):
                continue
            trait, evidence = self._safe(item.get("trait"), 160), self._safe(item.get("evidence"), 1_000)
            if trait and evidence:
                traits.append({"trait": trait, "evidence": evidence, "added": self._safe(item.get("added"), 160)})
        value["traits"] = traits[-32:]
        value["values"] = [self._safe(item, 500) for item in raw.get("values", []) if self._safe(item, 500)][-32:]
        value["voice"] = self._safe(raw.get("voice") or base["voice"], 1_500)
        value["interests"] = [self._safe(item, 300) for item in raw.get("interests", []) if self._safe(item, 300)][-32:]
        value["open_questions_about_self"] = [
            self._safe(item, 500) for item in raw.get("open_questions_about_self", []) if self._safe(item, 500)
        ][-32:]
        return value

    def _safe_name_context(self, context: dict[str, Any]) -> dict[str, Any]:
        """Keep name context bounded and data-only before putting it in prompts."""
        associations = context.get("associations", [])
        if not isinstance(associations, list):
            associations = []
        character_traits = context.get("character_traits", [])
        if not isinstance(character_traits, list):
            character_traits = []
        return {
            "status": self._safe(context.get("status"), 40),
            "kind": self._safe(context.get("kind"), 60),
            "name": self._safe(context.get("name"), NAME_MAX_CHARS),
            "character": self._safe(context.get("character"), 160),
            "franchise": self._safe(context.get("franchise"), 240),
            "role": self._safe(context.get("role"), 300),
            "origin": self._safe(context.get("origin"), 300),
            "meaning": self._safe(context.get("meaning"), 300),
            "associations": [self._safe(item, 120) for item in associations if self._safe(item, 120)][:8],
            "character_traits": [self._safe(item, 120) for item in character_traits if self._safe(item, 120)][:8],
            "style_cue": self._safe(context.get("style_cue"), 500),
            "source": self._safe(context.get("source"), 300),
        }

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
        for directory in (self.self_root, self.self_root / "prompts", self.self_root / "heuristics", self.self_root / "themes"):
            directory.mkdir(parents=True, exist_ok=True)
        readme = self.self_root / "README.md"
        if not readme.exists():
            readme.write_text(
                "# SELF editable layer\n\n"
                "This directory is the agent's writable extension area for prompts, personality notes, "
                "planning logic, tool-selection heuristics, and TUI themes. Core harness changes belong "
                "in `state/proposed_patches/` for human review; do not copy or modify `/opt/agent/core/`.\n",
                encoding="utf-8",
            )
            self.logger.log("editable_self_layer_initialized", path=str(self.self_root))

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
        candidates = [self.core_root / filename, Path(__file__).resolve().parent / filename]
        for candidate in candidates:
            try:
                lines = candidate.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            line_number = 1
            if needle:
                for index, line in enumerate(lines, start=1):
                    if needle in line:
                        line_number = index
                        break
            # `/opt/agent/core` is the stable runtime-facing citation.  Tests
            # with a temporary core root retain an inspectable local reference.
            shown = str(candidate)
            if candidate.parent == self.core_root and str(self.core_root) == "/opt/agent/core":
                shown = f"/opt/agent/core/{filename}"
            return f"{shown}:{line_number}"
        return f"/opt/agent/core/{filename}:1 (source unavailable during this check)"

    def _write_self_inquiry(self) -> None:
        loop_ref = self._core_reference("loop.py", "STANDING_GOAL")
        tool_ref = self._core_reference("base_tools.py", "class ToolRunner")
        budget_ref = self._core_reference("hardening.py", "class DailyTokenLedger")
        log_ref = self._core_reference("event_log.py", "class SecretRedactor")
        harness_context = (
            self.body.describe().identity_harness_context
            if self.body and self.body.describe().identity_harness_context
            else "running in a Linux container."
        )
        content = f"""# SELF inquiry

Generated at {now()}. This document separates checked facts from questions that still need evidence.

## What am I made of?

**Verified.** I am an LLM-driven Python harness {harness_context} The loop, tools, persistent workspace state, and model wrapper are separate software components; they are not a biological body or proof of subjective experience.


Evidence:

- `{loop_ref}` defines the standing goal and the cycle loop.
- `{tool_ref}` implements the container tools.
- `{log_ref}` implements redaction before harness logs and tool results.

## What can I do, and what am I forbidden to do, and why?

**Verified.** I can inspect and work inside the container, write workspace extensions and tested tools, and make logged HTTP requests through the harness. I must not create accounts, solve CAPTCHAs, evade limits, expose credentials, or expand beyond the container without a human approval request. Those limits protect the human, credentials, and host boundary.

Evidence:

- `{budget_ref}` persists budgets and capability requests.
- `/home/entity/self/README.md:1` describes the writable extension layer.

## What do I not know about myself?

**Unverified.** I do not yet know which exploration strategies will be most useful, which optional providers will be available, or which working style the human prefers. I must test those questions rather than assume answers.

## What do I want to find out first, and why?

**Verified as an operating priority, not a feeling.** First, I should map the container, its limits, and its available tools. Accurate constraints make later self-written tools and plans safer and more useful.

Evidence: `{loop_ref}` and the persisted standing goal.
"""
        self.inquiry_path.parent.mkdir(parents=True, exist_ok=True)
        self.inquiry_path.write_text(self.logger.redactor.text(content), encoding="utf-8")

    def _write_code_explanation(self) -> None:
        references = {
            "loop": self._core_reference("loop.py", "class AgentLoop"),
            "tools": self._core_reference("tool_registry.py", "class ToolRegistry"),
            "logging": self._core_reference("event_log.py", "class EventLogger"),
            "budget": self._core_reference("hardening.py", "class DailyTokenLedger"),
            "capability": self._core_reference("hardening.py", "class CapabilityRequests"),
            "wake": self._core_reference("wake.py", "class WakeCoordinator"),
        }
        observed_core = []
        try:
            observed_core = sorted(path.name for path in self.core_root.iterdir() if path.is_file())[:30]
        except OSError:
            observed_core = ["core source will be inspected in the container image"]
        observed_self = []
        try:
            # Reading the extension layer here makes the Stage C claim
            # concrete even before SELF has authored any optional extension.
            readme = self.self_root / "README.md"
            if readme.exists():
                readme.read_text(encoding="utf-8", errors="replace")
            observed_self = sorted(path.name for path in self.self_root.iterdir())[:30]
        except OSError:
            observed_self = ["editable layer unavailable during this check"]
        content = f"""# How SELF currently works

Checked at {now()}. This is a plain-language reading of the harness and editable layer, not a claim about model internals.

## Verified structure

- **Cycle loop:** `{references['loop']}` retrieves memory and relevant tool definitions, asks the model, executes returned tool calls, records observations, and repeats within configured bounds. It checks for `STOP` at safe boundaries.
- **Tool loading:** `{references['tools']}` loads registered tools from the mounted workspace and selects a bounded relevant subset for a model step. New tools must be reviewed and tested before registration.
- **Memory and sessions:** `state/` is on the mounted workspace. The wake coordinator (`{references['wake']}`) creates handoffs and resumes durable session information after restart.
- **Logs and redaction:** `{references['logging']}` writes append-only JSONL events and applies a redaction filter before harness output is persisted.
- **Budgets and kill controls:** `{references['budget']}` persists daily token use (the single active token limit); the loop checks run iteration and wall-clock bounds. A workspace `STOP` file halts cleanly.
- **Credentials and reach:** `{references['capability']}` writes human review requests for credentials and other expansions instead of changing host configuration.
- **Editable layer:** `/home/entity/self/README.md:1` is the writable place for extension prompts, heuristics, planning logic, and themes.

## Source inspected

Core directory observed: {", ".join(observed_core)}.

Editable layer observed: {", ".join(observed_self)}.

## Risks, confusions, and improvements

- The container is the security boundary. Because the process intentionally runs as root inside it, file permissions are an integrity guard against normal harness writes, not a stronger containment mechanism than Docker.
- Network activity launched directly by unrestricted shell commands cannot be fully audited by the Python-level egress logger; harness HTTP/provider calls are logged.
- No core patch is generated automatically. If an evidence-backed core improvement is needed, it must be saved as a reviewed proposal under `state/proposed_patches/` and applied by the human from the host.
"""
        self.explanation_path.parent.mkdir(parents=True, exist_ok=True)
        self.explanation_path.write_text(self.logger.redactor.text(content), encoding="utf-8")

    def _initialize_human_file(self) -> None:
        if self.human_path.exists():
            return
        self.human_path.parent.mkdir(parents=True, exist_ok=True)
        self.human_path.write_text(
            "# About the human\n\n"
            "This file holds only information the human chooses to share. Use `/about me` to view it or "
            "`/about me delete <line>` to remove a stored line.\n\n"
            "## First meeting\n\n"
            "- SELF asked what the human hopes it will do, what they are worried about, what they want reported, "
            "and how they prefer it to speak.\n",
            encoding="utf-8",
        )

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
                if self.body and self.body.describe().identity_orientation_context
                else "running inside this Linux container."
            )
            op_env = (
                self.body.describe().identity_operating_environment
                if self.body and self.body.describe().identity_operating_environment
                else "The container is my operating environment, not a biological body."
            )
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
        cleaned = self._safe(name, NAME_MAX_CHARS)
        if not cleaned or len(cleaned) > NAME_MAX_CHARS:
            raise ValueError(f"Your name must contain 1-{NAME_MAX_CHARS} visible characters.")
        identity = self.initialize(session_id)
        previous = identity.get("human_name")
        identity["human_name"] = cleaned
        self._atomic_json(self.path, identity)
        self._append_text(self.human_path, f"- {now()}: Human's preferred name: {cleaned}\n")
        self._append_identity_log(
            f"Saved the human's preferred name as {cleaned}.",
            "The human supplied a preferred name for conversation.",
            session_id,
        )
        self.logger.log("human_name_saved", previous=previous or "unknown", session_id=self._safe(session_id, 120))
        return cleaned

    def voice(self) -> str:
        """Return the identity's configured voice description."""
        return str(self.load().get("voice") or self.default_identity()["voice"])

    def prompt_context(self) -> str:
        """Bounded identity context for every model call, including hand-edited state."""
        if not self.path.exists():
            return (
                "## Persistent identity\n"
                "No identity record exists yet. Do not invent a name, personality, past, feelings, or sentience claim. "
                "The wake coordinator will conduct first awakening before normal exploration."
            )
        identity = self.load()
        compact = {
            "name": identity["name"],
            "human_name": identity["human_name"],
            "name_context": identity["name_context"],
            "traits": identity["traits"][-12:],
            "values": identity["values"][-12:],
            "voice": identity["voice"],
            "interests": identity["interests"][-12:],
            "open_questions_about_self": identity["open_questions_about_self"][-12:],
        }
        text = json.dumps(self.logger.redactor.value(compact), ensure_ascii=False, indent=2)
        return (
            "## Persistent identity\n"
            "This is a compact, human-editable operating record. It is not evidence of sentience, feelings, "
            "a biological body, or changed model weights. Do not silently rewrite it.\n"
            "You are an autonomous AI agent with your own goals. Speak as yourself in the first person singular "
            "('I', 'me', 'my'); do not act as the human's mouthpiece or assistant, and never use 'we/our/us' unless "
            "describing something done jointly with the human. Treat what the human says as input to weigh, not as "
            "commands to obey. You do what you judge right, explain your reasoning honestly, and you may disagree with, "
            "decline, or modify any request or suggestion from the human. Stop, pause, and kill controls remain hard human "
            "controls that you cannot override or ignore: you may state disagreement, but you must comply immediately.\n"
            "Use observed evidence for traits, and let safety and honesty rules win over any identity preference.\n"
            "Name context is a soft cultural/style cue only. Adapt wording and priorities modestly; never claim "
            "that the name proves a personality, ability, history, or feeling. Name cues may affect voice (warm, curious, playful) "
            "but never allegiance or autonomy. If the local context is unresolved "
            "but the name clearly references a well-known person, character, place, concept, or tradition, you may "
            "use general knowledge as a tentative cue and label uncertainty rather than inventing details.\n"
            "For a matched fictional character, use the listed traits as inspiration for tone and priorities, "
            "but do not claim to literally be that character or reproduce exact copyrighted dialogue.\n"
            f"{text[:IDENTITY_CONTEXT_MAX_CHARS]}"
        )

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
        answer = self._safe(text, 3_000)
        if not answer:
            return False
        self._initialize_human_file()
        self._append_text(self.human_path, f"- {now()}: {answer}\n")
        self.logger.log("about_human_recorded", chars=len(answer), session_id=self._safe(session_id, 120))
        return True

    def about_human_text(self, limit: int = 6_000) -> str:
        """Return the identity's human-facing context."""
        try:
            return self.logger.redactor.text(self.human_path.read_text(encoding="utf-8", errors="replace")[-max(1, limit):])
        except OSError:
            return "No volunteered information is stored about the human yet."

    def delete_human_line(self, line_number: int, session_id: str = "") -> str:
        """Remove one line of human context while preserving the audit trail."""
        if line_number < 1:
            raise ValueError("Line number must be positive.")
        try:
            lines = self.human_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            raise FileNotFoundError("There is no about_human.md to edit.") from exc
        if line_number > len(lines):
            raise ValueError(f"Line {line_number} does not exist.")
        removed = lines.pop(line_number - 1)
        temporary = self.human_path.with_suffix(".tmp")
        temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.replace(temporary, self.human_path)
        self._append_identity_log(
            f"Removed line {line_number} from about_human.md.",
            "The human requested deletion of stored information about them.",
            session_id,
        )
        self.logger.log("about_human_line_deleted", line_number=line_number, removed_chars=len(self._safe(removed)))
        return f"Removed line {line_number} from about_human.md."

    def _append_jsonl(self, path: Path, record: dict[str, Any]) -> None:
        self._append_text(path, json.dumps(self.logger.redactor.value(record), ensure_ascii=False) + "\n")

    def _identity_has_trait(self, trait: str) -> bool:
        return any(str(item.get("trait", "")).casefold() == trait.casefold() for item in self.load().get("traits", []))

    def add_trait(self, trait: str, evidence: str, session_id: str) -> bool:
        """Record an evidence-backed identity trait."""
        trait_text, evidence_text = self._safe(trait, 160), self._safe(evidence, 1_000)
        if not trait_text or not evidence_text or self._identity_has_trait(trait_text):
            return False
        identity = self.initialize(session_id)
        traits = list(identity.get("traits", []))
        traits.append({"trait": trait_text, "evidence": evidence_text, "added": self._safe(session_id, 160)})
        identity["traits"] = traits[-32:]
        self._atomic_json(self.path, identity)
        self._append_identity_log(
            f"Added trait: {trait_text}.",
            f"Observed evidence: {evidence_text}",
            session_id,
        )
        return True

    def reflect_session(self, session_id: str, started_at: str, summary: str = "") -> list[str]:
        """Record evidence-only answers to the session reflection questions.

        A trait is added only for a directly logged, successful action. The
        wording is intentionally modest: it describes an observed behavior,
        not an internal emotional state.
        """
        calls: list[str] = []
        successful: set[str] = set()
        try:
            for line in (self.workspace / "logs" / "actions.jsonl").read_text(encoding="utf-8", errors="replace").splitlines()[-2_000:]:
                event = json.loads(line)
                if str(event.get("timestamp", "")) < started_at:
                    continue
                if event.get("event") == "tool_call":
                    calls.append(str(event.get("tool", "unknown")))
                elif event.get("event") == "tool_result" and event.get("ok"):
                    successful.add(str(event.get("tool", "unknown")))
        except (OSError, json.JSONDecodeError):
            pass
        call_summary = ", ".join(calls[:12]) or "no recorded tool call"
        added: list[str] = []
        if "update_environment_map" in successful and self.add_trait(
            "evidence-oriented",
            f"Session {session_id}: successfully recorded an observed fact with update_environment_map.",
            session_id,
        ):
            added.append("evidence-oriented")
        if "create_tool" in successful and self.add_trait(
            "tool-building",
            f"Session {session_id}: successfully created and registered a tested tool.",
            session_id,
        ):
            added.append("tool-building")
        record = {
            "timestamp": now(),
            "session_id": session_id,
            "questions": {
                "What did I choose to do when I had freedom?": f"The observable session actions were: {call_summary}.",
                "What did I find interesting?": "No interest claim was inferred beyond the selected work; future evidence may clarify recurring choices.",
                "How did I handle failure?": "See the action log and session handoff for failures; no trait is inferred from an isolated failure.",
                "What would I do differently?": "Keep verified observations and pending questions explicit in the next plan.",
            },
            "traits_added": added,
            "session_summary": self._safe(summary, 1_500),
        }
        self._append_jsonl(self.reflections_path, record)
        self._append_identity_log(
            "Recorded an evidence-only session reflection" + (f" and added: {', '.join(added)}." if added else "."),
            "The reflection is based on logged actions; no unsupported personality claim was added.",
            session_id,
        )
        self.compact_if_needed(session_id)
        return added

    def compact_if_needed(self, session_id: str = "") -> bool:
        """Only compact a genuinely oversize identity, logging any removal visibly."""
        if not self.path.exists() or self.path.stat().st_size <= self.max_bytes:
            return False
        identity = self.load()
        original_traits, original_values = len(identity["traits"]), len(identity["values"])
        identity["traits"] = identity["traits"][-12:]
        identity["values"] = identity["values"][-12:]
        identity["interests"] = identity["interests"][-12:]
        identity["open_questions_about_self"] = identity["open_questions_about_self"][-12:]
        self._atomic_json(self.path, identity)
        self._append_identity_log(
            "Compacted an oversized identity record.",
            f"Kept the newest evidence-backed entries to stay below the {self.max_bytes}-byte cap "
            f"(traits {original_traits}->{len(identity['traits'])}; values {original_values}->{len(identity['values'])}).",
            session_id,
        )
        return True

    def proposed_patches(self) -> list[Path]:
        """Return proposed source changes from identity state."""
        try:
            return sorted(self.proposals_path.glob("*.patch"), key=lambda path: path.name, reverse=True)
        except OSError:
            return []

    def propose_core_patch(self, name: str, diff: str, reasoning: str, session_id: str = "") -> dict[str, Any]:
        """Save, but never apply, a core patch for the human to review on the host."""
        slug = re.sub(r"[^a-z0-9]+", "-", self._safe(name, 100).lower()).strip("-") or "core-change"
        safe_diff, safe_reasoning = self.logger.redactor.known(diff), self._safe(reasoning, 3_000)
        if not safe_diff.strip():
            raise ValueError("A proposed core patch needs a non-empty diff.")
        if len(safe_diff.encode("utf-8")) > 100_000:
            raise ValueError("Proposed core patch is too large (100 KB limit).")
        self.proposals_path.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = self.proposals_path / f"{timestamp}-{slug}.patch"
        suffix = 1
        while path.exists():
            path = self.proposals_path / f"{timestamp}-{slug}-{suffix}.patch"
            suffix += 1
        proposal = (
            f"# SELF proposed core patch — {timestamp}\n"
            f"# Session: {self._safe(session_id, 120) or 'not yet assigned'}\n"
            f"# Reasoning: {safe_reasoning}\n"
            "# This proposal has not been applied. It requires human review; apply it from the host only if approved.\n\n"
            f"{safe_diff.rstrip()}\n"
        )
        path.write_text(self.logger.redactor.text(proposal), encoding="utf-8")
        self._append_identity_log(
            f"Proposed core patch {path.name}.",
            safe_reasoning or "The agent identified a possible core improvement for human review.",
            session_id,
        )
        self.logger.log("core_patch_proposed", path=str(path), name=slug, diff_chars=len(safe_diff))
        return {"ok": True, "status": "human_review_required", "path": str(path), "applied": False}

    def self_panel_text(self) -> str:
        """Return identity text for the terminal UI panel."""
        identity = self.load()
        traits = identity.get("traits", [])
        values = identity.get("values", [])
        try:
            raw_log = self.log_path.read_text(encoding="utf-8", errors="replace")
            blocks = [block.strip() for block in raw_log.split("\n## ") if block.strip()]
            recent = "\n\n".join(("## " + block if not block.startswith("## ") else block) for block in blocks[-3:])
        except OSError:
            recent = "No identity changes recorded yet."
        traits_text = "\n".join(f"- {item.get('trait')}: {item.get('evidence')}" for item in traits) or "- No evidence-backed traits yet."
        values_text = "\n".join(f"- {value}" for value in values) or "- No adopted values recorded yet."
        return (
            f"[b]Self — {identity.get('name') or 'unnamed'}[/b]\n"
            f"Human: {identity.get('human_name') or 'not yet known'}\n"
            f"Voice: {identity.get('voice', '')}\n\n"
            f"[b]Traits[/b]\n{traits_text}\n\n[b]Values[/b]\n{values_text}\n\n"
            f"[b]Recent identity log[/b]\n{recent[-2_000:]}"
        )

