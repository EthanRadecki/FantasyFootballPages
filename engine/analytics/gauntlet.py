"""Schedule gauntlet: how hard was a run of consecutive opponents.

Replaces recompute_weights2.py (the champions' gauntlet cards, their ranks,
and the hardest and easiest stretches on extra-analytics.html).

A window is n consecutive games of one manager (n = 3, or 4 to compare with
the 2020 champion's four-round run). Each opponent in it is scored three
ways, each as a z-score against the league:
    points   the score the opponent put up in that game
    dom      the opponent's dominance that season (PF/G z-score)
    streak   the opponent's surge coming in: their average over the 5 games
             before this one minus their regular-season average
The window's three averages are shrunk by n / (n + 1) and mapped to 0-100
with a logistic curve; the gauntlet score is 0.70 points + 0.15 dom + 0.15
streak. A window starts no earlier than a manager's 6th game, needs its
weeks to be consecutive (a game that starts the week after the previous one ends: a
two-week playoff round is one game, so the next round follows it), and needs every
opponent to have a surge (5 earlier games).

Games: finished regular-season and winners-bracket games (no byes, no
consolation games). A forfeited game (a sat lineup scoring 0) is left out for
both teams, so no window runs through it. The league averages (points,
dominance, surge) are over the same games and seasons.

Champion runs come from the bracket: the champion's winners-bracket games in
order (a first-round bye leaves a three-game run in 2021).

Excluded managers: legacy dropped every game they were in. The engine keeps
their games (their opponents really played them) and their windows in the
ranking, and hides their own windows from the lists (`hidden`).

All functions are pure: tables in, DataFrames out.
"""

from __future__ import annotations

from collections import defaultdict

import numpy as np
import pandas as pd

W_PTS, W_DOM, W_STREAK = 0.70, 0.15, 0.15
SURGE_GAMES = 5
WINDOW_SIZES = (3, 4)

ENGINE_CHANGES = {
    "include_excluded": "excluded managers' games stay in (their opponents really played them); their own windows "
                        "are ranked and hidden from the lists; legacy dropped every game they were in",
    "unrounded_rank": "windows rank on the unrounded score, tied scores sharing a rank (legacy sorted scores "
                      "rounded to 2 places, ties in sort order)",
}


def _fixes(legacy_mode: bool, fixes) -> frozenset:
    if fixes is not None:
        return frozenset(fixes)
    return frozenset() if legacy_mode else frozenset(ENGINE_CHANGES)


def _z(values, mean: float, sd: float) -> float:
    """Average z-score of values; 0 when the league has no spread."""
    return float(np.mean((np.asarray(values, float) - mean) / sd)) if sd else 0.0


def logistic(z: float) -> float:
    return 100 / (1 + np.exp(-z))


def surges(games: pd.DataFrame) -> dict:
    """(season, manager_key, week) -> the manager's average over the 5 games
    before that week minus their regular-season average."""
    base = games[games["is_regular"]].groupby(["season", "manager_key"])["points"].mean()
    out = {}
    for (season, mgr), g in games.groupby(["season", "manager_key"], sort=True):
        g = g.sort_values("week")
        pts, wks = g["points"].tolist(), g["week"].tolist()
        for i in range(SURGE_GAMES, len(pts)):
            out[(season, mgr, wks[i])] = sum(pts[i - SURGE_GAMES:i]) / SURGE_GAMES - base[(season, mgr)]
    return out


def windows(games: pd.DataFrame, dominance: pd.DataFrame, sizes=WINDOW_SIZES,
            unrounded_rank: bool = True) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Every qualifying window.

    games: one row per team per game: season, week, week_label, is_regular,
    manager_key, opponent_key, points, opponent_points.
    dominance: season, manager_key, dominance.

    Returns (windows, window_games). windows: season, manager_key, n,
    start_week, raw_pts, raw_dom, raw_streak (window means before the
    shrink), s_pts, s_dom, s_streak, gs, rank, total. window_games: the games
    of each window with the opponent's score, dominance and surge."""
    pts = games["points"].to_numpy(float)
    pts_mean, pts_std = pts.mean(), pts.std()
    dom = {(int(s), m): float(d) for s, m, d in dominance[["season", "manager_key", "dominance"]].itertuples(index=False)}
    dom_vals = dominance["dominance"].to_numpy(float)
    dom_mean, dom_std = dom_vals.mean(), dom_vals.std()
    surge = surges(games)
    s_vals = np.array(list(surge.values()))
    s_mean, s_std = s_vals.mean(), s_vals.std()

    rows, detail = [], []
    for n in sizes:
        shrink = n / (n + 1)
        for (season, mgr), g in games.groupby(["season", "manager_key"], sort=True):
            g = g.sort_values("week").reset_index(drop=True)
            first = (g["first_week"] if "first_week" in g else g["week"]).tolist()
            for start in range(SURGE_GAMES, len(g) - (n - 1)):
                w = g.iloc[start:start + n]
                wk = w["week"].tolist()
                fw = first[start:start + n]
                if any(fw[j + 1] != wk[j] + 1 for j in range(n - 1)):
                    continue
                keys = [(int(season), o) for o in w["opponent_key"]]
                sv = [surge.get((season, o, x)) for o, x in zip(w["opponent_key"], wk)]
                if any(k not in dom for k in keys) or any(v is None for v in sv):
                    continue
                zp = _z(w["opponent_points"], pts_mean, pts_std)
                zd = _z([dom[k] for k in keys], dom_mean, dom_std)
                zs = _z(sv, s_mean, s_std)
                sp, sd, ss = logistic(zp * shrink), logistic(zd * shrink), logistic(zs * shrink)
                rows.append({"season": int(season), "manager_key": mgr, "n": n, "start_week": int(wk[0]),
                             "raw_pts": zp, "raw_dom": zd, "raw_streak": zs, "s_pts": sp, "s_dom": sd,
                             "s_streak": ss, "gs": W_PTS * sp + W_DOM * sd + W_STREAK * ss})
                for r, k, v in zip(w.itertuples(), keys, sv):
                    detail.append({"season": int(season), "manager_key": mgr, "n": n, "start_week": int(wk[0]),
                                   "week": int(r.week), "week_label": r.week_label, "opponent_key": r.opponent_key,
                                   "own_score": float(r.points), "opp_score": float(r.opponent_points),
                                   "margin": float(r.points - r.opponent_points), "opp_dom": dom[k], "opp_surge": v})
    out = pd.DataFrame(rows)
    parts = []
    for n, g in out.groupby("n", sort=True):
        if unrounded_rank:
            g = g.assign(rank=g["gs"].rank(ascending=False, method="min").astype(int))
        else:
            # legacy: sort on the score rounded to 2 places (pandas' default sort), rank = position
            g = g.assign(_r=[round(float(v), 2) for v in g["gs"]]).sort_values("_r", ascending=False).drop(columns="_r")
            g = g.assign(rank=np.arange(1, len(g) + 1))
        parts.append(g.assign(total=len(g)))
    return pd.concat(parts).sort_index().reset_index(drop=True), pd.DataFrame(detail)


def extremes(win: pd.DataFrame, n: int = 3, k: int = 5) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The k hardest and k easiest visible manager-seasons: each manager-
    season's hardest (easiest) window, then the top (bottom) k."""
    w = win[win["n"] == n]
    if "hidden" in w:
        w = w[~w["hidden"]]
    w = w.assign(_gs=[round(float(v), 2) for v in w["gs"]])
    hi = w.loc[w.groupby(["season", "manager_key"])["_gs"].idxmax()].sort_values("_gs", ascending=False).head(k)
    lo = w.loc[w.groupby(["season", "manager_key"])["_gs"].idxmin()].sort_values("_gs", ascending=True).head(k)
    return hi.drop(columns="_gs"), lo.drop(columns="_gs")


def champion_runs(tables: dict[str, pd.DataFrame], games: pd.DataFrame) -> list[tuple]:
    """(season, champion key, opponents in order, their weeks) from the bracket."""
    teams = tables["teams"]
    champs = teams[teams["final_rank"].eq(1)][["season", "manager_key"]]
    out = []
    for season, mgr in champs.itertuples(index=False):
        g = games[(games["season"] == season) & (games["manager_key"] == mgr) & ~games["is_regular"]]
        if len(g):
            g = g.sort_values("week")
            out.append((int(season), mgr, g["opponent_key"].tolist(), [int(w) for w in g["week"]]))
    return out


def champions(win: pd.DataFrame, detail: pd.DataFrame, runs) -> pd.DataFrame:
    """Each champion's run as a window (the window of the run's length whose
    opponents are the run's opponents, in order, and, when the run gives them, in
    its weeks: a champion could have met the same opponents in the same order
    earlier in the season, as the family league's 2023 champion did in weeks 9-10)."""
    rows = []
    for run in runs:
        season, mgr, opps = run[:3]
        run_weeks = run[3] if len(run) > 3 else None
        n = len(opps)
        cand = win[(win["season"] == season) & (win["manager_key"] == mgr) & (win["n"] == n)]
        for r in cand.itertuples():
            d = detail[(detail["season"] == season) & (detail["manager_key"] == mgr) & (detail["n"] == n)
                       & (detail["start_week"] == r.start_week)].sort_values("week")
            if d["opponent_key"].tolist() == opps and (run_weeks is None or d["week"].tolist() == run_weeks):
                rows.append(r._asdict())
                break
    return pd.DataFrame(rows).drop(columns="Index", errors="ignore")


def engine_games(tables: dict[str, pd.DataFrame], exclude_managers: set[str], include_excluded: bool) -> pd.DataFrame:
    """Counted games of finished seasons, forfeited games left out for both
    teams."""
    from engine.analytics.records import week_label
    from engine.analytics.weeks import counted_games, forfeited_weeks, live_seasons

    g = counted_games(tables)
    g = g[~g["season"].isin(live_seasons(tables))]
    f = forfeited_weeks(tables)
    lost = set(zip(f["season"], f["week"], f["manager_key"]))
    hit = [(s, w, a) in lost or (s, w, b) in lost
           for s, w, a, b in zip(g["season"], g["week"], g["manager_key"], g["opponent_manager_key"])]
    g = g[~np.array(hit, dtype=bool)]
    if not include_excluded:
        g = g[~g["manager_key"].isin(exclude_managers) & ~g["opponent_manager_key"].isin(exclude_managers)]
    reg = dict(zip(tables["seasons"]["season"], tables["seasons"]["regular_season_periods"]))
    from engine.analytics.weeks import playoff_game_weeks
    pw = playoff_game_weeks(tables)
    return pd.DataFrame({
        "season": g["season"].astype(int), "week": g["week"].astype(int),
        "week_label": [week_label(reg, s, w, pw) for s, w in zip(g["season"], g["week"])],
        "first_week": (g["first_week"] if "first_week" in g else g["week"]).astype(int),
        "is_regular": ~g["is_playoff_week"].astype(bool), "manager_key": g["manager_key"],
        "opponent_key": g["opponent_manager_key"], "points": g["points"].astype(float),
        "opponent_points": g["opponent_points"].astype(float)}).reset_index(drop=True)


def analyze_gauntlet(tables: dict[str, pd.DataFrame], manager_seasons: pd.DataFrame,
                     exclude_managers: set[str] = frozenset(), legacy_mode: bool = False,
                     fixes=None) -> dict[str, pd.DataFrame]:
    fx = _fixes(legacy_mode, fixes)
    games = engine_games(tables, exclude_managers, "include_excluded" in fx)
    dom = manager_seasons[manager_seasons["season"].isin(set(games["season"]))]
    if "include_excluded" not in fx:
        dom = dom[~dom["manager_key"].isin(exclude_managers)]
    runs = champion_runs(tables, games)
    # window lengths: 3 and 4 games, plus every champion run's length (a league with two playoff rounds
    # has two-game runs), so each champion's run is ranked against windows of its own length
    sizes = tuple(sorted(set(WINDOW_SIZES) | {len(r[2]) for r in runs}))
    win, detail = windows(games, dom[["season", "manager_key", "dominance"]], sizes,
                          unrounded_rank="unrounded_rank" in fx)
    win["hidden"] = win["manager_key"].isin(exclude_managers)
    champs = champions(win, detail, runs)
    return {"gauntlet_windows": win, "gauntlet_window_games": detail, "gauntlet_champions": champs}
