"""Fixed, bounded model probes and conservative official-document research."""
from __future__ import annotations

import subprocess
import time
from typing import Any, Callable

from agent.helper_models.probes.code_check import (
    CODE_TIMEOUT_SECONDS,
    _CODE_RUNNER,
    execute_code_check,
)
from agent.helper_models.probes.fact_extraction import extract_model_facts
from agent.helper_models.probes.official_docs import (
    FETCH_CAP,
    _Text,
    fetch_official_page,
    official_url as _official_url,
)
from agent.helper_models.probes.probe_execution import (
    INCONCLUSIVE_NOTE,
    OUTPUT_CAP,
    check_case_output,
    execute_model_probe,
    not_found_error as _not_found,
)
from agent.helper_models.probes.research_execution import execute_model_research
from agent.infra.event_log import EventLogger
from agent.llm.model_registry import ModelRegistry
from agent.prompts.probes import PROBE_CASES, PROBE_SYSTEM_PROMPT

__all__ = [
    "CODE_TIMEOUT_SECONDS",
    "FETCH_CAP",
    "INCONCLUSIVE_NOTE",
    "ModelProber",
    "OUTPUT_CAP",
    "PROBE_CASES",
    "PROBE_SYSTEM_PROMPT",
    "_CODE_RUNNER",
    "_Text",
    "_not_found",
    "_official_url",
    "check_code_output",
    "extract_model_facts",
    "fetch_official_page",
]


def check_code_output(source: str, *, timeout: float = CODE_TIMEOUT_SECONDS) -> dict[str, Any]:
    """Run a narrowly validated pure arithmetic function in an empty process."""
    return execute_code_check(source, timeout=timeout, subprocess_run=subprocess.run)


class ModelProber:
    """Probe configured helper models and research their capabilities."""

    def __init__(
        self,
        registry: ModelRegistry,
        llm: Any,
        logger: EventLogger,
        session_id: str,
        provider: str,
        *,
        clock: Callable[[], float] = time.time,
        code_checker: Callable[[str], dict[str, Any]] = check_code_output,
        fetcher: Callable[[str, EventLogger], dict[str, Any]] = fetch_official_page,
    ) -> None:
        self.registry = registry
        self.llm = llm
        self.logger = logger
        self.session_id = session_id
        self.provider = provider
        self.clock = clock
        self.code_checker = code_checker
        self.fetcher = fetcher
        self.client_records_stats = (
            getattr(getattr(llm, "client", None), "model_registry", None) is registry
        )

    def probe_model(self, name: str) -> dict[str, Any]:
        """Probe a configured model and store observed capability results."""
        return execute_model_probe(self, name)

    def _check(self, kind: str, text: str) -> dict[str, Any]:
        return check_case_output(kind, text, self.code_checker)

    def research_model(
        self,
        name: str,
        *,
        facts: list[dict[str, Any]] | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Research official model information and save verified findings."""
        return execute_model_research(self, name, facts=facts)
