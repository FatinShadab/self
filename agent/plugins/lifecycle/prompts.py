"""Rendering clearly delimited system prompt sections for active plugins."""
from __future__ import annotations

from agent.plugins.lifecycle.models import Plugin


def render_embodiment_prompt(active_plugins: dict[str, Plugin]) -> str:
    """Render clearly delimited embodiment section for enabled plugins."""
    if not active_plugins:
        return ""
    lines = [
        "### Active Plugins Embodiment",
        "The following specialization plugins are enabled and extend your embodiment:",
    ]
    for name, plugin in sorted(active_plugins.items()):
        lines.append(f"\n[Plugin: {name}]")
        lines.append(plugin.manifest.embodiment)
    return "\n".join(lines) + "\n"


def render_goal_notes_prompt(active_plugins: dict[str, Plugin]) -> str:
    """Render clearly delimited goal notes and starting seeds for enabled plugins."""
    if not active_plugins:
        return ""
    lines = [
        "### Active Plugins Notes & Goal Seeds",
        "The following plugin-provided goals and identity notes apply while enabled:",
    ]
    for name, plugin in sorted(active_plugins.items()):
        lines.append(f"\n[Plugin: {name}]")
        if plugin.manifest.starting_goal_seeds:
            lines.append("Starting goal seeds:")
            for seed in plugin.manifest.starting_goal_seeds:
                lines.append(f"- {seed}")
        if plugin.manifest.identity_notes:
            lines.append("Identity notes:")
            for note in plugin.manifest.identity_notes:
                lines.append(f"- {note}")
    return "\n".join(lines) + "\n"
