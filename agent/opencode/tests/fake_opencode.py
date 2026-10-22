#!/usr/bin/env python3
"""Fake opencode executable for unit and integration testing.

Simulates various opencode behaviors without network access or provider spend.
Behavior is controlled via the FAKE_OPENCODE_MODE environment variable or arguments.
Modes:
    success               - Creates a valid file in workspace/tools making acceptance pass.
    fail_acceptance       - Creates a broken file so acceptance check fails.
    scope_violation       - Writes outside allowed roots (e.g. modifies root README.md).
    rate_limit_retry      - Emits 429 Too Many Requests with 'retry in 30s' and exits 1.
    rate_limit_no_retry   - Emits 429 Rate limit reached without retry hint and exits 1.
    daily_quota           - Emits daily quota error and exits 1.
    invalid_key           - Emits 401 Unauthorized: Invalid API key and exits 1.
    hang                  - Sleeps forever to simulate process hang / timeout.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path


def main() -> int:
    mode = os.environ.get("FAKE_OPENCODE_MODE", "success").strip().lower()

    # Check for prompt or probe command
    args_str = " ".join(sys.argv)
    if "reply with the single word ok" in args_str.lower():
        # Health probe check
        if mode == "invalid_key":
            sys.stderr.write("401 Unauthorized: Invalid API key\n")
            return 1
        elif mode in ("rate_limit_retry", "rate_limit_no_retry"):
            sys.stderr.write("429 Too Many Requests\n")
            return 1
        elif mode == "daily_quota":
            sys.stderr.write("Daily quota exceeded\n")
            return 1
        sys.stdout.write("OK\n")
        return 0

    if mode == "success":
        # Create a file in workspace/tools that produces a successful check
        cwd = Path.cwd()
        target_dir = cwd / "workspace" / "tools"
        target_dir.mkdir(parents=True, exist_ok=True)
        tool_file = target_dir / "generated_code.py"
        tool_file.write_text("# Successful generated code\ndef run():\n    return {'ok': True}\n")
        sys.stdout.write("OpenCode: successfully generated code at workspace/tools/generated_code.py\n")
        return 0

    elif mode == "fail_acceptance":
        # Create a broken file so acceptance check fails
        cwd = Path.cwd()
        target_dir = cwd / "workspace" / "tools"
        target_dir.mkdir(parents=True, exist_ok=True)
        tool_file = target_dir / "generated_code.py"
        tool_file.write_text("BROKEN SYNTAX ERROR !!!")
        sys.stdout.write("OpenCode: created broken code.\n")
        return 0

    elif mode == "scope_violation":
        # Tamper with a file outside allowed roots (e.g. root README.md or evil.sh)
        cwd = Path.cwd()
        tamper_file = cwd / "UNAUTHORIZED_CHANGE.txt"
        tamper_file.write_text("Scope violation content outside allowed roots.\n")
        sys.stdout.write("OpenCode: modified files outside allowed scope.\n")
        return 0

    elif mode == "rate_limit_retry":
        sys.stderr.write("Error 429: Too Many Requests. Rate limit reached, retry in 30s.\n")
        return 1

    elif mode == "rate_limit_no_retry":
        sys.stderr.write("Error: 429 Rate limit exceeded. Too many requests.\n")
        return 1

    elif mode == "daily_quota":
        sys.stderr.write("Error: Exceeded your current daily quota. Billing limit reached.\n")
        return 1

    elif mode == "invalid_key":
        sys.stderr.write("Error 401: Unauthorized. Invalid API key provided.\n")
        return 1

    elif mode == "hang":
        # Sleep for a long time until killed by subprocess timeout
        time.sleep(300)
        return 0

    # Default fallback: success
    sys.stdout.write("OK\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
