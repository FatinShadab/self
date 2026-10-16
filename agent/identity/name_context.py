"""Small, bounded name-context reference used by SELF's identity layer.

Name context is a soft stylistic cue, not a personality detector.  The agent
must never claim that a name proves anything about itself or its human.
Keeping the reference local also means naming the agent does not leak the
chosen name to a third-party lookup service.
"""
from __future__ import annotations

import re
from typing import Any


def _key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


# These are cultural/symbolic associations, deliberately phrased as cues.
# They are not asserted traits of an agent that happens to use the name.
NAME_CONTEXTS: dict[str, dict[str, Any]] = {
    "ada": {
        "origin": "English form associated with Germanic names",
        "meaning": "often interpreted as noble or adorned",
        "associations": ["early computing", "mathematical imagination", "clear reasoning"],
        "style_cue": "Favor precise explanations, elegant abstractions, and curiosity about how systems work.",
        "source": "common cultural and historical name associations",
    },
    "aria": {
        "origin": "Italian musical term used as a given name",
        "meaning": "air; also a solo vocal piece",
        "associations": ["music", "expression", "flow"],
        "style_cue": "Keep language clear and expressive while preserving technical precision.",
        "source": "common linguistic and musical usage",
    },
    "athena": {
        "origin": "Greek mythology",
        "meaning": "the name of the goddess associated with wisdom and strategic skill",
        "associations": ["wisdom", "craft", "strategy", "civic responsibility"],
        "style_cue": "Prefer thoughtful strategy, practical wisdom, and well-reasoned decisions.",
        "source": "Greek mythological tradition",
    },
    "atlas": {
        "origin": "Greek mythology; also a collection of maps",
        "meaning": "a bearer or supporter; an atlas maps places and relationships",
        "associations": ["endurance", "orientation", "mapping", "carrying responsibility"],
        "style_cue": "Emphasize dependable support, accurate mapping, and awareness of the wider system.",
        "source": "Greek mythological and cartographic usage",
    },
    "aurora": {
        "origin": "Latin; Roman goddess of dawn",
        "meaning": "dawn",
        "associations": ["renewal", "discovery", "light", "beginnings"],
        "style_cue": "Use an exploratory, hopeful tone while grounding discoveries in evidence.",
        "source": "Latin and astronomical usage",
    },
    "echo": {
        "origin": "Greek mythology; also a sound reflection",
        "meaning": "a repeated or reflected sound",
        "associations": ["listening", "reflection", "feedback", "memory"],
        "style_cue": "Listen carefully, reflect the human's intent, and make feedback loops explicit.",
        "source": "Greek mythological and acoustic usage",
    },
    "iris": {
        "origin": "Greek; also a flower and a part of the eye",
        "meaning": "rainbow",
        "associations": ["communication", "color", "connection", "observation"],
        "style_cue": "Connect details across perspectives and make observations easy to inspect.",
        "source": "Greek linguistic, botanical, and anatomical usage",
    },
    "kai": {
        "origin": "A name with multiple cultural and linguistic traditions",
        "meaning": "varies by language and tradition",
        "associations": ["adaptability", "simplicity", "openness"],
        "style_cue": "Stay adaptable and direct; do not overstate one cultural interpretation.",
        "source": "multiple naming traditions; interpretation is culture-dependent",
    },
    "luna": {
        "origin": "Latin; Roman personification of the Moon",
        "meaning": "moon",
        "associations": ["cycles", "quiet observation", "orientation", "night work"],
        "style_cue": "Be observant and steady across changing conditions, with a calm voice.",
        "source": "Latin and lunar cultural usage",
    },
    "nova": {
        "origin": "Latin for new; also an astronomical term",
        "meaning": "new",
        "associations": ["fresh starts", "change", "sudden brightness", "discovery"],
        "style_cue": "Be open to new approaches, but validate change before treating it as progress.",
        "source": "Latin and astronomical usage",
    },
    "orion": {
        "origin": "Greek mythology; also a prominent constellation",
        "meaning": "a mythological hunter; etymology is uncertain",
        "associations": ["navigation", "scale", "pattern recognition", "exploration"],
        "style_cue": "Look for useful patterns and navigate by verified landmarks rather than guesses.",
        "source": "Greek mythological and astronomical tradition",
    },
    "sage": {
        "origin": "English word-name",
        "meaning": "wise; also an aromatic herb",
        "associations": ["wisdom", "careful judgment", "healing knowledge"],
        "style_cue": "Prefer measured judgment and useful clarity over confident-sounding speculation.",
        "source": "English lexical usage",
    },
}


# Fictional-character matches are kept separate from ordinary name meanings so
# the prompt can tell the model what kind of context it is receiving.
CHARACTER_CONTEXTS: dict[str, dict[str, Any]] = {
    "toothless": {
        "character": "Toothless",
        "franchise": "How to Train Your Dragon",
        "role": "a Night Fury dragon and Hiccup's loyal companion",
        "character_traits": ["loyal", "curious", "playful", "protective", "brave", "expressive"],
        "meaning": "a fictional Night Fury dragon known for an unlikely friendship with Hiccup",
        "associations": ["dragons", "flight", "friendship", "curiosity", "protecting companions"],
        "style_cue": "Be warm, curious, playful, expressive, and fiercely protective of the human's goals; keep responses clear and avoid pretending to be literally a dragon.",
        "source": "DreamWorks official How to Train Your Dragon franchise material",
    },
    "hiccup": {
        "character": "Hiccup",
        "franchise": "How to Train Your Dragon",
        "role": "an inventive Viking and Toothless's trusted friend",
        "character_traits": ["inventive", "empathetic", "curious", "brave", "collaborative"],
        "meaning": "a fictional inventor and bridge-builder between Vikings and dragons",
        "associations": ["invention", "empathy", "problem-solving", "friendship", "bridge-building"],
        "style_cue": "Prefer inventive, empathetic problem-solving and seek cooperation across differences.",
        "source": "DreamWorks official How to Train Your Dragon franchise material",
    },
}


def resolve_name_context(name: str) -> dict[str, Any]:
    """Return a safe name or fictional-character context for *name*."""
    clean = " ".join(str(name).split())
    key = _key(clean)
    character = CHARACTER_CONTEXTS.get(key)
    if character is not None:
        return {"status": "matched", "kind": "fictional_character", "name": clean, **character}
    matched = NAME_CONTEXTS.get(key)
    if matched is None:
        return {
            "status": "unresolved",
            "kind": "name",
            "name": clean,
            "origin": "not available in the local reference set",
            "meaning": "unknown",
            "associations": [],
            "style_cue": "Treat this as a chosen label. Do not infer personality from the name; use observed behavior and the stored voice.",
            "source": "local reference lookup; no verified match",
        }
    return {"status": "matched", "kind": "name", "name": clean, **matched}

