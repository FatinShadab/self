"""SELF event log module."""
from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SECRET_NAME_MARKERS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")
SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b([a-z0-9_]*(?:api[_-]?key|token|secret|password|credential)[a-z0-9_]*)"
    r"[ \t]*([=:])[ \t]*([^\s&]+)"
)


class SecretRedactor:
    """Redacts known environment credentials before output leaves the process."""

    def __init__(self) -> None:
        values: set[str] = set()
        for name, value in os.environ.items():
            if value and len(value) >= 4 and any(marker in name.upper() for marker in SECRET_NAME_MARKERS):
                values.add(value)
        self._values = sorted(values, key=len, reverse=True)

    def known(self, value: Any) -> str:
        text = str(value)
        for secret in self._values:
            text = text.replace(secret, "<redacted>")
        return text

    def text(self, value: Any) -> str:
        text = self.known(value)
        return SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}{match.group(2)}<redacted>", text)

    def value(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, dict):
            return {str(key): self.value(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.value(item) for item in value]
        return value


class EventLogger:
    """Writes one JSON object per append-only log line."""

    def __init__(self, path: str | Path = "/home/entity/logs/actions.jsonl") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.redactor = SecretRedactor()
        self._lock = threading.Lock()
        self._listeners: list[Any] = []

    def add_listener(self, listener: Any) -> None:
        """Register an in-process observer (used by the optional TUI)."""
        self._listeners.append(listener)

    def _record_egress(self, record: dict[str, Any]) -> None:
        if record.get("event") != "network_request" or not record.get("host"):
            return
        path = self.path.parent.parent / "state" / "egress.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {"timestamp": record["timestamp"], "date": record["timestamp"][:10], "domain": record["host"], "method": record.get("method", ""), "path": record.get("path", "/"), "request_count": 1}
        fd = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            os.write(fd, (json.dumps(self.redactor.value(entry), separators=(",", ":")) + "\n").encode("utf-8"))
        finally:
            os.close(fd)

    def log(self, event: str, **data: Any) -> None:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event,
            **self.redactor.value(data),
        }
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
        with self._lock:
            descriptor = os.open(self.path, flags, 0o600)
            try:
                os.write(descriptor, line.encode("utf-8"))
            finally:
                os.close(descriptor)
        self._record_egress(record)
        for listener in list(self._listeners):
            try:
                listener(record)
            except Exception:
                # Observers must never prevent durable event logging.
                pass

    def narrate(self, message: str) -> None:
        clean = " ".join(self.redactor.text(message).split())
        if clean:
            print(f"[SELF] {clean[:500]}", flush=True)
            self.log("narration", message=clean[:500])
