"""Command line entry point.

    engine config check leagues/preach/league.yaml
    engine pull leagues/preach/league.yaml [--seasons 2020-2026] [--refresh]
    engine normalize leagues/preach/league.yaml [--verify]
    engine analyze leagues/preach/league.yaml [--verify]
    engine build leagues/preach/league.yaml [--out dist] [--verify]
    engine update leagues/preach/league.yaml [--verify]      pull, normalize, analyze, build

See docs/ARCHITECTURE.md and docs/PUBLISH_PLAN.md.
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
            "player_cards", "card_transactions", "pool_players", "projection_weeks"]
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
    from engine.normalize.adp import build_adp
    from engine.normalize.espn import normalize_league, read_adp_snapshots
    from engine.store import canonical_dir, write_tables

    cfg = load_config(args.path)
    league = cfg["league"]
    raw_dir = Path(args.cache) / league["provider"] / str(league["league_id"])
    if not raw_dir.exists():
        print(f"error: no raw data at {raw_dir}. Run `engine pull {args.path}` first.")
        return 1

    tables = apply_corrections(normalize_league(raw_dir), cfg)
    tables["adp"], adp_report = build_adp(tables, read_adp_snapshots(raw_dir), cfg)
    out = canonical_dir(Path(args.cache), league["provider"], league["league_id"])
    write_tables(tables, out)

    print(f"Canonical tables written to {out}/")
    for name, df in tables.items():
        print(f"  {name:<12}{len(df):>8} rows")
    per_season = (tables["matchups"].groupby("season").size().rename("matchup_rows").to_frame()
                  .join(tables["lineups"].groupby("season").size().rename("lineup_rows")))
    print(per_season.to_string())
    pr = tables.get("projections")
    if pr is not None and len(pr):
        has = pr["projected_points"].notna()
        cov = pr.assign(has=has).groupby(["season", "week", "source"])["has"].agg(["size", "sum"]).unstack("source")
        cov.columns = [f"{src}_{'rows' if stat == 'size' else 'projected'}" for stat, src in cov.columns]
        print("Live projection snapshot (rows, and rows with a projection):")
        print(cov.fillna(0).astype(int).to_string())

    print("ADP by drafted season (source, and picks with an ADP):")
    print(adp_report.to_string(index=False))

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
        legacy.check_adp(tables, pd.read_csv(golden / "draft" / "draft_history_with_adp.csv.gz"), cfg),
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
DRAFT_CSV_GOLDENS = ["espn_player_stats_season", "espn_player_stats_2026", "draft_surplus_v2",
                     "surplus_value_2026_live", "draft_with_stats", "draft_fingerprint_manager_season",
                     "draft_fingerprint_career"]
DRAFT_JSON_GOLDENS = {"surplus_value_data": "surplus_value_data", "surplus_value_2026_live_json": "surplus_value_2026_live",
                      "draft_heatmap": "draft_heatmap", "hit_rate_data": "hit_rate_data",
                      "draft_fingerprints_page": "draft_fingerprints_page", "draft_board_page": "draft_board_page",
                      "surplus_value_page": "surplus_value_page", "draft_analysis_page": "draft_analysis_page"}
TRADE_PAGE_GOLDENS = ["page_data", "network_data", "winpct_data", "trade_week_data", "most_traded_data",
                      "trade_value_inline"]
TRADE_GOLDENS = ["trades_mapped", "trades_mapped_clean", "trade_universe", "position_baseline",
                 "player_stints_fixed", "metrics_final", "lineup_efficiency"]


def load_goldens(golden_dir: Path) -> dict:
    """Every legacy golden file the analyze checks use."""
    import gzip
    import json

    import pandas as pd

    golden = {n: pd.read_csv(golden_dir / "trades" / f"{n}.csv.gz") for n in TRADE_GOLDENS}
    with gzip.open(golden_dir / "trades" / "trade_explorer_data.json.gz", "rt", encoding="utf-8") as f:
        golden["trade_explorer_data"] = json.load(f)
    for n in TRADE_PAGE_GOLDENS:
        path = golden_dir / "trades" / f"{n}.json.gz"
        if path.exists():
            with gzip.open(path, "rt", encoding="utf-8") as f:
                golden[n] = json.load(f)
    golden["weekly_rosters_bracket_only"] = pd.read_csv(golden_dir / "weekly_rosters_bracket_only.csv.gz")
    golden["matchup_data"] = pd.read_csv(golden_dir / "matchup_data.csv.gz")
    for n in RECORD_JSON_GOLDENS:
        with gzip.open(golden_dir / "records" / f"{n}.json.gz", "rt", encoding="utf-8") as f:
            golden[n] = json.load(f)
    golden["lineup_blunders"] = pd.read_csv(golden_dir / "records" / "lineup_blunders.csv.gz")
    with gzip.open(golden_dir / "lineups" / "lineup_efficiency_page.json.gz", "rt", encoding="utf-8") as f:
        golden["lineup_efficiency_page"] = json.load(f)
    for n in DRAFT_CSV_GOLDENS:
        golden[n] = pd.read_csv(golden_dir / "draft" / f"{n}.csv.gz")
    for key, n in DRAFT_JSON_GOLDENS.items():
        with gzip.open(golden_dir / "draft" / f"{n}.json.gz", "rt", encoding="utf-8") as f:
            golden[key] = json.load(f)
    golden["schedule_luck_season"] = pd.read_csv(golden_dir / "schedule" / "schedule_luck_season.csv.gz")
    with gzip.open(golden_dir / "schedule" / "schedule_swap.json.gz", "rt", encoding="utf-8") as f:
        golden["schedule_swap"] = json.load(f)
    for n in ("projected_sos_weekly_detail", "projected_sos_2026", "schedule_2026"):
        golden[n] = pd.read_csv(golden_dir / "sos" / f"{n}.csv.gz")
    with gzip.open(golden_dir / "sos" / "rankings_2026_week03.json.gz", "rt", encoding="utf-8") as f:
        golden["rankings_2026_week03"] = json.load(f)
    with gzip.open(golden_dir / "playoff_odds" / "playoff_odds.json.gz", "rt", encoding="utf-8") as f:
        golden["playoff_odds"] = json.load(f)
    golden["waiver_stints_full"] = pd.read_csv(golden_dir / "waivers" / "waiver_stints_full.csv.gz")
    golden["attribution_season_data_final"] = pd.read_csv(
        golden_dir / "attribution" / "attribution_season_data_final.csv.gz")
    with gzip.open(golden_dir / "attribution" / "win_attribution_final.json.gz", "rt", encoding="utf-8") as f:
        golden["win_attribution_final"] = json.load(f)
    with gzip.open(golden_dir / "regressions" / "extra_analytics_regressions.json.gz", "rt", encoding="utf-8") as f:
        golden["extra_analytics_regressions"] = json.load(f)
    with gzip.open(golden_dir / "matchup_history" / "extra_analytics_matchups.json.gz", "rt", encoding="utf-8") as f:
        golden["extra_analytics_matchups"] = json.load(f)
    with gzip.open(golden_dir / "matchup_history" / "extra_analytics_inline.json.gz", "rt", encoding="utf-8") as f:
        golden["extra_analytics_inline"] = json.load(f)
    with gzip.open(golden_dir / "gauntlet" / "extra_analytics_gauntlet.json.gz", "rt", encoding="utf-8") as f:
        golden["extra_analytics_gauntlet"] = json.load(f)
    golden["preach_manager_stats"] = pd.read_csv(golden_dir / "manager_seasons" / "preach_manager_stats.csv.gz")
    with gzip.open(golden_dir / "manager_seasons" / "draft_slots_page.json.gz", "rt", encoding="utf-8") as f:
        golden["draft_slots_page"] = json.load(f)
    golden["draft_history_all_positions"] = pd.read_csv(golden_dir / "draft_history_all_positions.csv.gz")
    golden["pi_player_stints"] = pd.read_csv(golden_dir / "position_impact" / "player_stints.csv.gz")
    for n in ("position_impact_data", "dst_removed_data"):
        with gzip.open(golden_dir / "position_impact" / f"{n}.json.gz", "rt", encoding="utf-8") as f:
            golden[n] = json.load(f)
    for n in ("waiver_page", "roster_stints", "waiver_value_page"):
        with gzip.open(golden_dir / "waivers" / f"{n}.json.gz", "rt", encoding="utf-8") as f:
            golden[n] = json.load(f)
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
    from engine.analytics.attribution import analyze_attribution
    from engine.analytics.draft import analyze_draft
    from engine.analytics.draft_profiles import analyze_draft_profiles
    from engine.normalize.adp import build_adp
    from engine.analytics.gauntlet import analyze_gauntlet
    from engine.analytics.manager_seasons import analyze_manager_seasons
    from engine.analytics.matchup_history import analyze_matchup_history
    from engine.analytics.records import analyze_records
    from engine.analytics.playoff_odds import analyze_playoff_odds
    from engine.analytics.position_impact import analyze_position_impact
    from engine.analytics.projected_sos import analyze_projected_sos
    from engine.analytics.regressions import analyze_regressions
    from engine.analytics.schedule import analyze_schedule
    from engine.analytics.trades import analyze_trades
    from engine.analytics.waivers import analyze_waivers
    from engine.config import conference_labels, excluded_games, excluded_manager_keys
    from engine.store import canonical_dir, read_tables, write_tables

    cfg = load_config(args.path)
    league = cfg["league"]
    src = canonical_dir(Path(args.cache), league["provider"], league["league_id"])
    if not src.exists():
        print(f"error: no canonical tables at {src}. Run `engine normalize {args.path}` first.")
        return 1
    tables = read_tables(src)
    if "adp" not in tables:
        print("note: no adp table in the canonical tables (run `engine normalize`); using the ADP library")
        tables["adp"], _ = build_adp(tables, {}, cfg)

    exclude = excluded_manager_keys(cfg)
    results = {**analyze_trades(tables), **analyze_records(tables, exclude), **analyze_schedule(tables, exclude),
               **analyze_projected_sos(tables, exclude), **analyze_waivers(tables, exclude),
               **analyze_manager_seasons(tables, exclude, excluded_games(cfg, "ppg"), conference_labels(cfg)),
               **analyze_matchup_history(tables, conference_labels(cfg), exclude, excluded_games(cfg, "ppg"))}
    results.update(analyze_gauntlet(tables, results["manager_seasons"], exclude))
    odds_cutoff = ((cfg.get("analysis") or {}).get("playoff_odds") or {}).get("cutoff")
    results.update(analyze_regressions(tables, results["manager_seasons"], exclude, excluded_games(cfg, "ppg"),
                                       odds_cutoff))
    results.update(analyze_playoff_odds({**tables, **results}, exclude, odds_cutoff))
    results.update(analyze_position_impact(tables, results, exclude, odds_cutoff))
    if "player_stats" in tables and len(tables["player_stats"]):
        results.update(analyze_draft(tables, exclude))
        results.update(analyze_draft_profiles(tables, results, exclude,
                                              {m["id"]: m["name"] for m in cfg.get("managers") or []}))
        results.update(analyze_attribution(tables, results, exclude))
    else:
        print("note: no player pool yet (run `engine pull`); draft value and win% attribution skipped")
    out = Path(args.cache) / "analysis" / league["provider"] / str(league["league_id"])
    write_tables(results, out)
    print(f"Analysis tables written to {out}/")
    for name, df in results.items():
        print(f"  {name:<18}{len(df):>8} rows")
    m = results["trade_metrics"]
    if len(m):
        print(m.groupby("season").agg(trade_groups=("group_id", "nunique"), trade_sides=("group_id", "size"),
                                      low_stakes=("low_stakes", "sum")).to_string())

    sos = results.get("projected_sos")
    if sos is not None and len(sos):
        names = {m["id"]: m["name"] for m in cfg.get("managers") or []}
        view = sos[~sos["hidden"]].assign(manager=lambda d: d["manager_key"].map(names))
        print(f"\nProjected strength of schedule, weeks {int(view['start_week'].min())} on (rank 1 = hardest):")
        print(view[["manager", "own_avg_proj_ppg", "sos_avg_opp_ppg", "sos_rank", "weeks_counted"]]
              .to_string(index=False))

    odds = results.get("playoff_odds")
    if odds is not None and len(odds):
        names = {m["id"]: m["name"] for m in cfg.get("managers") or []}
        last = odds[odds["season"] == odds["season"].max()]
        last = last[(last["week"] == last["week"].max()) & ~last["hidden"]]
        print(f"\nPlayoff odds, {int(last['season'].iloc[0])} week {int(last['week'].iloc[0])} "
              f"({last['method'].iloc[0]}, top {int(last['cutoff'].iloc[0])}):")
        print(last.assign(manager=last["manager_key"].map(names)).sort_values("odds", ascending=False)[
            ["manager", "odds"]].to_string(index=False))

    if not args.verify:
        return 0
    from engine.legacy_attribution import verify_attribution
    from engine.legacy_draft import verify_draft
    from engine.legacy_draft_profiles import verify_draft_profiles
    from engine.legacy_gauntlet import verify_gauntlet
    from engine.legacy_manager_seasons import verify_manager_seasons
    from engine.legacy_matchup_history import verify_matchup_history
    from engine.legacy_records import verify_records
    from engine.legacy_playoff_odds import verify_playoff_odds
    from engine.legacy_regressions import verify_regressions
    from engine.legacy_position_impact import verify_position_impact
    from engine.legacy_schedule import verify_schedule
    from engine.legacy_sos import verify_projected_sos
    from engine.legacy_trades import verify_trades
    from engine.legacy_waivers import verify_waivers

    golden = load_goldens(Path(args.golden))
    detail_dir = Path(args.cache) / "verify"
    detail_dir.mkdir(parents=True, exist_ok=True)
    trade_checks, info = verify_trades(tables, golden, cfg)
    _report("Verifying trades against the legacy pipeline:", trade_checks, info, detail_dir, "trades")
    record_checks = verify_records(tables, golden, cfg)
    _report("Verifying records and lineups against the legacy site files:", record_checks, [], detail_dir, "records")
    draft_checks, draft_info = verify_draft(tables, golden, cfg)
    _report("Verifying draft value against the legacy draft files:", draft_checks, draft_info, detail_dir, "draft")
    profile_checks, profile_info = verify_draft_profiles(tables, golden, cfg, results)
    _report("Verifying draft profiles against draft_fingerprint.py's outputs:", profile_checks, profile_info,
            detail_dir, "profiles")
    schedule_checks, schedule_info = verify_schedule(tables, golden, cfg)
    _report("Verifying schedule luck and swap against the legacy files:", schedule_checks, schedule_info,
            detail_dir, "schedule")
    sos_checks, sos_info = verify_projected_sos(tables, golden, cfg)
    _report("Verifying projected strength of schedule against the legacy files:", sos_checks, sos_info,
            detail_dir, "sos")
    waiver_checks, waiver_info = verify_waivers(tables, golden, cfg)
    _report("Verifying waiver and roster stints against the legacy files:", waiver_checks, waiver_info,
            detail_dir, "waivers")
    attr_checks, attr_info = verify_attribution(tables, results, golden, cfg)
    _report("Verifying win% attribution against the legacy files:", attr_checks, attr_info, detail_dir,
            "attribution")
    gt_checks, gt_info = verify_gauntlet(tables, results, golden, cfg)
    _report("Verifying the schedule gauntlet against extra-analytics.html:", gt_checks, gt_info, detail_dir,
            "gauntlet")
    rg_checks, rg_info = verify_regressions(tables, results, golden, cfg)
    _report("Verifying positional production and the quarterly model against extra-analytics.html:", rg_checks,
            rg_info, detail_dir, "regressions")
    mh_checks, mh_info = verify_matchup_history(tables, golden, cfg)
    _report("Verifying matchup history against extra-analytics.html:", mh_checks, mh_info, detail_dir, "matchups")
    ms_checks, ms_info = verify_manager_seasons(tables, golden, cfg)
    _report("Verifying manager season stats against the legacy stats file:", ms_checks, ms_info, detail_dir,
            "seasons")
    pi_checks, pi_info = verify_position_impact(tables, golden, cfg, results)
    _report("Verifying position impact against the legacy files:", pi_checks, pi_info, detail_dir, "positions")
    odds_checks, odds_info = verify_playoff_odds({**tables, **results}, golden, cfg)
    _report("Verifying playoff odds against the legacy files (about a minute):", odds_checks, odds_info,
            detail_dir, "odds")
    print(f"\nFull detail: {detail_dir}/")
    checks = (trade_checks + record_checks + draft_checks + profile_checks + schedule_checks + sos_checks + waiver_checks + ms_checks
              + attr_checks + gt_checks + mh_checks + rg_checks + pi_checks + odds_checks)
    return 0 if all(r.ok for r in checks) else 1


def cmd_build(args: argparse.Namespace) -> int:
    from engine.publish.build import BuildContext, run_build, verify_build
    from engine.publish.writer import build_info
    from engine.store import canonical_dir, read_tables

    cfg = load_config(args.path)
    report = validate_config(cfg)
    if not report.ok:
        for e in report.errors:
            print(f"error: {e}")
        return 1
    league = cfg["league"]
    src = canonical_dir(Path(args.cache), league["provider"], league["league_id"])
    if not src.exists():
        print(f"error: no canonical tables at {src}. Run `engine normalize {args.path}` first.")
        return 1
    ana = Path(args.cache) / "analysis" / league["provider"] / str(league["league_id"])
    analysis = read_tables(ana) if ana.exists() else {}
    if not analysis:
        print(f"note: no analysis tables at {ana} (run `engine analyze`); pages that need them are skipped")
    ctx = BuildContext(cfg=cfg, tables=read_tables(src), analysis=analysis, build=build_info(args.build_id),
                       site_root=Path(args.site), golden_dir=Path(args.golden),
                       league_dir=Path(args.path).parent)
    result = run_build(ctx, Path(args.out))
    n_site = sum(1 for f in result.copied if f not in {o.path for o in result.generated})
    print(f"Built {result.out}/ (build {ctx.build['id']}): {n_site} site files copied, "
          f"{len(result.generated)} generated")
    groups: dict[tuple, list[str]] = {}
    for o in result.generated:
        kind = f"{o.schema} v{o.version}" if o.schema else "legacy view"
        folder = o.path.rsplit("/", 1)[0] if o.path.count("/") > 2 else o.path
        groups.setdefault((folder, kind), []).append(o.path)
    for (folder, kind), paths in groups.items():
        label = paths[0] if len(paths) == 1 else f"{folder}/*.json ({len(paths)} files)"
        print(f"  {label:<44}{kind}")
    cur = ctx.config["current"]
    if cur:
        live = " (live)" if ctx.config["live_season"] == cur["season"] else ""
        print(f"Data through {cur['season']}{live} week {cur['last_completed_week']}")
    if not args.verify:
        return 0
    checks = verify_build(ctx, result)
    print("\nVerifying the build:")
    for c in checks:
        print(c if isinstance(c, str) else c.render())
    return 0 if all(c.ok for c in checks if not isinstance(c, str)) else 1


def cmd_update(args: argparse.Namespace) -> int:
    """The weekly update: pull, normalize, analyze, build. Stops at the first failure."""
    common = {"path": args.path, "cache": args.cache, "golden": args.golden}
    steps = []
    if not args.skip_pull:
        steps.append(("pull", cmd_pull, argparse.Namespace(**common, seasons=args.seasons, refresh=False,
                                                            auth=args.auth)))
    steps += [
        ("normalize", cmd_normalize, argparse.Namespace(**common, verify=False)),
        ("analyze", cmd_analyze, argparse.Namespace(**common, verify=False)),
        ("build", cmd_build, argparse.Namespace(**common, out=args.out, site=args.site, build_id=args.build_id,
                                                 verify=args.verify)),
    ]
    for name, fn, ns in steps:
        print(f"\n=== engine {name} ===", flush=True)
        rc = fn(ns)
        if rc != 0:
            print(f"\nFAIL: engine {name} returned {rc}; later steps not run.")
            return rc
    print("\nUpdate complete.")
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

    def build_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("path", help="league.yaml")
        p.add_argument("--cache", default=".cache", help="cache root (default .cache)")
        p.add_argument("--out", default="dist", help="output folder (default dist)")
        p.add_argument("--site", default=".", help="folder holding the site template (default: repo root)")
        p.add_argument("--build-id", dest="build_id", help="build id (default: UTC time plus git commit)")
        p.add_argument("--verify", action="store_true", help="check the build (schemas, paths, goldens)")
        p.add_argument("--golden", default="engine/tests/golden", help="golden files directory")

    build = sub.add_parser("build", help="Assemble the site in dist/ from the analysis tables")
    build_args(build)
    build.set_defaults(func=cmd_build)

    update = sub.add_parser("update", help="Weekly update: pull, normalize, analyze, build")
    build_args(update)
    update.add_argument("--seasons", help="seasons to pull (default: all; finished seasons come from the cache)")
    update.add_argument("--auth", help="JSON file with espn_s2 and swid (default: environment)")
    update.add_argument("--skip-pull", dest="skip_pull", action="store_true", help="use the cached raw data")
    update.set_defaults(func=cmd_update)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
