#!/usr/bin/env python3
"""scripts/analyze_run.py - CLI entry point for 30-cycle autonomous run log analysis."""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure repo root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.reporting.run_analysis import analyze_run, main, print_report

if __name__ == "__main__":
    sys.exit(main())
