"""Plugin SDK CLI implementation package."""
from __future__ import annotations

from agent.plugins.sdk_cli.checking import cmd_check
from agent.plugins.sdk_cli.listing import _read_config_static, cmd_list
from agent.plugins.sdk_cli.parser import build_parser, main
from agent.plugins.sdk_cli.scaffold import (
    RESERVED_PLUGIN_NAMES,
    _find_template_dir,
    cmd_new,
)
from agent.plugins.sdk_cli.validation import (
    _render_validation_result,
    cmd_validate,
)

__all__ = [
    "RESERVED_PLUGIN_NAMES",
    "_find_template_dir",
    "_read_config_static",
    "_render_validation_result",
    "build_parser",
    "cmd_check",
    "cmd_list",
    "cmd_new",
    "cmd_validate",
    "main",
]
