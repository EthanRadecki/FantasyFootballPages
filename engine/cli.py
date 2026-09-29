"""Command line entry point.

    engine config check leagues/preach/league.yaml
    engine pull leagues/preach/league.yaml [--seasons 2020-2026] [--refresh]
    engine normalize leagues/preach/league.yaml [--verify]
    engine analyze leagues/preach/league.yaml [--verify]

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

    cols = ["teams", "weeks", "matchups", "lineup_entries", "transactions", "draft_picks",
            "player_cards", "card_transactions", "pool_players"]
    print(f"{league['name']} ({league['provider']} {league['league_id']}), seasons {seasons[0]}-{seasons[-1]}")
    print(f"{'season':<8}{'status':<8}" + "".join(f"{c:>18}" for c in cols))
    try:
        for season, status, summary in run_pull(provider, league["league_id"], seasons,
                                                Path(args.cache), refresh=args.refresh):
            print(f"{season:<8}{status:<8}" + "".join(f"{summary.get(c, 0):>18}" for c in cols), flush=True)
    except EspnError as exc:
        print(f"error: {exc}")
        return 1
    print(f"Done. {provider.client.calls} ESPN request(s). Cache: {args.cache}/")
    return 0


def cmd_normalize(args: argparse.Namespace) -> int:
    import pandas as pd

    from engine import legacy
    from engine.normalize.corrections import apply_corrections
    from engine.normalize.espn import normalize_league
    from engine.store import canonical_dir, write_tables

    cfg = load_config(args.path)
    league = cfg["league"]
    raw_dir = Path(args.cache) / league["provider"] / str(league["league_id"])
    if not raw_dir.exists():
        print(f"error: no raw data at {raw_dir}. Run `engine pull {args.path}` first.")
        return 1

    tables = apply_corrections(normalize_league(raw_dir), cfg)
    out = canonical_dir(Path(args.cache), league["provider"], league["league_id"])
    write_tables(tables, out)

    print(f"Canonical tables written to {out}/")
    for name, df in tables.items():
        print(f"  {name:<12}{len(df):>8} rows")
    per_season = (tables["matchups"].groupby("season").size().rename("matchup_rows").to_frame()
                  .join(tables["lineups"].groupby("season").size().rename("lineup_rows")))
    print(per_season.to_string())

    for w in legacy.config_consistency(tables, cfg):
        print(f"warning: {w}")

    if not args.verify:
        return 0
    golden = Path(args.golden)
    print("\nVerifying against legacy files:")
    results = [
        legacy.check_matchups(tables, pd.read_csv(golden / "matchup_data.csv.gz"), cfg),
        legacy.check_rosters(tables, pd.read_csv(golden / "weekly_rosters_bracket_only.csv.gz"), cfg),
        legacy.check_draft(tables, pd.read_csv(golden / "draft_history_all_positions.csv.gz"), cfg),
        legacy.check_transactions(tables, pd.read_csv(golden / "transactions_clean.csv.gz"), cfg),
    ]
    if "player_stats" in tables and len(tables["player_stats"]):
        results.append(legacy.check_player_stats(
            tables, pd.read_csv(golden / "draft" / "espn_player_stats_season.csv.gz"), cfg))
    else:
        print("note: no player pool in the cache yet; run `engine pull --refresh` to add it")
    detail_dir = Path(args.cache) / "verify"
    detail_dir.mkdir(parents=True, exist_ok=True)
    for old in detail_dir.glob("*.csv"):
        old.unlink()
    for r in results:
        print(r.render())
        slug = r.name.split(" vs ")[0].replace(" ", "_")
        for part, frame in r.frames.items():
            if len(frame):
                frame.to_csv(detail_dir / f"{slug}__{part}.csv", index=False)
    print(f"\nFull detail: {detail_dir}/")
    return 0 if all(r.ok for r in results) else 1


RECORD_JSON_GOLDENS = ["matchups", "franchise_leaders", "best_single_week"]
TRADE_GOLDENS = ["trades_mapped", "trades_mapped_clean", "trade_universe", "position_baseline",
                 "player_stints_fixed", "metrics_final", "lineup_efficiency"]


def load_goldens(golden_dir: Path) -> dict:
    """Every legacy golden file the analyze checks use."""
    import gzip
    import json

    import pandas as pd

    golden = {n: pd.read_csv(golden_dir / "trades" / f"{n}.csv.gz") for n in TRADE_GOLDENS}
    golden["weekly_rosters_bracket_only"] = pd.read_csv(golden_dir / "weekly_rosters_bracket_only.csv.gz")
    golden["matchup_data"] = pd.read_csv(golden_dir / "matchup_data.csv.gz")
    for n in RECORD_JSON_GOLDENS:
        with gzip.open(golden_dir / "records" / f"{n}.json.gz", "rt", encoding="utf-8") as f:
            golden[n] = json.load(f)
    golden["lineup_blunders"] = pd.read_csv(golden_dir / "records" / "lineup_blunders.csv.gz")
    return golden


def _report(title: str, checks: list, info: list[str], detail_dir: Path, prefix: str) -> None:
    print(f"\n{title}")
    for old in detail_dir.glob(f"{prefix}__*.csv"):
        old.unlink()
    for line in info[:1]:
        print(line)
    for r in checks:
        print(r.render())
        slug = f"{prefix}__" + r.name.split(" vs ")[0].replace(" ", "_")
        for part, frame in r.frames.items():
            if len(frame):
                frame.to_csv(detail_dir / f"{slug}__{part}.csv", index=False)
    for line in info[1:]:
        print(line)


def cmd_analyze(args: argparse.Namespace) -> int:
    from engine.analytics.records import analyze_records
    from engine.analytics.trades import analyze_trades
    from engine.config import excluded_manager_keys
    from engine.store import canonical_dir, read_tables, write_tables

    cfg = load_config(args.path)
    league = cfg["league"]
    src = canonical_dir(Path(args.cache), league["provider"], league["league_id"])
    if not src.exists():
        print(f"error: no canonical tables at {src}. Run `engine normalize {args.path}` first.")
        return 1
    tables = read_tables(src)

    results = {**analyze_trades(tables), **analyze_records(tables, excluded_manager_keys(cfg))}
    out = Path(args.cache) / "analysis" / league["provider"] / str(league["league_id"])
    write_tables(results, out)
    print(f"Analysis tables written to {out}/")
    for name, df in results.items():
        print(f"  {name:<18}{len(df):>8} rows")
    m = results["trade_metrics"]
    if len(m):
        print(m.groupby("season").agg(trade_groups=("group_id", "nunique"), trade_sides=("group_id", "size"),
                                      low_stakes=("low_stakes", "sum")).to_string())

    if not args.verify:
        return 0
    from engine.legacy_records import verify_records
    from engine.legacy_trades import verify_trades

    golden = load_goldens(Path(args.golden))
    detail_dir = Path(args.cache) / "verify"
    detail_dir.mkdir(parents=True, exist_ok=True)
    trade_checks, info = verify_trades(tables, golden, cfg)
    _report("Verifying trades against the legacy pipeline:", trade_checks, info, detail_dir, "trades")
    record_checks = verify_records(tables, golden, cfg)
    _report("Verifying records and lineups against the legacy site files:", record_checks, [], detail_dir, "records")
    print(f"\nFull detail: {detail_dir}/")
    return 0 if all(r.ok for r in trade_checks + record_checks) else 1


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

    norm = sub.add_parser("normalize", help="Build canonical tables from the raw cache")
    norm.add_argument("path", help="league.yaml")
    norm.add_argument("--cache", default=".cache", help="cache root (default .cache)")
    norm.add_argument("--verify", action="store_true", help="compare with the legacy golden files")
    norm.add_argument("--golden", default="engine/tests/golden", help="golden files directory")
    norm.set_defaults(func=cmd_normalize)

    ana = sub.add_parser("analyze", help="Build analysis tables from the canonical tables")
    ana.add_argument("path", help="league.yaml")
    ana.add_argument("--cache", default=".cache", help="cache root (default .cache)")
    ana.add_argument("--verify", action="store_true", help="compare with the legacy golden files")
    ana.add_argument("--golden", default="engine/tests/golden", help="golden files directory")
    ana.set_defaults(func=cmd_analyze)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
