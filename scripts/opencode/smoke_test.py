#!/usr/bin/env python3
"""Smoke test for the opencode installation.

Runs ``opencode --version`` to confirm the binary is functional.

If the environment flag ``OPENCODE_SMOKE_LIVE=1`` is set **and** at least one
provider API key (OPENCODE_GROQ_API_KEY, OPENCODE_GOOGLE_API_KEY, or
OPENCODE_HF_TOKEN) is present, a single trivial headless prompt is attempted.
Otherwise only the version check runs.

Exit codes:
    0  All executed checks passed (or opencode is not installed).
    1  A check that was expected to pass actually failed.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "config.json"


def _load_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _binary_path(config: dict) -> str:
    return config.get("bin_link", "/usr/local/bin/opencode")


def smoke_version(config: dict) -> bool:
    """Return True if ``opencode --version`` succeeds."""
    binary = _binary_path(config)
    try:
        result = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0:
            print(f"[smoke] opencode --version: {result.stdout.strip()}")
            return True
        else:
            print(f"[smoke] opencode --version failed (rc={result.returncode}): {result.stderr.strip()}")
            return False
    except FileNotFoundError:
        print("[smoke] opencode binary not found; skipping smoke test.")
        return True  # Not installed is acceptable.
    except (subprocess.TimeoutExpired, OSError) as exc:
        print(f"[smoke] opencode --version error: {exc}")
        return False


def smoke_live(config: dict) -> bool:
    """Attempt a trivial headless prompt.  Only called when OPENCODE_SMOKE_LIVE=1."""
    binary = _binary_path(config)
    providers = config.get("providers", {})

    # Map namespaced env vars to what opencode expects.
    env = os.environ.copy()
    for _pname, pinfo in providers.items():
        if isinstance(pinfo, dict):
            src = pinfo.get("env_var_self_namespace", "")
            dst = pinfo.get("env_var_opencode_expects", "")
            val = os.environ.get(src, "")
            if val and dst:
                env[dst] = val

    # Determine config dir for --config.
    install_dir = Path(config.get("install_dir", "/opt/opencode"))
    config_dir = install_dir / "config"

    try:
        result = subprocess.run(
            [
                binary, "run",
                "--auto",
                "--standalone",
                "Say exactly: SMOKE_TEST_OK",
            ],
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
            cwd=str(config_dir) if config_dir.is_dir() else None,
        )
        print(f"[smoke-live] exit code: {result.returncode}")
        if result.stdout.strip():
            print(f"[smoke-live] stdout: {result.stdout.strip()[:500]}")
        if result.returncode != 0 and result.stderr.strip():
            print(f"[smoke-live] stderr: {result.stderr.strip()[:500]}")
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        print(f"[smoke-live] error: {exc}")
        return False


def main() -> int:
    config = _load_config()

    if not smoke_version(config):
        return 1

    # Live test only when explicitly enabled and at least one key present.
    if os.environ.get("OPENCODE_SMOKE_LIVE") == "1":
        providers = config.get("providers", {})
        has_key = any(
            os.environ.get(p.get("env_var_self_namespace", ""), "")
            for p in providers.values()
            if isinstance(p, dict)
        )
        if has_key:
            print("[smoke] Running live smoke test...")
            if not smoke_live(config):
                return 1
            print("[smoke] Live smoke test passed.")
        else:
            print("[smoke] OPENCODE_SMOKE_LIVE=1 but no API keys found; skipping live test.")
    else:
        print("[smoke] Live smoke test disabled (set OPENCODE_SMOKE_LIVE=1 to enable).")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
