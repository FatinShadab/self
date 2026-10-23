"""Scenario description and capability generation for SimBody."""
from __future__ import annotations

from typing import Any

from agent.body.base import BodyDescription, Capability


def build_sim_description(scenario: dict[str, Any]) -> BodyDescription:
    """Return narrative describing the embodiment, default interests, and rules from scenario."""
    desc = scenario.get("description", {})
    default_interests = desc.get(
        "default_interests",
        [
            "operating reliably within scenario boundaries",
            "monitoring telemetry and avoiding envelope breaches",
            "completing assigned scenario tasks accurately",
        ],
    )
    body_rules = desc.get(
        "body_rules",
        [
            "- Operations are bounded by the active simulation scenario.",
            "- Remain strictly within documented operating envelopes.",
        ],
    )
    return BodyDescription(
        embodiment_text=desc.get(
            "embodiment_text",
            "Your body is a deterministic simulated environment driven by scenario parameters.",
        ),
        embodiment_clause=desc.get(
            "embodiment_clause",
            "operating inside a simulated environment.",
        ),
        default_interests=default_interests,
        initial_orientation_task=desc.get(
            "initial_orientation_task",
            "Observe current simulation telemetry, verify operating constraints, and complete the scenario objective.",
        ),
        conversation_context=desc.get(
            "conversation_context",
            "operating inside a simulated environment.",
        ),
        identity_context=desc.get(
            "identity_context",
            "operating inside a deterministic simulated scenario.",
        ),
        notes_preamble=desc.get(
            "notes_preamble",
            "I am SELF operating in a deterministic simulation scenario. I verify state observations and respect operating limits.",
        ),
        body_rules=body_rules,
        pre_capability_rules=desc.get("pre_capability_rules", body_rules[:1]),
        post_capability_rules=desc.get("post_capability_rules", body_rules[1:]),
    )


def build_sim_capabilities(scenario: dict[str, Any]) -> list[Capability]:
    """Return the concrete capabilities exposed by the active scenario."""
    actions_def = scenario.get("actions", {})
    caps: list[Capability] = []
    for name, spec in sorted(actions_def.items()):
        caps.append(
            Capability(
                name=name,
                schema=spec.get("input_schema", {"type": "object", "properties": {}}),
                risk_class=spec.get("risk_class", "writes"),
                reversible=bool(spec.get("reversible", False)),
            )
        )
    return caps
