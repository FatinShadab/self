"""Constants, schemas, and environment limit parsers for the model registry."""
from __future__ import annotations

import os

MAX_MODELS = 32
MAX_NAME_CHARS = 160
MAX_ASSESSMENT_CHARS = 2_000
MAX_EVIDENCE_CHARS = 1_000
MAX_NOTES_CHARS = 1_000
MAX_COUNTER = 1_000_000_000
MAX_FILE_BYTES = 1_000_000
MAX_PROBES_PER_SESSION = 2
PROBE_COOLDOWN_SECONDS = 3_600
SCHEMA_VERSION = 3
PROBE_FORMAT_VERSION = 2
LEGACY_PROBE_INVALIDATION_REASON = (
    "Earlier probe output caps did not account for hidden thinking or provider truncation."
)
RATING_CATEGORIES = (
    "reasoning",
    "code",
    "instruction_following",
    "summarization",
    "json_output",
)
RATING_VALUES = {"low", "medium", "high", "unknown"}
DEFAULT_MODEL_OUTPUT_CEILING = 32_768


def env_limit(name: str, default: int, minimum: int, maximum: int) -> int:
    """Parse an integer environment limit clamped between minimum and maximum."""
    try:
        return max(minimum, min(maximum, int(os.getenv(name, str(default)))))
    except ValueError:
        return default
