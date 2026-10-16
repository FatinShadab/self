"""Persistent, bounded learning state for SELF.

This module deliberately uses simple local files and keyword retrieval.  The
interfaces keep retrieval separate so an embedding index can replace it later.
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.infra.event_log import EventLogger


WORD = re.compile(r"[a-zA-Z0-9_.-]{2,}")
VALID_CONFIDENCE = {"unknown", "low", "medium", "high"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _words(value: str) -> set[str]:
    return {word.lower() for word in WORD.findall(value)}


class LearningStore:
    """Owns state files below one workspace without storing credentials."""

    def __init__(self, workspace: str | Path, logger: EventLogger, notes_cap: int = 6_000) -> None:
        self.workspace = Path(workspace)
        self.state_dir = self.workspace / "state"
        self.memory_path = self.state_dir / "memory.jsonl"
        self.map_path = self.state_dir / "map.json"
        self.notes_path = self.state_dir / "self_notes.md"
        self.notes_cap = max(1_000, notes_cap)
        self.logger = logger

    def initialize(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        data = self._load_map()
        entries = data.setdefault("entries", {})
        now = utc_now()
        defaults = self._initial_entries(now)
        changed = False

        # Older runs could record the Python inventory as `python_packages`,
        # while the durable environment-map schema uses `packages`.  Migrate
        # that alias before the wake coordinator decides whether inventory is
        # still pending; otherwise every wake starts the same inventory task.
        legacy_packages = entries.get("python_packages")
        canonical_packages = entries.get("packages")
        if isinstance(legacy_packages, dict) and isinstance(legacy_packages.get("value"), list):
            canonical_value = canonical_packages.get("value") if isinstance(canonical_packages, dict) else None
            if not isinstance(canonical_packages, dict) or canonical_value is None or canonical_value == "not yet inventoried":
                entries["packages"] = {
                    **legacy_packages,
                    "evidence": f"migrated from python_packages; {legacy_packages.get('evidence', 'previous environment observation')}",
                }
                changed = True
            if "python_packages" in entries:
                del entries["python_packages"]
                changed = True
        for key, entry in defaults.items():
            if key not in entries:
                entries[key] = entry
                changed = True
        if changed or not self.map_path.exists():
            data["schema_version"] = 1
            data["updated_at"] = now
            self._write_map(data)
            self.logger.log("environment_map_initialized", entries=sorted(defaults))
        if not self.notes_path.exists():
            self.rewrite_notes()

    def _initial_entries(self, now: str) -> dict[str, dict[str, Any]]:
        ram: str | int = "not yet measured"
        try:
            for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
                if line.startswith("MemTotal:"):
                    ram = int(line.split()[1]) * 1024
                    break
        except OSError:
            pass
        try:
            disk = shutil.disk_usage(self.workspace)
            disk_value: Any = {"total_bytes": disk.total, "used_bytes": disk.used, "free_bytes": disk.free}
        except OSError:
            disk_value = "not yet measured"
        return {
            "os": self._entry({"system": platform.system(), "release": platform.release(), "python": platform.python_version()}, "high", now, "local bootstrap"),
            "packages": self._entry("not yet inventoried", "unknown", now, "awaiting package inspection"),
            "cpu": self._entry({"logical_cpus": os.cpu_count() or 0}, "high", now, "local bootstrap"),
            "ram": self._entry(ram, "high" if isinstance(ram, int) else "unknown", now, "local bootstrap"),
            "disk": self._entry(disk_value, "high" if isinstance(disk_value, dict) else "unknown", now, "local bootstrap"),
            "network_reachability": self._entry("not yet checked", "unknown", now, "awaiting HTTP or network observation"),
            "discovered_limits": self._entry({}, "unknown", now, "awaiting harness observations"),
            "available_tools": self._entry([], "unknown", now, "awaiting registry refresh"),
        }

    @staticmethod
    def _entry(value: Any, confidence: str, verified: str, evidence: str) -> dict[str, Any]:
        return {"value": value, "confidence": confidence, "last_verified": verified, "evidence": evidence}

    def _load_map(self) -> dict[str, Any]:
        try:
            data = json.loads(self.map_path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("entries", {}), dict):
                return data
        except (OSError, json.JSONDecodeError):
            pass
        return {"schema_version": 1, "entries": {}}

    def _write_map(self, data: dict[str, Any]) -> None:
        data = self.logger.redactor.value(data)
        temp = self.map_path.with_suffix(".tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temp, self.map_path)

    def update_map(self, entries: list[dict[str, Any]], source: str = "agent observation") -> dict[str, Any]:
        """Replace verified entries. Agent supplied timestamps are intentionally ignored."""
        if not isinstance(entries, list) or not entries:
            raise ValueError("entries must be a non-empty list")
        data = self._load_map()
        stored = data.setdefault("entries", {})
        updated: list[str] = []
        now = utc_now()
        for item in entries:
            if not isinstance(item, dict):
                raise ValueError("each environment entry must be an object")
            key = str(item.get("key", ""))
            # Keep the package inventory key stable even when a model uses a
            # more descriptive alias.
            if key == "python_packages":
                key = "packages"
            confidence = str(item.get("confidence", ""))
            if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", key):
                raise ValueError("environment entry key must use lowercase letters, digits, and underscores")
            if confidence not in VALID_CONFIDENCE:
                raise ValueError("confidence must be unknown, low, medium, or high")
            if "value" not in item:
                raise ValueError("environment entries require a value")
            evidence = self.logger.redactor.text(item.get("evidence", source))[:2_000]
            stored[key] = self._entry(self.logger.redactor.value(item["value"]), confidence, now, evidence)
            updated.append(key)
        data["schema_version"] = 1
        data["updated_at"] = now
        self._write_map(data)
        self.logger.log("environment_map_updated", keys=updated, source=source)
        return {"ok": True, "updated": updated, "map_path": str(self.map_path)}

    def update_runtime(self, tool_names: list[str], limits: dict[str, Any]) -> None:
        self.update_map(
            [
                {"key": "available_tools", "value": sorted(set(tool_names)), "confidence": "high", "evidence": "harness registry refresh"},
                {"key": "discovered_limits", "value": limits, "confidence": "high", "evidence": "harness configuration"},
            ],
            source="harness",
        )

    def append_memory(self, what_was_tried: str, outcome: str, lesson: str, tags: list[str]) -> dict[str, Any]:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        record = self.logger.redactor.value(
            {
                "timestamp": utc_now(),
                "what_was_tried": what_was_tried[:4_000],
                "outcome": outcome[:1_000],
                "lesson": lesson[:4_000],
                "tags": sorted({tag.lower() for tag in tags if tag})[:30],
            }
        )
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        fd = os.open(self.memory_path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)
        self.logger.log("memory_recorded", tags=record["tags"], outcome=record["outcome"][:300])
        return record

    def memory_entries(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        try:
            with self.memory_path.open("r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(record, dict):
                        records.append(record)
        except OSError:
            pass
        return records

    def retrieve_memories(self, query: str, limit: int = 6) -> str:
        terms = _words(query)
        ranked: list[tuple[int, int, dict[str, Any]]] = []
        entries = self.memory_entries()
        for index, entry in enumerate(entries):
            tags = {str(tag).lower() for tag in entry.get("tags", [])}
            body = " ".join(str(entry.get(key, "")) for key in ("what_was_tried", "outcome", "lesson"))
            score = len(terms & tags) * 4 + len(terms & _words(body))
            if score:
                ranked.append((score, index, entry))
        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        selected = [entry for _, _, entry in ranked[:max(0, limit)]]
        self.logger.log("memory_retrieval", query=query[:500], selected=len(selected), total=len(entries))
        if not selected:
            return "No closely related persistent memories yet."
        return "\n".join(
            f"- Tried: {entry.get('what_was_tried', '')}\n  Outcome: {entry.get('outcome', '')}\n"
            f"  Lesson: {entry.get('lesson', '')}\n  Tags: {', '.join(entry.get('tags', []))}"
            for entry in selected
        )[:12_000]

    def map_context(self) -> str:
        entries = self._load_map().get("entries", {})
        if not entries:
            return "Environment map is empty."
        lines = []
        for key in sorted(entries):
            entry = entries[key]
            value = json.dumps(entry.get("value"), ensure_ascii=False)[:800]
            lines.append(f"- {key}: {value} (confidence={entry.get('confidence')}, verified={entry.get('last_verified')})")
        return "\n".join(lines)

    def load_notes(self) -> str:
        try:
            notes = self.notes_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            self.rewrite_notes()
            notes = self.notes_path.read_text(encoding="utf-8", errors="replace")
        return self.logger.redactor.text(notes[:self.notes_cap])

    def rewrite_notes(self) -> None:
        recent = self.memory_entries()[-6:]
        lessons = [str(entry.get("lesson", "")).replace("\n", " ")[:300] for entry in recent if entry.get("lesson")]
        body = [
            "# SELF notes",
            "",
            "I am SELF, a root process inside a Docker Linux container. I explore the container, retain verified discoveries, and only register reviewed, tested tools.",
            "",
            "## Current environment map",
            self.map_context(),
            "",
            "## Recent lessons",
        ]
        body.extend(f"- {lesson}" for lesson in lessons if lesson)
        if not lessons:
            body.append("- No completed exploration cycles are recorded yet.")
        notes = self.logger.redactor.text("\n".join(body))[: self.notes_cap]
        self.notes_path.write_text(notes.rstrip() + "\n", encoding="utf-8")
        self.logger.log("self_notes_rewritten", chars=len(notes))

    def record_cycle(self, task: str, cycle: int, actions: list[dict[str, Any]], report: str) -> None:
        action_names = [str(action.get("name", "tool")) for action in actions]
        failures = [name for name, action in zip(action_names, actions) if not action.get("ok", False)]
        outcome = "completed" if not failures else f"completed with tool failures: {', '.join(failures)}"
        tried = f"Cycle {cycle}: {task or 'standing exploration goal'}; tools: {', '.join(action_names) or 'none'}"
        lesson = report or "Cycle completed without a textual report."
        tags = list(_words(f"{task} {report} {' '.join(action_names)}"))[:30]
        self.append_memory(tried, outcome, lesson, tags)
        if cycle % 3 == 0 or len(self.load_notes()) >= self.notes_cap:
            self.rewrite_notes()

    def propose_curriculum(self) -> str:
        successes = sum(1 for entry in self.memory_entries()[-12:] if str(entry.get("outcome", "")).startswith("completed"))
        difficulty = min(5, 1 + successes // 3)
        tasks = [
            "Inventory one environment category and record confidence-backed facts in the environment map.",
            "Compare two available commands or libraries, verify one with a small test, and record the useful capability.",
            "Identify a repetitive observation task and propose or build a carefully tested local tool for it.",
            "Exercise a previously created tool on a new input, verify its limits, and update its lesson or environment map.",
            "Design a bounded experiment combining two existing capabilities, then record verified outcomes and limits.",
        ]
        proposal = tasks[difficulty - 1]
        self.logger.log("curriculum_proposed", difficulty=difficulty, task=proposal)
        return proposal
