"""Trivial headless probe execution for opencode providers."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Callable

from agent.opencode.provider_status.classification import (
    classify_failure,
    parse_reset_time,
)
from agent.opencode.provider_status.constants import (
    PROVIDER_ENV_VARS,
    PROVIDER_STANDARD_ENV,
)
from agent.opencode.provider_status.storage import load_config


def execute_probe(
    provider: str,
    binary_path: str,
    config_path: Path | None,
    runner_fn: Callable[..., subprocess.CompletedProcess],
    on_success: Callable[[str], None],
    on_failure: Callable[[str, str, str, float | None], None],
) -> bool:
    """Run a trivial headless opencode probe for *provider*.

    Probes are the ONLY way a throttled provider returns to available.
    Returns True if probe succeeded, False otherwise.
    """
    env_var = PROVIDER_ENV_VARS.get(provider, "")
    key = os.environ.get(env_var, "").strip() if env_var else ""
    if not key:
        on_failure(provider, "invalid_key", f"No API key in {env_var}", None)
        return False

    config = load_config(config_path)
    models = config.get("models", [])
    chosen_model = None
    for m in models:
        if isinstance(m, str) and m.startswith(f"{provider}/") and not m.startswith("_PLACEHOLDER"):
            chosen_model = m
            break

    cmd = [binary_path, "run", "--auto", "--standalone"]
    if chosen_model:
        cmd.extend(["--model", chosen_model])
    cmd.append("reply with the single word OK")

    env = {
        "PATH": os.environ.get("PATH", ""),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "HOME": os.environ.get("HOME", "/tmp"),
    }
    std_var = PROVIDER_STANDARD_ENV.get(provider)
    if std_var:
        env[std_var] = key

    try:
        res = runner_fn(
            cmd,
            capture_output=True,
            text=True,
            timeout=45,
            env=env,
        )
        output = (res.stdout or "") + " " + (res.stderr or "")
        category = classify_failure(res.returncode, output)
        if category == "ok":
            on_success(provider)
            return True
        else:
            reset_sec = parse_reset_time(output)
            on_failure(provider, category, output[:200], reset_sec)
            return False
    except subprocess.TimeoutExpired:
        on_failure(provider, "transient", "Probe timed out after 45s", None)
        return False
    except (OSError, Exception) as exc:
        on_failure(provider, "transient", f"Probe execution error: {exc}", None)
        return False
