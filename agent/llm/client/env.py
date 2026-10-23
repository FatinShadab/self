"""Environment variable reading and key parsing helpers."""
from __future__ import annotations

import json
import os
import re
from typing import Any


def _first_env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return None


def _env_key_list(*names: str) -> list[str]:
    """Read comma-, semicolon-, newline-, or JSON-array-separated keys."""
    keys: list[str] = []
    for name in names:
        raw = os.getenv(name, "").strip()
        if not raw:
            continue
        values: list[Any] | None = None
        if raw.startswith("["):
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    values = parsed
            except json.JSONDecodeError:
                values = None
        if values is None:
            values = re.split(r"[,;\r\n]+", raw)
        for value in values:
            cleaned = str(value).strip().strip('"').strip("'")
            if cleaned and cleaned not in keys:
                keys.append(cleaned)
    return keys
