"""Plugin SDK Command-Line Interface (CLI).

Provides commands:
  - new: Scaffold a new plugin skeleton from plugins/_template.
  - validate: Statically validate plugin manifest, schema, permissions, and tests.
  - list: List discovered plugins, enablement status, and hash pinning status.
  - check: Statically check compatibility of all plugins against the core API version.

This module is strictly static: it never imports or executes untrusted plugin code.
"""
from __future__ import annotations

import sys

from agent.plugins.sdk_cli import (
    RESERVED_PLUGIN_NAMES,
    _find_template_dir,
    _read_config_static,
    _render_validation_result,
    build_parser,
    cmd_check,
    cmd_list,
    cmd_new,
    cmd_validate,
    main,
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

if __name__ == "__main__":
    sys.exit(main())
