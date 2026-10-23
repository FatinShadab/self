"""Identity prompt context rendering and TUI panel formatting."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent.identity.store.constants import IDENTITY_CONTEXT_MAX_CHARS
from agent.prompts.identity import render_identity_prompt_context


def build_identity_prompt_context(
    identity: dict[str, Any],
    active_plugins: Any,
    redactor: Any,
) -> str:
    """Format bounded identity context JSON and embodiment notes for model prompts."""
    raw_interests = identity.get("interests", [])
    filtered_interests: list[str] = []
    for it in raw_interests:
        if isinstance(it, dict):
            p = it.get("plugin", "core")
            if active_plugins is not None and p != "core" and p not in active_plugins:
                continue
            filtered_interests.append(str(it.get("interest") or it.get("text", "")))
        else:
            filtered_interests.append(str(it))

    compact = {
        "name": identity["name"],
        "human_name": identity["human_name"],
        "name_context": identity["name_context"],
        "traits": identity["traits"][-12:],
        "values": identity["values"][-12:],
        "voice": identity["voice"],
        "interests": filtered_interests[-12:],
        "open_questions_about_self": identity["open_questions_about_self"][-12:],
    }
    redacted_compact = redactor.value(compact) if hasattr(redactor, "value") else compact
    text = json.dumps(redacted_compact, ensure_ascii=False, indent=2)

    plugin_notes: list[str] = []
    if active_plugins:
        embodiments = identity.get("plugin_embodiments", {})
        if isinstance(embodiments, dict):
            for p_name in sorted(active_plugins):
                if p_name in embodiments and embodiments[p_name]:
                    plugin_notes.append(f"[{p_name}] {embodiments[p_name]}")

    embodiment_block = ""
    if plugin_notes:
        embodiment_block = "\n\n## Active plugin embodiment notes:\n" + "\n".join(plugin_notes)

    return render_identity_prompt_context(
        text[:IDENTITY_CONTEXT_MAX_CHARS],
        embodiment_block,
    )


def format_self_panel_text(identity: dict[str, Any], log_path: Path) -> str:
    """Return identity summary and recent audit entries for the terminal UI."""
    traits = identity.get("traits", [])
    values = identity.get("values", [])
    try:
        raw_log = log_path.read_text(encoding="utf-8", errors="replace")
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
