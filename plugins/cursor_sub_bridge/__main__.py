"""``py -3 -m plugins.cursor_sub_bridge -- serve|mcp``."""

from __future__ import annotations

import sys

from .cli import cursor_sub_command, register_cli
import argparse


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m plugins.cursor_sub_bridge")
    register_cli(parser)
    # Default to showing usage when no subcommand.
    if len(sys.argv) <= 1:
        parser.print_help()
        return 2
    # Allow ``python -m plugins.cursor_sub_bridge serve`` by injecting dest.
    args = parser.parse_args()
    if not getattr(args, "cursor_sub_command", None):
        parser.print_help()
        return 2
    return int(cursor_sub_command(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
