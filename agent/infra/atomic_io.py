"""Atomic file I/O operations using temporary files and atomic replace."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def atomic_write_text(path: Path | str, content: str, *, encoding: str = "utf-8", suffix: str = ".tmp") -> None:
    """Atomically write text to path using a temporary sibling file and os.replace."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target.with_suffix(suffix)
    try:
        temp_path.write_text(content, encoding=encoding)
        os.replace(temp_path, target)
    finally:
        temp_path.unlink(missing_ok=True)


def atomic_write_json(path: Path | str, data: Any, *, indent: int = 2, sort_keys: bool = False,
                      ensure_ascii: bool = True, encoding: str = "utf-8") -> None:
    """Atomically write JSON data to path formatted with standard trailing newline."""
    text = json.dumps(data, indent=indent, sort_keys=sort_keys, ensure_ascii=ensure_ascii) + "\n"
    atomic_write_text(path, text, encoding=encoding)
