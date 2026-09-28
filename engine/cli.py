"""Command line entry point.

    engine config check leagues/preach/league.yaml
    engine pull leagues/preach/league.yaml [--seasons 2020-2026] [--refresh]

More commands (build, serve) arrive in later phases; see docs/ARCHITECTURE.md.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

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


def cmd_pull(args: argparse.Namespace) -> int:
    from engine.providers.espn import EspnError
    from engine.pull import make_provider, parse_seasons, run_pull

    cfg = load_config(args.path)
    report = validate_config(cfg)
    if not report.ok:
        for e in report.errors:
            print(f"error: {e}")
        return 1
    league = cfg["league"]
    seasons = parse_seasons(args.seasons, league["first_season"])
    provider = make_provider(cfg, args.auth)

    cols = ["teams", "members", "weeks", "matchups", "lineup_entries", "transactions", "draft_picks"]
    print(f"{league['name']} ({league['provider']} {league['league_id']}), seasons {seasons[0]}-{seasons[-1]}")
    print(f"{'season':<8}{'status':<8}" + "".join(f"{c:>15}" for c in cols))
    try:
        for season, status, summary in run_pull(provider, league["league_id"], seasons,
                                                Path(args.cache), refresh=args.refresh):
            print(f"{season:<8}{status:<8}" + "".join(f"{summary.get(c, 0):>15}" for c in cols), flush=True)
    except EspnError as exc:
        print(f"error: {exc}")
        return 1
    print(f"Done. {provider.client.calls} ESPN request(s). Cache: {args.cache}/")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="engine")
    sub = parser.add_subparsers(dest="command", required=True)

    config = sub.add_parser("config", help="League config commands")
    config_sub = config.add_subparsers(dest="config_command", required=True)
    check = config_sub.add_parser("check", help="Validate a league.yaml")
    check.add_argument("path")
    check.set_defaults(func=cmd_config_check)

    pull = sub.add_parser("pull", help="Download raw league data into the local cache")
    pull.add_argument("path", help="league.yaml")
    pull.add_argument("--seasons", help="e.g. 2020-2026 or 2024,2026 (default: all)")
    pull.add_argument("--refresh", action="store_true", help="re-download completed seasons too")
    pull.add_argument("--cache", default=".cache", help="cache root (default .cache)")
    pull.add_argument("--auth", help="JSON file with espn_s2 and swid (default: environment)")
    pull.set_defaults(func=cmd_pull)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
