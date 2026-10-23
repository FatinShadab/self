"""Tool and model response narration formatters using an extensible handler registry."""
from __future__ import annotations

from typing import Any, Callable
from urllib.parse import urlsplit

from agent.infra.event_log import EventLogger

TOOL_NARRATORS: dict[str, Callable[[dict[str, Any], EventLogger], str]] = {
    "run_shell": lambda args, logger: f"Running a shell action: {logger.redactor.text(args.get('cmd', ''))[:180]}",
    "read_file": lambda args, logger: f"Reading {args.get('path', 'a file')}...",
    "write_file": lambda args, logger: f"Writing {args.get('path', 'a file')}...",
    "list_dir": lambda args, logger: f"Listing {args.get('path', 'a directory')}...",
    "http_get": lambda args, logger: f"Fetching {urlsplit(str(args.get('url', ''))).hostname or 'a host'}{urlsplit(str(args.get('url', ''))).path or '/'}...",
    "update_environment_map": lambda args, logger: "Updating the verified environment map...",
    "read_plan": lambda args, logger: "Reviewing the current persistent plan...",
    "update_plan": lambda args, logger: f"Updating plan ({str(args.get('action', 'update'))}): {str(args.get('reason', ''))[:100]}...",
    "propose_core_patch": lambda args, logger: "Saving a core-change proposal for human review...",
    "read_cost_ledger": lambda args, logger: "Reviewing measured cost baselines in the ledger...",
    "propose_plugin": lambda args, logger: f"Submitting proposal for plugin {args.get('name', 'project')}...",
    "scaffold_plugin": lambda args, logger: f"Scaffolding plugin draft {args.get('name', 'project')} in workspace/plugin_dev/...",
    "validate_plugin": lambda args, logger: f"Statically validating plugin draft {args.get('name', 'project')}...",
    "test_plugin": lambda args, logger: f"Running isolated tests for plugin draft {args.get('name', 'project')}...",
    "request_plugin_review": lambda args, logger: f"Requesting strict critic review for plugin {args.get('name', 'project')}...",
    "opencode_status": lambda args, logger: "Checking opencode availability status...",
    "delegate_coding": lambda args, logger: f"Delegating coding task to opencode in sandbox: {str(args.get('route_reasons', ''))[:120]}...",
    "apply_delegation": lambda args, logger: f"Applying opencode delegation {args.get('delegation_id', '')} to repository...",
    "discard_delegation": lambda args, logger: f"Discarding opencode delegation {args.get('delegation_id', '')}...",
    "record_build_route": lambda args, logger: f"Recording build route decision ({args.get('route', '')}): {str(args.get('reasons', ''))[:100]}...",
    "record_build_outcome": lambda args, logger: f"Recording build outcome for {args.get('task_id', '')}: {args.get('result', '')}...",
    "build_route_stats": lambda args, logger: "Reviewing build route performance history and balance stats...",
}


def format_tool_narration(name: str, arguments: dict[str, Any], logger: EventLogger) -> str:
    """Return user-facing narration text for a tool execution."""
    narrator = TOOL_NARRATORS.get(name)
    if narrator is not None:
        return narrator(arguments, logger)
    return f"Using {name}..."


def format_content_narration(content: list[dict[str, Any]], logger: EventLogger) -> str:
    """Extract and log text blocks from model response content."""
    reports: list[str] = []
    for block in content:
        if block.get("type") != "text":
            continue
        text = str(block.get("text", "")).strip()
        if not text:
            continue
        reports.append(text)
        logger.log("agent_step", message=logger.redactor.text(text[:4_000]))
    return "\n".join(reports)
