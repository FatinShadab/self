"""Command-line argument parser and dispatcher for Plugin SDK CLI."""
from __future__ import annotations

import argparse

from agent.plugins.sdk_cli.checking import cmd_check
from agent.plugins.sdk_cli.listing import cmd_list
from agent.plugins.sdk_cli.scaffold import cmd_new
from agent.plugins.sdk_cli.validation import cmd_validate


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for python -m agent.plugins."""
    parser = argparse.ArgumentParser(
        prog="python -m agent.plugins",
        description="SELF Plugin SDK CLI: scaffold, validate, list, and check plugins.",
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # new
    p_new = subparsers.add_parser("new", help="Scaffold a new plugin from plugins/_template.")
    p_new.add_argument("name", help="Name of the new plugin (alphanumeric, underscores, hyphens).")
    p_new.add_argument("--dest", "-d", default=None, help="Destination directory (default: ./plugins/<name> or ./<name>).")
    p_new.add_argument("--template", "-t", default=None, help="Custom template directory override.")

    # validate
    p_val = subparsers.add_parser("validate", help="Statically validate a plugin manifest and files.")
    p_val.add_argument("path", help="Path to plugin directory or plugin.json.")
    p_val.add_argument("--json", action="store_true", help="Emit machine-readable JSON output.")

    # list
    p_list = subparsers.add_parser("list", help="List discovered plugins and hash pinning status.")
    p_list.add_argument("--workspace", default=None, help="Workspace directory.")
    p_list.add_argument("--config", default=None, help="Config directory containing plugins.json.")
    p_list.add_argument("--shipped", default=None, help="Shipped plugins directory.")
    p_list.add_argument("--json", action="store_true", help="Emit machine-readable JSON output.")

    # check
    p_chk = subparsers.add_parser("check", help="Check compatibility of plugins against the core version.")
    p_chk.add_argument("--workspace", default=None, help="Workspace directory.")
    p_chk.add_argument("--shipped", default=None, help="Shipped plugins directory.")
    p_chk.add_argument("--json", action="store_true", help="Emit machine-readable JSON output.")

    return parser


def main(argv: list[str] | None = None) -> int:
    """Parse command-line arguments and dispatch plugin SDK commands."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.subcommand == "new":
        return cmd_new(args.name, dest_dir=args.dest, template_dir=args.template)
    elif args.subcommand == "validate":
        return cmd_validate(args.path, output_json=args.json)
    elif args.subcommand == "list":
        return cmd_list(workspace_dir=args.workspace, config_dir=args.config, shipped_dir=args.shipped, output_json=args.json)
    elif args.subcommand == "check":
        return cmd_check(workspace_dir=args.workspace, shipped_dir=args.shipped, output_json=args.json)
    return 1
