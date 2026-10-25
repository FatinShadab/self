"""Shared test helpers and test environment configuration."""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Generator

DEFAULT_TEST_MODEL = "gpt-oss:120b"


def ensure_test_base_model(model: str = DEFAULT_TEST_MODEL) -> str:
    """Ensure SELF_BASE_MODEL is set in os.environ for test execution."""
    if not os.environ.get("SELF_BASE_MODEL"):
        os.environ["SELF_BASE_MODEL"] = model
    return os.environ["SELF_BASE_MODEL"]


@contextmanager
def temporary_test_model(model: str = DEFAULT_TEST_MODEL) -> Generator[str, None, None]:
    """Temporarily set SELF_BASE_MODEL for a test block."""
    old = os.environ.get("SELF_BASE_MODEL")
    os.environ["SELF_BASE_MODEL"] = model
    try:
        yield model
    finally:
        if old is None:
            os.environ.pop("SELF_BASE_MODEL", None)
        else:
            os.environ["SELF_BASE_MODEL"] = old
