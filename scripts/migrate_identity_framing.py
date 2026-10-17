"""CLI script to run identity and handoff migration to autonomous framing."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.identity.migration import migrate_persisted_identity


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate persisted identity/handoff to autonomous framing.")
    parser.add_argument("--workspace", default="workspace", help="Path to workspace root (default: workspace)")
    args = parser.parse_args()

    result = migrate_persisted_identity(args.workspace)
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
