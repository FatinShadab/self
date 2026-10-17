"""Command-line script to migrate old subservient/shared framing out of workspace/state/memory.jsonl."""
from __future__ import annotations

import json
from agent.learning.memory_migration import migrate_memory_store

if __name__ == "__main__":
    result = migrate_memory_store("workspace")
    print(json.dumps(result, indent=2))
