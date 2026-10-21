"""Command-line script for Prompt 14 schema migration and byte-for-byte restore."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Add repo root to sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.infra.migration import run_migration_p14, restore_migration_p14


def main() -> int:
    parser = argparse.ArgumentParser(description="Prompt 14 plugin-tagged state migration and restore.")
    parser.add_argument("--workspace", default="workspace", help="Path to workspace directory (default: workspace)")
    parser.add_argument("--restore", help="Path to backup directory to restore pre-migration files byte-for-byte")
    parser.add_argument("--backup-dir", help="Explicit backup destination directory")

    args = parser.parse_args()

    if args.restore:
        print(f"Restoring pre-migration state from: {args.restore}")
        try:
            result = restore_migration_p14(args.workspace, args.restore)
            print("Restore succeeded! Byte-for-byte verification passed.")
            print(json.dumps(result, indent=2))
            return 0
        except Exception as exc:
            print(f"Restore failed: {exc}", file=sys.stderr)
            return 1
    else:
        print(f"Running Prompt 14 migration on workspace: {args.workspace}")
        try:
            result = run_migration_p14(args.workspace, backup_dir=args.backup_dir)
            print("Migration completed successfully!")
            print(json.dumps(result, indent=2))
            return 0
        except Exception as exc:
            print(f"Migration failed: {exc}", file=sys.stderr)
            return 1


if __name__ == "__main__":
    sys.exit(main())
