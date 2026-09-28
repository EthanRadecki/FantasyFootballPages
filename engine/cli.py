"""Command line entry point.

    engine config check leagues/preach/league.yaml

More commands (pull, build, serve) arrive in later phases; see docs/ARCHITECTURE.md.
"""

from __future__ import annotations

import argparse
import sys

from engine.config import load_config, validate_config


def cmd_config_check(args: argparse.Namespace) -> int:
    cfg = load_config(args.path)
    report = validate_config(cfg)
    for w in report.warnings:
        print(f"warning: {w}")
    for e in report.errors:
        print(f"error: {e}")
    if report.ok:
        n = len(cfg.get("managers") or [])
        print(f"OK: {args.path} is valid ({n} managers, {len(report.warnings)} warning(s)).")
        return 0
    print(f"FAIL: {len(report.errors)} error(s).")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="engine")
    sub = parser.add_subparsers(dest="command", required=True)

    config = sub.add_parser("config", help="League config commands")
    config_sub = config.add_subparsers(dest="config_command", required=True)
    check = config_sub.add_parser("check", help="Validate a league.yaml")
    check.add_argument("path")
    check.set_defaults(func=cmd_config_check)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
