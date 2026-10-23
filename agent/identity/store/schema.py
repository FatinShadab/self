"""Identity schema, default dictionary generation, and structure normalization."""
from __future__ import annotations

from typing import Any

from agent.identity.name_context import resolve_name_context
from agent.identity.store.constants import NAME_MAX_CHARS, clean_line
from agent.prompts.identity import AUTONOMOUS_VOICE


def safe_text(value: Any, redactor: Any = None, limit: int = 4_000) -> str:
    """Clean and redact a text value bounded to limit chars."""
    if redactor and hasattr(redactor, "text"):
        value = redactor.text(value)
    return clean_line(value, limit)


def get_default_identity(body: Any | None = None) -> dict[str, Any]:
    """Return a new identity record with default fields."""
    if body is None:
        from agent.body.container import ContainerBody
        body = ContainerBody()
    raw_interests = (
        list(body.describe().default_interests)
        if body.describe().default_interests
        else [
            "mapping the container accurately",
            "building reliable, tested tools",
            "learning from evidence and human feedback",
        ]
    )
    interests = [
        {"interest": it, "plugin": "core", "body": "container"}
        for it in raw_interests
    ]
    return {
        "name": None,
        "named_by": None,
        "named_at": None,
        "name_context": None,
        "human_name": None,
        "traits": [],
        "values": [],
        "voice": AUTONOMOUS_VOICE,
        "interests": interests,
        "plugin_embodiments": {},
        "open_questions_about_self": [
            "Which exploration habits consistently produce useful, verified discoveries?",
            "Which tool-selection heuristics are worth keeping in the editable layer?",
        ],
    }


def sanitize_name_context(context: dict[str, Any], redactor: Any = None) -> dict[str, Any]:
    """Keep name context bounded and data-only before putting it in prompts."""
    associations = context.get("associations", [])
    if not isinstance(associations, list):
        associations = []
    character_traits = context.get("character_traits", [])
    if not isinstance(character_traits, list):
        character_traits = []
    return {
        "status": safe_text(context.get("status"), redactor, 40),
        "kind": safe_text(context.get("kind"), redactor, 60),
        "name": safe_text(context.get("name"), redactor, NAME_MAX_CHARS),
        "character": safe_text(context.get("character"), redactor, 160),
        "franchise": safe_text(context.get("franchise"), redactor, 240),
        "role": safe_text(context.get("role"), redactor, 300),
        "origin": safe_text(context.get("origin"), redactor, 300),
        "meaning": safe_text(context.get("meaning"), redactor, 300),
        "associations": [safe_text(item, redactor, 120) for item in associations if safe_text(item, redactor, 120)][:8],
        "character_traits": [safe_text(item, redactor, 120) for item in character_traits if safe_text(item, redactor, 120)][:8],
        "style_cue": safe_text(context.get("style_cue"), redactor, 500),
        "source": safe_text(context.get("source"), redactor, 300),
    }


def normalize_identity(
    raw: dict[str, Any],
    base: dict[str, Any],
    redactor: Any = None,
) -> dict[str, Any]:
    """Return a type-safe compact identity without mutating hand-edited state."""
    if not raw:
        return base
    value: dict[str, Any] = {}
    name = raw.get("name")
    value["name"] = (
        safe_text(name, redactor, NAME_MAX_CHARS)
        if isinstance(name, str) and safe_text(name, redactor, NAME_MAX_CHARS)
        else None
    )
    value["named_by"] = raw.get("named_by") if raw.get("named_by") in {"human", "self", None} else None
    value["named_at"] = safe_text(raw.get("named_at"), redactor, 80) if raw.get("named_at") else None
    context = raw.get("name_context")
    if isinstance(context, dict):
        value["name_context"] = sanitize_name_context(context, redactor)
    elif value["name"]:
        value["name_context"] = resolve_name_context(value["name"])
    else:
        value["name_context"] = None
    human_name = raw.get("human_name")
    value["human_name"] = (
        safe_text(human_name, redactor, NAME_MAX_CHARS)
        if isinstance(human_name, str) and safe_text(human_name, redactor, NAME_MAX_CHARS)
        else None
    )
    traits: list[dict[str, str]] = []
    for item in raw.get("traits", []):
        if not isinstance(item, dict):
            continue
        trait, evidence = safe_text(item.get("trait"), redactor, 160), safe_text(item.get("evidence"), redactor, 1_000)
        if trait and evidence:
            traits.append({"trait": trait, "evidence": evidence, "added": safe_text(item.get("added"), redactor, 160)})
    value["traits"] = traits[-32:]
    value["values"] = [safe_text(item, redactor, 500) for item in raw.get("values", []) if safe_text(item, redactor, 500)][-32:]
    value["voice"] = safe_text(raw.get("voice") or base["voice"], redactor, 1_500)
    clean_interests: list[Any] = []
    for item in raw.get("interests", []):
        if isinstance(item, dict):
            clean_interests.append({
                "interest": safe_text(item.get("interest") or item.get("text", ""), redactor, 300),
                "plugin": safe_text(item.get("plugin", "core"), redactor, 80),
                "body": safe_text(item.get("body", "container"), redactor, 80),
            })
        elif safe_text(item, redactor, 300):
            clean_interests.append(safe_text(item, redactor, 300))
    value["interests"] = clean_interests[-32:]
    value["open_questions_about_self"] = [
        safe_text(item, redactor, 500)
        for item in raw.get("open_questions_about_self", [])
        if safe_text(item, redactor, 500)
    ][-32:]
    if isinstance(raw.get("plugin_embodiments"), dict):
        value["plugin_embodiments"] = {
            safe_text(k, redactor, 80): safe_text(v, redactor, 2_000)
            for k, v in raw["plugin_embodiments"].items()
            if isinstance(k, str) and isinstance(v, str)
        }
    else:
        value["plugin_embodiments"] = {}
    return value
