"""Allowlist management for container network egress filtering."""
from __future__ import annotations

import fnmatch
import logging
from pathlib import Path

logger = logging.getLogger("egress_proxy")


class Allowlist:
    """Manages allowed hosts loaded from an allowlist file."""

    def __init__(self, path: Path | str | None) -> None:
        self.path = Path(path) if path else None
        self.patterns: set[str] = set()
        self.reload()

    def reload(self) -> None:
        if not self.path or not self.path.exists():
            logger.warning(f"Allowlist file {self.path} not found; blocking all outbound requests.")
            self.patterns = set()
            return
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
            patterns = set()
            for line in lines:
                clean = line.split("#", 1)[0].strip().lower()
                if clean:
                    patterns.add(clean)
            self.patterns = patterns
            logger.info(f"Loaded {len(self.patterns)} egress allowlist patterns from {self.path}")
        except Exception as exc:
            logger.error(f"Failed to load allowlist from {self.path}: {exc}")

    def is_allowed(self, host: str) -> bool:
        host = host.lower().strip()
        # Remove port if present
        if ":" in host:
            host = host.split(":", 1)[0]
        for pattern in self.patterns:
            if pattern == host:
                return True
            if pattern.startswith("*.") and (host.endswith(pattern[1:]) or host == pattern[2:]):
                return True
            if fnmatch.fnmatch(host, pattern):
                return True
        return False
