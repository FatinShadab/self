"""Permission level hierarchy and parsing."""
from __future__ import annotations

import enum
from typing import Any


class PermissionLevel(enum.IntEnum):
    """Permission level hierarchy:
    - L0: observe (read-only, no side-effects)
    - L1: reversible change (quarantine, plan updates, reversible edits)
    - L2: destructive / irreversible (run_shell, file overwrites/deletions)
    - L3: physical actuation (hardware/robotic movement or triggers)
    """
    L0 = 0
    L1 = 1
    L2 = 2
    L3 = 3

    @classmethod
    def from_value(cls, val: Any) -> PermissionLevel:
        """Parse permission level from int, string ('L0', '0', 'observe', etc.)."""
        if isinstance(val, PermissionLevel):
            return val
        if isinstance(val, int):
            return cls(min(3, max(0, val)))
        s = str(val).strip().upper()
        if s in {"L0", "0", "OBSERVE", "READS", "READ_ONLY"}:
            return cls.L0
        if s in {"L1", "1", "REVERSIBLE", "QUARANTINE"}:
            return cls.L1
        if s in {"L2", "2", "DESTRUCTIVE", "IRREVERSIBLE", "WRITES", "EXECUTES"}:
            return cls.L2
        if s in {"L3", "3", "PHYSICAL", "ACTUATION"}:
            return cls.L3
        return cls.L0
