"""Readable formatter for model registry snapshots and routing decisions."""
from __future__ import annotations

import json
from typing import Any


def format_models_snapshot(snapshot: dict[str, Any]) -> str:
    """Readable /models view of registry evidence and recent decisions."""
    registry = snapshot.get("registry") or {}
    models = registry.get("models", []) if isinstance(registry, dict) else []
    lines = ["Model registry:"]
    if not models:
        lines.append("No model data yet.")
    for entry in models:
        stats = entry.get("measured_stats") or {}
        lines.append(
            f"- {entry.get('name', 'unknown')} ({entry.get('role', '?')}): "
            f"status={entry.get('status', 'unknown')}; "
            f"calls={stats.get('calls', 0)} failures={stats.get('failures', 0)}; "
            f"assessment={entry.get('agent_assessment') or 'none'}; "
            f"ratings={json.dumps(entry.get('ratings'), ensure_ascii=False, sort_keys=True)}; "
            f"measured_stats={json.dumps(stats, ensure_ascii=False, sort_keys=True)}"
        )
    lines.append("Last ten decisions:")
    decisions = snapshot.get("last_ten_decisions") or []
    if not decisions:
        lines.append("No decisions yet.")
    for row in decisions[-10:]:
        lines.append(
            f"- {row.get('source', '?')} → {row.get('model', '?')} "
            f"origin={row.get('origin', 'unknown')} task={row.get('task_type', '?')}"
        )
    return "\n".join(lines)


__all__ = [
    "format_models_snapshot",
]
