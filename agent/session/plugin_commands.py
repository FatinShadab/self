"""Human CLI commands for managing plugins and proposals."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable


def handle_plugins_command(plugins: Any, command: str) -> str:
    """Handle human-only /plugins commands for listing, enabling, and disabling plugins."""
    cmd = command.strip()
    if cmd in {"/plugins", "/plugins list"}:
        plugins.discover()
        cfg = plugins.read_config().get("plugins", {})
        if not plugins.discovered:
            return "No plugins discovered in image /opt/agent/plugins or workspace/plugins/."
        lines = ["**Discovered Plugins:**\n"]
        for name, p in sorted(plugins.discovered.items()):
            entry = cfg.get(name, {})
            status = "ENABLED" if entry.get("enabled") else "DISABLED"
            source = "shipped" if p.is_shipped else "workspace"
            h = entry.get("hash", "")
            h_str = f" [hash: {h[:12]}...]" if h else ""
            lines.append(f"- **{name}** (v{p.manifest.version}, {p.manifest.kind}, {source}): [{status}]{h_str}")
            lines.append(f"  {p.manifest.description}")
            if p.manifest.tools:
                tool_names = [f"{name}.{t['name']}" for t in p.manifest.tools]
                lines.append(f"  Tools: {', '.join(tool_names)}")
        return "\n".join(lines)

    if cmd.startswith("/plugins enable "):
        name = cmd.removeprefix("/plugins enable ").strip()
        if not name:
            return "Usage: /plugins enable <name>"
        try:
            res = plugins.enable_by_human(name)
            p = plugins.discovered.get(name)
            perm_summary: dict[str, Any] = {}
            if p and p.manifest:
                for t in p.manifest.tools:
                    perm_summary[f"{name}.{t.get('name')}"] = {
                        "permission_level": t.get("permission_level", "L0"),
                        "risk_classes": t.get("risk_classes", []),
                    }
            perm_text = json.dumps(perm_summary, indent=2) if perm_summary else "No tools declared."
            return (
                f"Plugin '{name}' enabled (hash pinned: {res['hash'][:12]}...).\n"
                f"Permission requests:\n{perm_text}\n"
                f"Takes effect at the next cycle boundary."
            )
        except PermissionError:
            return f"Cannot enable plugin '{name}': /config/plugins.json is mounted read-only (human host config). Please edit ./config/plugins.json on host."
        except Exception as exc:
            return f"Could not enable plugin '{name}': {exc}"

    if cmd.startswith("/plugins disable "):
        name = cmd.removeprefix("/plugins disable ").strip()
        if not name:
            return "Usage: /plugins disable <name>"
        try:
            plugins.disable_by_human(name)
            return f"Plugin '{name}' disabled. Takes effect at the next cycle boundary."
        except PermissionError:
            return f"Cannot disable plugin '{name}': /config/plugins.json is mounted read-only. Please edit ./config/plugins.json on host."
        except Exception as exc:
            return f"Could not disable plugin '{name}': {exc}"

    if cmd.startswith("/plugins promote "):
        name = cmd.removeprefix("/plugins promote ").strip()
        if not name:
            return "Usage: /plugins promote <name>"
        from agent.plugins.self_dev import PluginDevManager
        dev = PluginDevManager(plugins.workspace, plugins.logger)
        res = dev.promote_draft_by_human(name)
        if not res.get("ok"):
            return f"Could not promote plugin '{name}': {res.get('error')}"
        diff_summary = res.get("diff", "")
        perm_summary = res.get("permission_summary", {})
        return (
            f"Plugin '{name}' promoted to workspace/plugins/{name} as DISABLED.\n"
            f"Permission requests: {json.dumps(perm_summary, indent=2)}\n"
            f"Review diff:\n{diff_summary[:2000]}\n\n"
            f"To enable this plugin, run: /plugins enable {name}"
        )

    return "Unknown plugins command. Usage: /plugins list, /plugins enable <name>, /plugins disable <name>, /plugins promote <name>"


def handle_proposals_command(
    workspace: Path,
    logger: Any,
    command: str = "/proposals",
    receive_input_fn: Callable[[str, str], None] | None = None,
) -> str:
    """Display plugin proposals from state/plugin_proposals.jsonl or record comments."""
    cmd = command.strip()
    parts = cmd.split(maxsplit=3)
    from agent.plugins.self_dev import PluginDevManager
    dev = PluginDevManager(workspace, logger)

    if len(parts) >= 4 and parts[1] == "comment":
        target_name = parts[2]
        comment_text = parts[3]
        if receive_input_fn is not None:
            receive_input_fn(f"[Proposal comment on '{target_name}'] {comment_text}", "proposal_comment")
        return f"Comment on proposal '{target_name}' submitted to agent inbox as advice to weigh."

    proposals = dev.list_proposals()
    if not proposals:
        return "No plugin proposals recorded in state/plugin_proposals.jsonl."

    lines = ["**Plugin Proposals:**\n"]
    for p in proposals:
        p_name = p.get("name", "unknown")
        status = p.get("status", "proposed")
        need = p.get("need", "")
        est = p.get("estimate", {})
        tokens_range = est.get("tokens", {})
        cycles_range = est.get("cycles", {})
        lines.append(f"- **{p_name}** [{status}] (tokens: {tokens_range}, cycles: {cycles_range})")
        lines.append(f"  Need: {need}")
        lines.append(f"  Derivation: {est.get('derivation', '')}")
        lines.append(f"  Expected benefit: {p.get('expected_benefit', '')}")
    lines.append("\nTo comment on a proposal: /proposals comment <name> <your comment>")
    return "\n".join(lines)


def handle_slash_command(plugins: Any, text: str) -> str | None:
    """Dispatch a human-facing slash command to active plugins."""
    if plugins is not None and hasattr(plugins, "handle_slash_command"):
        return plugins.handle_slash_command(text)
    return None


__all__ = [
    "handle_plugins_command",
    "handle_proposals_command",
    "handle_slash_command",
]
