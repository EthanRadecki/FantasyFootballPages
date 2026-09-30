"""Check playoff odds against the legacy outputs.

Golden files:
    playoff_odds/playoff_odds.json.gz   data/rankings/playoff_odds.json: 2020-2025
                                        from generate_playoff_odds.py, 2026 weeks
                                        1-3 from generate_playoff_odds_2026_live.py
    matchup_data.csv.gz                 the backtest's input
    sos/schedule_2026.csv.gz, sos/projected_sos_weekly_detail.csv.gz
                                        the live script's inputs for week 3
    records/matchups.json.gz            2026 weeks 1-2 results (live input)

The simulation is seeded, so legacy mode must match to the last digit:
every 2020-2025 week, and 2026 week 3 (week 1 is a flat value; week 2 used a
projection file that no longer exists). INFO lines show what the engine
changes: flat week 1 for finished seasons, division winners qualifying, one
seed per week, finished 2026 weeks recomputed from results on ESPN's schedule,
and the live week blended with the engine's projections.
"""

from __future__ import annotations

import pandas as pd

from engine.analytics import playoff_odds as po
from engine.legacy import Comparison, compare, name_to_key

LIVE_NAME_FIX = {"Ryan McQuaid": "Ryan P McQuaid", "Carmine Pittelli": "Carmine Pittelli Jr."}


def _gold_frame(gold: dict, lookup: dict, seasons: set[str] | None = None, weeks: set[int] | None = None) -> pd.DataFrame:
    rows = []
    for s, d in gold.items():
        if seasons is not None and s not in seasons:
            continue
        for w, odds in d["weeks"].items():
            if weeks is not None and int(w) not in weeks:
                continue
            rows += [{"season": int(s), "week": int(w), "manager_key": lookup[n.strip().lower()], "odds": v}
                     for n, v in odds.items()]
    return pd.DataFrame(rows)


def check_backtest(matchup_data: pd.DataFrame, gold: dict, cfg: dict, trials: int = po.TRIALS) -> Comparison:
    lk = name_to_key(cfg)
    res = po.legacy_backtest(matchup_data, trials)
    act = pd.DataFrame([{"season": s, "week": w, "manager_key": lk[n.strip().lower()], "odds": v}
                        for s, weeks in res.items() for w, odds in weeks.items() for n, v in odds.items()])
    exp = _gold_frame(gold, lk, {str(s) for s in res})
    return compare("playoff odds backtest vs playoff_odds.json", exp, act, keys=["season", "week", "manager_key"],
                   values=["odds"], tolerance=1e-9)


def live_inputs(games_json: list, schedule: pd.DataFrame, detail: pd.DataFrame, season: int, week: int):
    rows = []
    for g in games_json:
        if g["season"] == season and g["week"] < week and not g["isPlayoff"]:
            for a, b in (("teamA", "teamB"), ("teamB", "teamA")):
                rows.append({"Team_Name": g[a]["manager"], "Team_Score": g[a]["score"], "Opponent_Score": g[b]["score"]})
    played = pd.DataFrame(rows)
    played["Team_Name"] = played["Team_Name"].replace(LIVE_NAME_FIX)
    sched = schedule.assign(Team_A=schedule["Team_A"].replace(LIVE_NAME_FIX),
                            Team_B=schedule["Team_B"].replace(LIVE_NAME_FIX))
    det = detail.assign(manager=detail["manager"].replace(LIVE_NAME_FIX))
    return played, sched, det


def check_live(games_json: list, schedule: pd.DataFrame, detail: pd.DataFrame, gold: dict, cfg: dict,
               season: int = 2026, week: int = 3) -> Comparison:
    lk = name_to_key(cfg)
    res = po.legacy_live(*live_inputs(games_json, schedule, detail, season, week), current_week=week)
    act = pd.DataFrame([{"season": season, "week": week, "manager_key": lk[n.strip().lower()], "odds": v}
                        for n, v in res.items()])
    exp = _gold_frame(gold, lk, {str(season)}, {week})
    return compare(f"playoff odds live {season} week {week} vs playoff_odds.json", exp, act,
                   keys=["season", "week", "manager_key"], values=["odds"], tolerance=1e-9)


def engine_changes(tables: dict, gold: dict, cfg: dict, cutoff: int | None) -> list[str]:
    from engine.analytics import projected_sos as sos_mod

    names = {m["id"]: m["name"] for m in cfg.get("managers") or []}
    lk = name_to_key(cfg)
    t = dict(tables)
    if "projected_team_weeks" not in t and "projections" in t:
        t.update(sos_mod.analyze_projected_sos(t))
    eng = po.playoff_odds(t, cutoff=cutoff)
    no_div = po.playoff_odds(t, cutoff=cutoff, use_divisions=False)
    leg = _gold_frame(gold, lk)
    k = ["season", "week", "manager_key"]
    m = leg.merge(eng, on=k, suffixes=("_l", "_e")).merge(no_div[k + ["odds"]].rename(columns={"odds": "odds_nd"}), on=k)
    lines = ["INFO  engine: flat week 1 for finished seasons; division winners qualify; one seed per week; "
             "finished 2026 weeks from results on ESPN's schedule; live week blends the engine's projections"]
    w1 = m[(m["week"] == 1) & (m["season"] < m["season"].max())]
    lines.append(f"INFO      week 1 flat (finished seasons): {int(((w1['odds_l'] - w1['odds_e']).abs() > 0.05).sum())} "
                 f"of {len(w1)} values change, max {(w1['odds_l'] - w1['odds_e']).abs().max():.1f} points")
    rest = m[m["week"] > 1]
    div = (rest["odds_e"] - rest["odds_nd"]).abs()
    big = rest[div > 1.0]
    lines.append(f"INFO      division winners qualifying: {int((div > 1.0).sum())} of {len(rest)} values move more "
                 f"than 1 point, max {div.max():.1f}" + (" (" + ", ".join(
                     f"{r.season} wk{r.week} {names.get(r.manager_key, r.manager_key)} {r.odds_nd:.1f}->{r.odds_e:.1f}"
                     for r in big.sort_values("odds_e").head(6).itertuples()) + ")" if len(big) else ""))
    fin = rest[rest["season"] < 2026]
    noise = (fin["odds_nd"] - fin["odds_l"]).abs()
    lines.append(f"INFO      seed per week (same inputs, new random draws), 2020-2025: mean change {noise.mean():.2f}, "
                 f"max {noise.max():.1f} points")
    live = m[m["season"] == 2026]
    if len(live):
        lines.append("INFO      2026 published -> engine: " + "; ".join(
            f"wk{w}: " + ", ".join(f"{names.get(r.manager_key, r.manager_key)} {r.odds_l:.1f}->{r.odds_e:.1f}"
                                    for r in g.sort_values("odds_e", ascending=False).itertuples())
            for w, g in live.groupby("week") if w > 1))
    cur = eng[eng["method"] == "results+projections"]
    if len(cur):
        lines.append(f"INFO      live week {int(cur['week'].iloc[0])}: " + ", ".join(
            f"{names.get(r.manager_key, r.manager_key)} {r.odds:.1f}" for r in cur.sort_values("odds", ascending=False).itertuples()))
    return lines


def verify_playoff_odds(tables: dict, golden: dict, cfg: dict) -> tuple[list[Comparison], list[str]]:
    gold = golden["playoff_odds"]
    cutoff = ((cfg.get("analysis") or {}).get("playoff_odds") or {}).get("cutoff")
    checks = [check_backtest(golden["matchup_data"], gold, cfg),
              check_live(golden["matchups"], golden["schedule_2026"], golden["projected_sos_weekly_detail"], gold, cfg)]
    info = [f"INFO  legacy mode: {po.TRIALS} trials, seed {po.SEED}, top {po.LEGACY_CUTOFF}"]
    return checks, info + engine_changes(tables, gold, cfg, cutoff)
