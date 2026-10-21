"""Plugin manifest validation and parsing for SELF plugins."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CORE_API_VERSION = "1.1.0"
VALID_KINDS = frozenset({"body", "skill", "both"})
VALID_RISK_CLASSES = frozenset({"reads", "writes", "executes", "network"})

RESERVED_SLASH_COMMANDS = frozenset({
    "stop", "pause", "resume", "kill", "status", "rename", "name",
    "plugin", "plugins", "help", "quit", "exit", "goal", "goals",
    "reflect", "decide", "decisions", "targets", "plan", "self",
    "patches", "about", "journal", "tools", "requests", "inputs",
    "memory", "budget", "models", "identity",
})


class PluginManifestValidationError(ValueError):
    """Raised when a plugin manifest fails schema or compatibility validation."""
    pass


def _parse_version(v: str) -> tuple[int, int, int]:
    """Parse a semantic version 'X.Y.Z' into integer tuple."""
    parts = v.strip().split(".")
    try:
        if len(parts) == 1:
            return (int(parts[0]), 0, 0)
        elif len(parts) == 2:
            return (int(parts[0]), int(parts[1]), 0)
        elif len(parts) >= 3:
            return (int(parts[0]), int(parts[1]), int(parts[2].split("-")[0].split("+")[0]))
    except ValueError:
        pass
    raise PluginManifestValidationError(f"Invalid version string: '{v}'")


def is_core_api_compatible(required_range: str, current_api: str = CORE_API_VERSION) -> bool:
    """Check if the current core API version satisfies the plugin's compatible range."""
    required = required_range.strip()
    if not required:
        return False
    if required in {"*", "any"}:
        return True

    curr = _parse_version(current_api)

    # Check comma-separated range clauses e.g. '>=1.0.0,<2.0.0' or '>=1.0,<2.0'
    clauses = [c.strip() for c in required.split(",") if c.strip()]
    for clause in clauses:
        if clause.startswith("^"):
            target = _parse_version(clause[1:])
            # Caret: allows changes that do not modify left-most non-zero digit
            if target[0] > 0:
                if curr[0] != target[0] or curr < target:
                    return False
            elif target[1] > 0:
                if curr[0] != 0 or curr[1] != target[1] or curr < target:
                    return False
            else:
                if curr != target:
                    return False
        elif clause.startswith("~"):
            target = _parse_version(clause[1:])
            if curr[0] != target[0] or curr[1] != target[1] or curr < target:
                return False
        elif clause.startswith(">="):
            target = _parse_version(clause[2:])
            if curr < target:
                return False
        elif clause.startswith("<="):
            target = _parse_version(clause[2:])
            if curr > target:
                return False
        elif clause.startswith(">"):
            target = _parse_version(clause[1:])
            if curr <= target:
                return False
        elif clause.startswith("<"):
            target = _parse_version(clause[1:])
            if curr >= target:
                return False
        elif clause.startswith("=="):
            target = _parse_version(clause[2:])
            if curr != target:
                return False
        elif clause.startswith("="):
            target = _parse_version(clause[1:])
            if curr != target:
                return False
        else:
            # Exact match
            target = _parse_version(clause)
            if curr != target:
                return False
    return True


@dataclass
class PluginSensor:
    """Declared passive sensor telemetry specification."""
    name: str
    description: str
    risk_class: str
    reversible: bool
    required_permission_level: str


@dataclass
class PluginAction:
    """Declared environmental action specification."""
    name: str
    description: str
    risk_class: str
    reversible: bool
    required_permission_level: str


@dataclass
class PluginCommand:
    """Declared human-facing slash command specification."""
    name: str
    description: str
    usage: str = ""


@dataclass
class DeclaredNeeds:
    """Declared external prerequisites for plugin operation."""
    env_vars: list[str] = field(default_factory=list)
    mounts: list[str] = field(default_factory=list)


@dataclass
class PluginManifest:
    """Parsed and validated plugin manifest representation."""
    name: str
    version: str
    core_api: str
    kind: str
    description: str
    tools: list[dict[str, Any]]
    sensors: list[PluginSensor]
    actions: list[PluginAction]
    starting_goal_seeds: list[str]
    embodiment: str
    identity_notes: list[str] = field(default_factory=list)
    state_dir: str = ""
    declared_needs: DeclaredNeeds = field(default_factory=DeclaredNeeds)
    tests_entry_point: str = ""
    commands: list[PluginCommand] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert manifest object to standard dictionary representation."""
        return {
            "name": self.name,
            "version": self.version,
            "core_api": self.core_api,
            "kind": self.kind,
            "description": self.description,
            "tools": self.tools,
            "sensors": [
                {
                    "name": s.name,
                    "description": s.description,
                    "risk_class": s.risk_class,
                    "reversible": s.reversible,
                    "required_permission_level": s.required_permission_level,
                }
                for s in self.sensors
            ],
            "actions": [
                {
                    "name": a.name,
                    "description": a.description,
                    "risk_class": a.risk_class,
                    "reversible": a.reversible,
                    "required_permission_level": a.required_permission_level,
                }
                for a in self.actions
            ],
            "starting_goal_seeds": self.starting_goal_seeds,
            "embodiment": self.embodiment,
            "identity_notes": self.identity_notes,
            "state_dir": self.state_dir,
            "declared_needs": {
                "env_vars": self.declared_needs.env_vars,
                "mounts": self.declared_needs.mounts,
            },
            "tests_entry_point": self.tests_entry_point,
            "commands": [
                {
                    "name": c.name,
                    "description": c.description,
                    "usage": c.usage,
                }
                for c in self.commands
            ],
        }


def parse_manifest(
    source: dict[str, Any] | str | Path,
    current_api: str = CORE_API_VERSION,
    check_compatibility: bool = True,
) -> PluginManifest:
    """Parse and strictly validate a plugin.json manifest."""
    if isinstance(source, (str, Path)):
        path = Path(source)
        if not path.exists():
            raise PluginManifestValidationError(f"Manifest file not found: {path}")
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PluginManifestValidationError(f"Invalid JSON in manifest {path}: {exc}") from exc
    elif isinstance(source, dict):
        raw = source
    else:
        raise PluginManifestValidationError(f"Expected dict or path, got {type(source).__name__}")

    # Required top-level fields
    name = str(raw.get("name", "")).strip()
    if not name or not re.match(r"^[a-zA-Z0-9_-]+$", name):
        raise PluginManifestValidationError(f"Plugin 'name' must be a non-empty alphanumeric identifier, got: {name!r}")

    version = str(raw.get("version", "")).strip()
    if not version:
        raise PluginManifestValidationError("Plugin 'version' is required.")
    _parse_version(version)

    core_api = str(raw.get("core_api", "")).strip()
    if not core_api:
        raise PluginManifestValidationError(f"Plugin '{name}' core_api field is missing or empty. A valid core_api compatible range is required.")
    if check_compatibility and not is_core_api_compatible(core_api, current_api=current_api):
        raise PluginManifestValidationError(
            f"Plugin '{name}' core_api range '{core_api}' is incompatible with core version '{current_api}'."
        )

    kind = str(raw.get("kind", "")).strip().lower()
    if kind not in VALID_KINDS:
        raise PluginManifestValidationError(f"Plugin 'kind' must be one of {sorted(VALID_KINDS)}, got: {kind!r}")

    description = str(raw.get("description", "")).strip()
    if not description:
        raise PluginManifestValidationError("Plugin 'description' is required.")

    # Tools
    raw_tools = raw.get("tools")
    if not isinstance(raw_tools, list):
        raise PluginManifestValidationError("Plugin 'tools' must be a list of tool definitions.")
    tools: list[dict[str, Any]] = []
    for idx, t in enumerate(raw_tools):
        if not isinstance(t, dict) or not str(t.get("name", "")).strip():
            raise PluginManifestValidationError(f"Tool at index {idx} must be a dict with a non-empty 'name'.")
        tools.append(dict(t))

    # Sensors
    raw_sensors = raw.get("sensors")
    if not isinstance(raw_sensors, list):
        raise PluginManifestValidationError("Plugin 'sensors' must be a list of sensor definitions.")
    sensors: list[PluginSensor] = []
    for idx, s in enumerate(raw_sensors):
        if not isinstance(s, dict):
            raise PluginManifestValidationError(f"Sensor at index {idx} must be a dict.")
        s_name = str(s.get("name", "")).strip()
        s_desc = str(s.get("description", "")).strip()
        s_risk = str(s.get("risk_class", "")).strip().lower()
        if not s_name:
            raise PluginManifestValidationError(f"Sensor at index {idx} requires a 'name'.")
        if s_risk not in VALID_RISK_CLASSES:
            raise PluginManifestValidationError(f"Sensor '{s_name}' has invalid risk_class {s_risk!r}; must be one of {sorted(VALID_RISK_CLASSES)}.")
        if "reversible" not in s:
            raise PluginManifestValidationError(f"Sensor '{s_name}' requires boolean 'reversible' flag.")
        perm = str(s.get("required_permission_level", "")).strip()
        if not perm:
            raise PluginManifestValidationError(f"Sensor '{s_name}' requires 'required_permission_level'.")
        sensors.append(PluginSensor(
            name=s_name,
            description=s_desc,
            risk_class=s_risk,
            reversible=bool(s.get("reversible")),
            required_permission_level=perm,
        ))

    # Actions
    raw_actions = raw.get("actions")
    if not isinstance(raw_actions, list):
        raise PluginManifestValidationError("Plugin 'actions' must be a list of action definitions.")
    actions: list[PluginAction] = []
    for idx, a in enumerate(raw_actions):
        if not isinstance(a, dict):
            raise PluginManifestValidationError(f"Action at index {idx} must be a dict.")
        a_name = str(a.get("name", "")).strip()
        a_desc = str(a.get("description", "")).strip()
        a_risk = str(a.get("risk_class", "")).strip().lower()
        if not a_name:
            raise PluginManifestValidationError(f"Action at index {idx} requires a 'name'.")
        if a_risk not in VALID_RISK_CLASSES:
            raise PluginManifestValidationError(f"Action '{a_name}' has invalid risk_class {a_risk!r}; must be one of {sorted(VALID_RISK_CLASSES)}.")
        if "reversible" not in a:
            raise PluginManifestValidationError(f"Action '{a_name}' requires boolean 'reversible' flag.")
        perm = str(a.get("required_permission_level", "")).strip()
        if not perm:
            raise PluginManifestValidationError(f"Action '{a_name}' requires 'required_permission_level'.")
        actions.append(PluginAction(
            name=a_name,
            description=a_desc,
            risk_class=a_risk,
            reversible=bool(a.get("reversible")),
            required_permission_level=perm,
        ))

    # Starting goal seeds
    raw_seeds = raw.get("starting_goal_seeds", [])
    if not isinstance(raw_seeds, list):
        raise PluginManifestValidationError("Plugin 'starting_goal_seeds' must be a list.")
    starting_goal_seeds = [str(item).strip() for item in raw_seeds if str(item).strip()]

    # Embodiment
    embodiment = str(raw.get("embodiment") or raw.get("embodiment_text", "")).strip()
    if not embodiment:
        raise PluginManifestValidationError("Plugin 'embodiment' text is required.")

    # Identity notes
    raw_id_notes = raw.get("identity_notes", [])
    if isinstance(raw_id_notes, str):
        identity_notes = [raw_id_notes.strip()] if raw_id_notes.strip() else []
    elif isinstance(raw_id_notes, list):
        identity_notes = [str(note).strip() for note in raw_id_notes if str(note).strip()]
    else:
        identity_notes = []

    state_dir = str(raw.get("state_dir", "")).strip()

    # Declared needs
    raw_needs = raw.get("declared_needs", {})
    if isinstance(raw_needs, dict):
        env_vars = [str(v).strip() for v in raw_needs.get("env_vars", []) if str(v).strip()]
        mounts = [str(m).strip() for m in raw_needs.get("mounts", []) if str(m).strip()]
        declared_needs = DeclaredNeeds(env_vars=env_vars, mounts=mounts)
    else:
        declared_needs = DeclaredNeeds()

    tests_entry_point = str(raw.get("tests_entry_point", "")).strip()

    # Commands (optional list of human-facing slash commands)
    raw_commands = raw.get("commands", [])
    if not isinstance(raw_commands, list):
        raise PluginManifestValidationError("Plugin 'commands' must be a list of command definitions.")
    commands: list[PluginCommand] = []
    for idx, c in enumerate(raw_commands):
        if not isinstance(c, dict):
            raise PluginManifestValidationError(f"Command at index {idx} must be a dict.")
        c_name = str(c.get("name", "")).strip().lstrip("/")
        c_desc = str(c.get("description", "")).strip()
        c_usage = str(c.get("usage", "")).strip()
        if not c_name:
            raise PluginManifestValidationError(f"Command at index {idx} requires a 'name'.")
        if c_name.lower() in RESERVED_SLASH_COMMANDS:
            raise PluginManifestValidationError(
                f"Plugin '{name}' cannot register reserved slash command '/{c_name}'. "
                "Hard human controls and core commands cannot be overridden by plugins."
            )
        commands.append(PluginCommand(name=c_name, description=c_desc, usage=c_usage))

    return PluginManifest(
        name=name,
        version=version,
        core_api=core_api,
        kind=kind,
        description=description,
        tools=tools,
        sensors=sensors,
        actions=actions,
        starting_goal_seeds=starting_goal_seeds,
        embodiment=embodiment,
        identity_notes=identity_notes,
        state_dir=state_dir,
        declared_needs=declared_needs,
        tests_entry_point=tests_entry_point,
        commands=commands,
    )
