"""Compare the schedule gauntlet with the page it feeds.

Golden file:
    gauntlet/extra_analytics_gauntlet.json.gz   the inline CHAMPION_RANKS,
                                                CHAMPIONS, HARDEST and EASIEST
                                                blocks of extra-analytics.html

recompute_weights2.py read matchup_data.csv and preach_manager_stats.csv as
they were when it ran (2020-2025; its output drifts with every new game, so
the check cuts both at 2025). The legacy inputs go through the engine's
windows() and must reproduce the champions' ranks and the hardest and
easiest lists exactly (names stand in for member keys so ties sort as they
did). The inputs are checked by their own modules (matchups by normalize,
dominance by manager season stats).

The champion cards came from an earlier, lost variant of the script:
dominance averaged without re-standardizing (it is already a z-score), points
standardized against league averages from an earlier data version, and
surges computed differently (2020, the season with byes and the excluded
managers, differs most; keeping the excluded managers' games reproduces some
of them but not all). Checked exactly: each card's games (opponent, scores,
margin, opponent dominance, opponent PF/G) and raw dominance; each score is
the logistic of its raw value; the card total is the weighted sum of the
rounded scores. Excused by pattern: raw points within 0.03 of the engine's
(the earlier league averages). Not compared: the cards' surges. The ranks and
the hardest and easiest lists, which reproduce exactly, carry the check.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from engine.analytics import gauntlet as gt
from engine.config import excluded_manager_keys
from engine.legacy import Comparison, compare, name_to_key, resolve_names

LEGACY_LAST_SEASON = 2025
RAW_CLOSE = 0.03


def legacy_games(md: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """recompute_weights2.py's games: excluded managers dropped on both sides,
    regular-season and real playoff rows, any game with a 0 score dropped."""
    names = {n.lower() for n, k in name_to_key(cfg).items() if k in excluded_manager_keys(cfg)}
    m = md[md["Season_Year"] <= LEGACY_LAST_SEASON]
    m = m[~m["Team_Name"].str.lower().isin(names) & ~m["Opponent_Name"].str.lower().isin(names)]
    m = m[m["Week"].str.startswith("Week") | m["Is_Playoff"].eq("Yes")]
    m = m[(m["Team_Score"] != 0) & (m["Opponent_Score"] != 0)]
    num = m["Week"].str.extract(r"(\d+)$")[0].astype(int)
    reg = m["Week"].str.startswith("Week")
    length = num[reg].groupby(m["Season_Year"][reg]).max()
    week = num.where(reg, m["Season_Year"].map(length) + num)
    return pd.DataFrame({"season": m["Season_Year"].astype(int), "week": week.astype(int), "week_label": m["Week"],
                         "is_regular": reg, "manager_key": m["Team_Name"], "opponent_key": m["Opponent_Name"],
                         "points": m["Team_Score"].astype(float),
                         "opponent_points": m["Opponent_Score"].astype(float)}).reset_index(drop=True)


def legacy_dominance(stats: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    s = stats[stats["Year"] <= LEGACY_LAST_SEASON]
    s = s[~resolve_names(s["Manager"], name_to_key(cfg)).isin(excluded_manager_keys(cfg))]
    return pd.DataFrame({"season": s["Year"].astype(int), "manager_key": s["Manager"],
                         "dominance": s["Dominance_Score"].astype(float), "pf_per_game": s["PF/G"].astype(float)})


def legacy_runs(stats: pd.DataFrame, games: pd.DataFrame) -> list:
    champs = stats[(stats["Placement_within_Year"] == 1) & (stats["Year"] <= LEGACY_LAST_SEASON)]
    out = []
    for season, mgr in zip(champs["Year"].astype(int), champs["Manager"]):
        g = games[(games["season"] == season) & (games["manager_key"] == mgr) & ~games["is_regular"]]
        out.append((season, mgr, g.sort_values("week")["opponent_key"].tolist()))
    return out


def _r(v, n):
    return round(float(v), n)


def _list_frames(records: list[dict]) -> tuple[pd.DataFrame, pd.DataFrame]:
    heads, games = [], []
    for i, r in enumerate(records):
        heads.append({"pos": i, "season": r["season"], "manager": r["manager"], "s_pts": r["s_pts"],
                      "s_dom": r["s_dom"], "s_streak": r["s_streak"], "gs": r["gs"]})
        for j, g in enumerate(r["games"]):
            games.append({"pos": i, "game": j, **g})
    return pd.DataFrame(heads), pd.DataFrame(games)


def _engine_list(sel: pd.DataFrame, detail: pd.DataFrame) -> list[dict]:
    out = []
    for r in sel.itertuples():
        d = detail[(detail["season"] == r.season) & (detail["manager_key"] == r.manager_key) & (detail["n"] == r.n)
                   & (detail["start_week"] == r.start_week)].sort_values("week")
        out.append({"season": r.season, "manager": r.manager_key, "s_pts": _r(r.s_pts, 1), "s_dom": _r(r.s_dom, 1),
                    "s_streak": _r(r.s_streak, 1), "gs": _r(r.gs, 2),
                    "games": [{"week": g.week_label, "opponent": g.opponent_key, "own_score": _r(g.own_score, 1),
                               "opp_score": _r(g.opp_score, 1), "margin": _r(g.margin, 1),
                               "opp_dom": _r(g.opp_dom, 3), "opp_surge": _r(g.opp_surge, 1)}
                              for g in d.itertuples()]})
    return out


def check_lists(win: pd.DataFrame, detail: pd.DataFrame, page: dict) -> list[Comparison]:
    hi, lo = gt.extremes(win)
    out = []
    for label, sel, key in (("hardest", hi, "HARDEST"), ("easiest", lo, "EASIEST")):
        eh, eg = _list_frames(page[key])
        ah, ag = _list_frames(_engine_list(sel, detail))
        out.append(compare(f"gauntlet {label} 5 vs extra-analytics.html {key}", eh, ah, keys=["pos"],
                           values=["season", "manager", "s_pts", "s_dom", "s_streak", "gs"], tolerance=1e-9))
        out.append(compare(f"gauntlet {label} 5 games vs extra-analytics.html {key}", eg, ag, keys=["pos", "game"],
                           values=["week", "opponent", "own_score", "opp_score", "margin", "opp_dom", "opp_surge"],
                           tolerance=1e-9))
    return out


def check_ranks(champs: pd.DataFrame, win: pd.DataFrame, page: dict) -> Comparison:
    """Legacy ranked on the score rounded to 2 places with pandas' default
    (unstable) sort, so the order inside a tie depends on the pandas version.
    A page rank anywhere inside its tied group is excused."""
    exp = pd.DataFrame([{"key": k, "rank": v["rank"], "total": v["total"]} for k, v in page["CHAMPION_RANKS"].items()])
    act = champs.assign(key=champs["season"].astype(str) + "_" + champs["manager_key"])
    known = []
    for r in act.itertuples():
        pool = [round(float(v), 2) for v in win.loc[win["n"] == r.n, "gs"]]
        mine = round(float(r.gs), 2)
        lo, hi = sum(v > mine for v in pool) + 1, sum(v >= mine for v in pool)
        pub = exp.loc[exp["key"] == r.key, "rank"]
        if lo < hi and len(pub) and lo <= int(pub.iloc[0]) <= hi:
            known.append({"key": r.key, "column": "rank",
                          "reason": f"tied score (ranks {lo}-{hi}); legacy's sort order inside a tie depends on the pandas version"})
    return compare("gauntlet champion ranks vs extra-analytics.html CHAMPION_RANKS", exp, act, keys=["key"],
                   values=["rank", "total"], tolerance=0, known=pd.DataFrame(known, columns=["key", "column", "reason"]))


def check_cards(champs: pd.DataFrame, detail: pd.DataFrame, dom: pd.DataFrame, page: dict) -> list[Comparison]:
    pfg = {(s, m): v for s, m, v in dom[["season", "manager_key", "pf_per_game"]].itertuples(index=False)}
    exp_g, act_g, exp_c, act_c, known = [], [], [], [], []
    for c in page["CHAMPIONS"]:
        key = f"{c['year']}_{c['champion']}"
        row = champs[(champs["season"] == c["year"]) & (champs["manager_key"] == c["champion"])].iloc[0]
        d = detail[(detail["season"] == row["season"]) & (detail["manager_key"] == row["manager_key"])
                   & (detail["n"] == row["n"]) & (detail["start_week"] == row["start_week"])].sort_values("week")
        for j, (g, e) in enumerate(zip(c["games"], d.itertuples())):
            exp_g.append({"key": key, "game": j, "opp": g["opp"], "cs": g["cs"], "os": g["os"], "m": g["m"],
                          "dom": g["dom"], "rppg": g["rppg"]})
            act_g.append({"key": key, "game": j, "opp": e.opponent_key, "cs": _r(e.own_score, 1),
                          "os": _r(e.opp_score, 1), "m": _r(e.margin, 1), "dom": _r(e.opp_dom, 3),
                          "rppg": _r(pfg[(c["year"], e.opponent_key)], 1)})
        n = c["n"]
        shrink = n / (n + 1)
        s = {f: _r(gt.logistic(c[f"raw_{f}"] * shrink), 1) for f in ("pts", "dom", "streak")}
        exp_c.append({"key": key, "raw_dom": c["raw_dom"], "raw_pts": c["raw_pts"],
                      "s_pts": c["s_pts"], "s_dom": c["s_dom"], "s_streak": c["s_streak"], "gs": c["gs"]})
        act_c.append({"key": key, "raw_dom": _r(d["opp_dom"].mean(), 4), "raw_pts": _r(row["raw_pts"], 4),
                      "s_pts": s["pts"], "s_dom": s["dom"],
                      "s_streak": s["streak"],
                      "gs": _r(gt.W_PTS * c["s_pts"] + gt.W_DOM * c["s_dom"] + gt.W_STREAK * c["s_streak"], 1)})
        if abs(c["raw_pts"] - row["raw_pts"]) <= RAW_CLOSE:
            known.append({"key": key, "column": "raw_pts",
                          "reason": "card built on an earlier data version (league averages differ slightly)"})
    return [
        compare("gauntlet champion card games vs extra-analytics.html CHAMPIONS", pd.DataFrame(exp_g),
                pd.DataFrame(act_g), keys=["key", "game"], values=["opp", "cs", "os", "m", "dom", "rppg"],
                tolerance=1e-9),
        compare("gauntlet champion card scores vs extra-analytics.html CHAMPIONS", pd.DataFrame(exp_c),
                pd.DataFrame(act_c), keys=["key"],
                values=["raw_dom", "raw_pts", "s_pts", "s_dom", "s_streak", "gs"], tolerance=1e-9,
                known=pd.DataFrame(known, columns=["key", "column", "reason"])),
    ]


def legacy_run(golden: dict, cfg: dict):
    games = legacy_games(golden["matchup_data"], cfg)
    dom = legacy_dominance(golden["preach_manager_stats"], cfg)
    win, detail = gt.windows(games, dom, unrounded_rank=False)
    champs = gt.champions(win, detail, legacy_runs(golden["preach_manager_stats"], games))
    return win, detail, champs, dom


def check_legacy(golden: dict, cfg: dict) -> list[Comparison]:
    page = golden["extra_analytics_gauntlet"]
    win, detail, champs, dom = legacy_run(golden, cfg)
    return [check_ranks(champs, win, page), *check_lists(win, detail, page), *check_cards(champs, detail, dom, page)]


def _describe(res: dict, names: dict) -> list[str]:
    win, champs = res["gauntlet_windows"], res["gauntlet_champions"]
    hi, lo = gt.extremes(win)
    fmt = lambda df: ", ".join(f"{r.season} {names.get(r.manager_key, r.manager_key)} {r.gs:.1f}" for r in df.itertuples())
    c = champs.sort_values("gs", ascending=False)
    return [f"champions: " + ", ".join(f"{r.season} {names.get(r.manager_key, r.manager_key)} {r.gs:.1f} "
                                       f"(rank {r.rank}/{r.total})" for r in c.itertuples()),
            f"hardest: {fmt(hi)}", f"easiest: {fmt(lo)}",
            f"windows: {int((win['n'] == 3).sum())} of 3 games, {int((win['n'] == 4).sum())} of 4"]


def engine_changes(tables: dict, results: dict, golden: dict, cfg: dict) -> list[str]:
    names = {m["id"]: m["name"] for m in cfg.get("managers") or []}
    ex = excluded_manager_keys(cfg)
    ms = results["manager_seasons"]
    lk = name_to_key(cfg)
    win, detail, champs, _ = legacy_run(golden, cfg)
    rename = lambda df: df.assign(manager_key=resolve_names(df["manager_key"], lk))
    pub = {"gauntlet_windows": rename(win), "gauntlet_champions": rename(champs)}
    lines = ["INFO  published (legacy inputs, 2020-2025):"] + [f"INFO      {x}" for x in _describe(pub, names)]
    leg = gt.analyze_gauntlet(tables, ms, ex, legacy_mode=True)
    lines += ["INFO  engine inputs, legacy gauntlet rules:"] + [f"INFO      {x}" for x in _describe(leg, names)]
    for fix, text in gt.ENGINE_CHANGES.items():
        eng = gt.analyze_gauntlet(tables, ms, ex, fixes={fix})
        lines.append(f"INFO  engine fix [{fix}] {text}")
        lines += [f"INFO      {x}" for x in _describe(eng, names)]
    eng = gt.analyze_gauntlet(tables, ms, ex)
    lines += ["INFO  engine (all fixes):"] + [f"INFO      {x}" for x in _describe(eng, names)]
    return lines


def verify_gauntlet(tables: dict, results: dict, golden: dict, cfg: dict) -> tuple[list[Comparison], list[str]]:
    info = [f"INFO  legacy inputs cut at {LEGACY_LAST_SEASON} (the page's run); engine uses finished seasons"]
    return check_legacy(golden, cfg), info + engine_changes(tables, results, golden, cfg)
