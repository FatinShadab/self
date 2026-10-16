"""Preserve the legacy event logging import path."""

# Compatibility shim: implementation lives in agent.infra.event_log.
from agent.infra.event_log import *  # noqa: F401,F403
