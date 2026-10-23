"""Provider candidate resolution and opencode installation detection."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any


def is_opencode_installed(binary_path: str | Path) -> bool:
    """Check if opencode executable is present and accessible."""
    p = Path(binary_path)
    if p.exists():
        return True
    return shutil.which(str(binary_path)) is not None


def load_configured_models(config_path: Path) -> list[str]:
    """Read ordered models list from config.json."""
    if config_path.is_file():
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
            models = data.get("models", [])
            return [
                m
                for m in models
                if isinstance(m, str) and not m.startswith("_PLACEHOLDER") and "/" in m
            ]
        except (OSError, json.JSONDecodeError):
            pass
    return []


def resolve_provider_candidates(
    requested_model: str | None,
    usability_providers: dict[str, Any],
    configured_models: list[str],
) -> list[tuple[str, str | None]]:
    """Order candidate (provider, model) pairs according to usability."""
    candidates: list[tuple[str, str | None]] = []
    seen_providers: set[str] = set()

    def is_provider_usable(pname: str) -> bool:
        pst = usability_providers.get(pname, {}).get("state", "unknown")
        return pst in ("available", "unknown", "probe_due")

    # 1. Requested model first if provided
    if requested_model and "/" in requested_model:
        req_prov = requested_model.split("/", 1)[0].lower()
        if is_provider_usable(req_prov):
            candidates.append((req_prov, requested_model))
            seen_providers.add(req_prov)

    # 2. Configured models in order
    for m in configured_models:
        p = m.split("/", 1)[0].lower()
        if p not in seen_providers and is_provider_usable(p):
            candidates.append((p, m))
            seen_providers.add(p)

    # 3. Any remaining usable providers without explicit model
    for p in ("groq", "google", "huggingface"):
        if p not in seen_providers and is_provider_usable(p):
            candidates.append((p, None))
            seen_providers.add(p)

    return candidates
