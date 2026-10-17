"""Append-only audit trail with SHA-256 hash chaining.

Each record is cryptographically linked to the previous record's hash.
Integrity can be validated offline by verifying the sequential hash chain.

Caveat:
In the default Docker profile, the container process runs as root and could
rewrite this file if malicious. Under the hardened profile, the container runs
as a non-root user with a read-only root filesystem, but the state volume remains
writable for legitimate state persistence.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

GENESIS_HASH = "0" * 64


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_bytes(payload: dict[str, Any]) -> bytes:
    """Return canonical JSON bytes (sorted keys, compact separators) for hashing."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


class AuditTrail:
    """Append-only action audit trail with SHA-256 hash chaining."""

    def __init__(self, path: Path | str, logger: Any | None = None) -> None:
        self.path = Path(path).resolve()
        self.logger = logger
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._last_hash = self._recover_last_hash()
        self._next_seq = self._count_entries() + 1

    def _recover_last_hash(self) -> str:
        """Read the last line from the audit log to resume the chain."""
        if not self.path.exists() or self.path.stat().st_size == 0:
            return GENESIS_HASH
        try:
            with self.path.open("rb") as handle:
                handle.seek(0, os.SEEK_END)
                pos = handle.tell()
                if pos == 0:
                    return GENESIS_HASH
                # Search backwards for last non-empty line
                buffer = bytearray()
                while pos > 0:
                    pos -= 1
                    handle.seek(pos)
                    byte = handle.read(1)
                    if byte == b"\n" and buffer:
                        break
                    if byte != b"\n":
                        buffer.extend(byte)
                last_line = bytes(reversed(buffer)).decode("utf-8", errors="replace").strip()
                if not last_line:
                    return GENESIS_HASH
                data = json.loads(last_line)
                return str(data.get("entry_hash", GENESIS_HASH))
        except (OSError, json.JSONDecodeError):
            return GENESIS_HASH

    def _count_entries(self) -> int:
        if not self.path.exists():
            return 0
        try:
            with self.path.open("r", encoding="utf-8", errors="replace") as handle:
                return sum(1 for line in handle if line.strip())
        except OSError:
            return 0

    def append(
        self,
        event: str,
        action: str = "",
        source: str = "",
        level: str = "",
        reversibility: bool = False,
        **extra: Any,
    ) -> str:
        """Append an event to the audit trail and return the calculated entry hash."""
        seq = self._next_seq
        self._next_seq += 1

        record: dict[str, Any] = {
            "seq": seq,
            "timestamp": _now_utc(),
            "event": event,
            "action": action,
            "source": source,
            "level": level,
            "reversibility": reversibility,
            "prev_hash": self._last_hash,
            "details": extra,
        }

        entry_hash = hashlib.sha256(_canonical_bytes(record)).hexdigest()
        record["entry_hash"] = entry_hash

        line = json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n"
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line)

        self._last_hash = entry_hash
        return entry_hash

    def verify(self) -> tuple[bool, int, str]:
        """Verify the cryptographic integrity of the hash chain.

        Returns (is_valid, entries_checked, message).
        """
        if not self.path.exists() or self.path.stat().st_size == 0:
            return True, 0, "Audit trail is empty; chain is intact."

        expected_prev = GENESIS_HASH
        count = 0

        with self.path.open("r", encoding="utf-8", errors="replace") as handle:
            for lineno, line in enumerate(handle, start=1):
                raw = line.strip()
                if not raw:
                    continue
                try:
                    entry = json.loads(raw)
                except json.JSONDecodeError as exc:
                    return False, count, f"Line {lineno}: JSON decode error: {exc}"

                stored_hash = entry.get("entry_hash", "")
                stored_prev = entry.get("prev_hash", "")
                seq = entry.get("seq", 0)

                if seq != count + 1:
                    return False, count, f"Line {lineno}: sequence mismatch (expected {count + 1}, got {seq})"

                if stored_prev != expected_prev:
                    return (
                        False,
                        count,
                        f"Line {lineno}: broken hash chain — prev_hash mismatch "
                        f"(expected {expected_prev[:16]}..., got {stored_prev[:16]}...)",
                    )

                # Recompute hash
                payload = dict(entry)
                payload.pop("entry_hash", None)
                computed_hash = hashlib.sha256(_canonical_bytes(payload)).hexdigest()

                if computed_hash != stored_hash:
                    return (
                        False,
                        count,
                        f"Line {lineno}: payload tampering detected — entry_hash mismatch "
                        f"(computed {computed_hash[:16]}..., stored {stored_hash[:16]}...)",
                    )

                expected_prev = stored_hash
                count += 1

        return True, count, f"Verified {count} audit trail entries; hash chain is intact."
