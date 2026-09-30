"""Playoff odds: Monte Carlo simulation of the rest of the regular season.

For a target week W, the odds describe the league before week W is played:
real results through week W-1 are fixed, and weeks W onward are simulated
many times. A manager's odds are the share of simulations in which they
qualify for the playoffs.

Scoring model (each team, each simulated week): a normal distribution.
    mean    points scored so far, shrunk toward the league average
            (n x own average + K x league average) / (n + K). In the live
            season's current week it is blended with the team's projected
            total for that week (best projected lineup, analytics.projected_sos):
            weight on points so far = games played / (games played + BLEND_K),
            the rest on the projection. Early in the season the projection
            leads; as games accumulate, results take over.
    spread  the team's score variance so far, shrunk the same way toward the
            league variance.
A forfeit (0 with no lineup) keeps its loss but is not a scoring sample.

Qualifying (league structure from the data, nothing hardcoded):
    cutoff        playoff spots: analysis.playoff_odds.cutoff in league.yaml,
                  else ESPN's playoff team count for that season
    divisions     when a season has more than one division, each division's
                  best team (wins, then points) qualifies; the remaining spots
                  go to the best other teams by wins, then points for
    weeks         each season's regular-season length

Which weeks:
    finished weeks (any season)  results only; week 1 (no games yet) is a flat
                                 cutoff / teams for everyone
    the live season's current week (first week without a final result)
                                 results blended with projections; before any
                                 games, projections alone

Each (season, week) has its own random seed, so any week reproduces on its
own. legacy_* functions reproduce the two legacy scripts, which shared one
global seed across every week and season.
"""

from __future__ import annotations

from typing import Callable

import numpy as np
import pandas as pd

from engine.analytics.weeks import completed_weeks, forfeited_weeks

TRIALS = 50_000
SEED = 42
SHRINK_K = 3
BLEND_K = 3
DEFAULT_MU = 100.0      # league mean and variance before any game is played
DEFAULT_VAR = 225.0
MIN_VAR = 1.0
DIVISION_BONUS = 1e12   # lifts a division winner above every non-winner when ranking a trial


# ---------------------------------------------------------------- core

def scoring_model(scores: dict, teams: list, shrink_k: float = SHRINK_K) -> tuple[dict, dict, dict]:
    """Per team: shrunk mean, shrunk standard deviation, games counted.
    scores: team -> list of points so far."""
    allpts = np.array([p for t in teams for p in scores.get(t, [])], dtype=float)
    league_mu = allpts.mean() if len(allpts) else DEFAULT_MU
    league_var = allpts.var(ddof=1) if len(allpts) > 1 else DEFAULT_VAR
    mu, sd, n_games = {}, {}, {}
    for t in teams:
        s = scores.get(t, [])
        n = len(s)
        mu[t] = (n * np.mean(s) + shrink_k * league_mu) / (n + shrink_k) if n else league_mu
        var = (n * np.var(s, ddof=1) + shrink_k * league_var) / (n + shrink_k) if n > 1 else league_var
        sd[t] = float(np.sqrt(max(var, MIN_VAR)))
        n_games[t] = n
    return mu, sd, n_games


def simulate(teams: list, real_wins: dict, real_pts: dict, games: list[tuple[int, object, object]],
             mean: Callable[[object, int], float], sd: dict, normal: Callable, trials: int, cutoff: int,
             divisions: dict | None = None) -> dict:
    """Odds (percent) of qualifying. games: (week, team_a, team_b) in draw order;
    team_a's scores are drawn before team_b's for each game."""
    idx = {t: i for i, t in enumerate(teams)}
    wins = np.tile(np.array([real_wins.get(t, 0.0) for t in teams], dtype=float), (trials, 1))
    pts = np.tile(np.array([real_pts.get(t, 0.0) for t in teams], dtype=float), (trials, 1))
    for week, a, b in games:
        ai, bi = idx[a], idx[b]
        sa = normal(mean(a, week), sd[a], trials)
        sb = normal(mean(b, week), sd[b], trials)
        pts[:, ai] += sa
        pts[:, bi] += sb
        a_wins = sa > sb
        wins[:, ai] += a_wins
        wins[:, bi] += ~a_wins
    combined = wins * 100000.0 + pts          # wins first, points as the tiebreak
    if divisions and len(set(divisions.values())) > 1:
        lifted = combined.copy()
        for d in set(divisions.values()):
            members = [idx[t] for t in teams if divisions.get(t) == d]
            best = np.array(members)[np.argmax(combined[:, members], axis=1)]
            lifted[np.arange(trials), best] += DIVISION_BONUS
        combined = lifted
    order = np.argsort(-combined, axis=1)
    ranks = np.argsort(order, axis=1)
    odds = (ranks < cutoff).mean(axis=0) * 100
    return {t: round(float(odds[idx[t]]), 1) for t in teams}


# ---------------------------------------------------------------- engine

def _cutoffs(tables: dict, cfg_cutoff: int | None) -> dict[int, int]:
    s = tables["seasons"]
    return {int(y): int(cfg_cutoff or n) for y, n in zip(s["season"], s["playoff_team_count"])}


def playoff_odds(tables: dict[str, pd.DataFrame], exclude_managers: set[str] = frozenset(),
                 cutoff: int | None = None, trials: int = TRIALS, seed: int = SEED,
                 seasons: set[int] | None = None, use_divisions: bool = True) -> pd.DataFrame:
    """(season, week, manager_key, odds, method, cutoff, hidden) for every
    finished regular-season week and the live season's current week."""
    m = tables["matchups"]
    done = completed_weeks(tables)
    forfeits = {tuple(r) for r in forfeited_weeks(tables)[["season", "week", "manager_key"]].itertuples(index=False)}
    cutoffs = _cutoffs(tables, cutoff)
    regular = dict(zip(tables["seasons"]["season"].astype(int), tables["seasons"]["regular_season_periods"].astype(int)))
    teams_t = tables["teams"]
    fm = tables.get("future_matchups")
    ptw = tables.get("projected_team_weeks")
    rows = []
    for season in sorted(regular):
        if seasons is not None and season not in seasons:
            continue
        n_weeks = regular[season]
        games = m[(m["season"] == season) & ~m["is_playoff_week"] & ~m["is_bye"]]
        finished = set(done.loc[done["season"] == season, "week"]) & set(range(1, n_weeks + 1))
        unfinished = [w for w in range(1, n_weeks + 1) if w not in finished]
        current = unfinished[0] if unfinished else None
        st = teams_t[teams_t["season"] == season]
        teams = sorted(st["manager_key"].dropna())
        divisions = dict(zip(st["manager_key"], st["division_id"]))
        # the schedule: played games, then (live season) the scheduled rest
        sched = games[games["week"].isin(finished)][["week", "game_id", "manager_key"]]
        if current is not None and fm is not None and len(fm):
            rest = fm[(fm["season"] == season) & (fm["week"] >= current) & (fm["week"] <= n_weeks)]
            sched = pd.concat([sched, rest[["week", "game_id", "manager_key"]]], ignore_index=True)
        pairs = [(int(w), g["manager_key"].iloc[0], g["manager_key"].iloc[-1])
                 for (w, _), g in sched.sort_values(["week", "game_id", "manager_key"]).groupby(["week", "game_id"])
                 if g["manager_key"].nunique() == 2]
        targets = sorted(finished) + ([current] if current is not None else [])
        for W in targets:
            played = games[games["week"] < W]
            real_wins = played.groupby("manager_key")["result"].apply(
                lambda r: float((r == "W").sum() + 0.5 * (r == "T").sum())).to_dict()
            real_pts = played.groupby("manager_key")["points"].sum().to_dict()
            scores: dict = {}
            for r in played.itertuples(index=False):
                if (season, int(r.week), r.manager_key) not in forfeits:
                    scores.setdefault(r.manager_key, []).append(float(r.points))
            mu, sd, n_games = scoring_model(scores, teams)
            live = W == current
            proj = {}
            if live and ptw is not None and len(ptw):
                p = ptw[ptw["season"] == season]
                proj = {(int(w), k): float(v) for w, k, v in zip(p["week"], p["manager_key"], p["proj_points"])}
            if not played.shape[0] and not proj:
                odds = {t: round(cutoffs[season] / len(teams) * 100, 1) for t in teams}
                method = "flat"
            else:
                def mean(t, week, _mu=mu, _n=n_games, _proj=proj):
                    pj = _proj.get((week, t))
                    if pj is None:
                        return _mu[t]
                    w_emp = _n[t] / (_n[t] + BLEND_K)
                    return w_emp * _mu[t] + (1 - w_emp) * pj
                rng = np.random.default_rng([seed, season, W])
                remaining = [g for g in pairs if g[0] >= W]
                odds = simulate(teams, real_wins, real_pts, remaining, mean, sd, rng.normal, trials,
                                cutoffs[season], divisions if use_divisions else None)
                method = "results+projections" if proj else "results"
            for t in teams:
                rows.append({"season": season, "week": W, "manager_key": t, "odds": odds[t], "method": method,
                             "cutoff": cutoffs[season], "hidden": t in exclude_managers})
    return pd.DataFrame(rows, columns=["season", "week", "manager_key", "odds", "method", "cutoff", "hidden"])


def analyze_playoff_odds(tables: dict[str, pd.DataFrame], exclude_managers: set[str] = frozenset(),
                         cutoff: int | None = None) -> dict[str, pd.DataFrame]:
    return {"playoff_odds": playoff_odds(tables, exclude_managers, cutoff)}


# ---------------------------------------------------------------- legacy

LEGACY_CUTOFF = 8


def legacy_backtest(matchup_data: pd.DataFrame, trials: int = TRIALS) -> dict:
    """generate_playoff_odds.py on a legacy matchup_data.csv: one global seed
    for the whole run, games in file order (first row of each pair), the
    alphabetically first manager drawn first, top 8 by wins then points,
    week 1 simulated on league defaults. Returns {season: {week: {name: odds}}}."""
    np.random.seed(SEED)
    md = matchup_data[matchup_data["Week"].str.startswith("Week")].copy()
    md["WeekNum"] = md["Week"].str.extract(r"(\d+)")[0].astype(int)
    out = {}
    for season, g in md.groupby("Season_Year"):
        teams = sorted(g["Team_Name"].unique())
        games = g[["WeekNum", "Team_Name", "Opponent_Name"]].copy()
        games["pair"] = [tuple(sorted(p)) for p in zip(games["Team_Name"], games["Opponent_Name"])]
        games = games.drop_duplicates(subset=["WeekNum", "pair"])
        pairs = [(int(w), p[0], p[1]) for w, p in zip(games["WeekNum"], games["pair"])]
        pairs = sorted(pairs, key=lambda x: x[0])      # groupby(WeekNum) order, file order within a week
        weeks = {}
        for W in range(1, int(g["WeekNum"].max()) + 1):
            played = g[g["WeekNum"] < W]
            real_wins = {t: 0.0 for t in teams}
            real_pts = {t: 0.0 for t in teams}
            scores = {t: [] for t in teams}
            for r in played.itertuples(index=False):
                real_pts[r.Team_Name] += r.Team_Score
                scores[r.Team_Name].append(r.Team_Score)
                real_wins[r.Team_Name] += 1.0 if r.Team_Score > r.Opponent_Score else (
                    0.5 if r.Team_Score == r.Opponent_Score else 0.0)
            mu, sd, _ = scoring_model(scores, teams)
            weeks[W] = simulate(teams, real_wins, real_pts, [p for p in pairs if p[0] >= W],
                                lambda t, w: mu[t], sd, np.random.normal, trials, LEGACY_CUTOFF)
        out[int(season)] = weeks
    return out


def legacy_live(played: pd.DataFrame, schedule: pd.DataFrame, projections: pd.DataFrame, current_week: int,
                trials: int = TRIALS) -> dict:
    """generate_playoff_odds_2026_live.py: played has Team_Name, Team_Score,
    Opponent_Score for weeks before current_week; schedule has Week, Team_A,
    Team_B (draw order); projections has manager, week, proj_ppg. Names must
    already be one spelling. Returns {name: odds}."""
    np.random.seed(SEED)
    teams = sorted(set(schedule["Team_A"]) | set(schedule["Team_B"]))
    real_wins = {t: 0.0 for t in teams}
    real_pts = {t: 0.0 for t in teams}
    scores = {t: [] for t in teams}
    for r in played.itertuples(index=False):
        real_pts[r.Team_Name] += r.Team_Score
        scores[r.Team_Name].append(r.Team_Score)
        real_wins[r.Team_Name] += 1.0 if r.Team_Score > r.Opponent_Score else (
            0.5 if r.Team_Score == r.Opponent_Score else 0.0)
    mu, sd, n_games = scoring_model(scores, teams)
    if sum(n_games.values()) == 0:
        return {t: round(LEGACY_CUTOFF / len(teams) * 100, 1) for t in teams}
    proj = {(int(w), m): float(p) for m, w, p in zip(projections["manager"], projections["week"], projections["proj_ppg"])}

    def mean(t, week):
        pj = proj.get((week, t))
        if pj is None:
            return mu[t]
        w_emp = n_games[t] / (n_games[t] + BLEND_K)
        return w_emp * mu[t] + (1 - w_emp) * pj

    rest = schedule[schedule["Week"] >= current_week]
    games = [(int(w), a, b) for w, a, b in zip(rest["Week"], rest["Team_A"], rest["Team_B"])]
    games = sorted(games, key=lambda x: x[0])
    return simulate(teams, real_wins, real_pts, games, mean, sd, np.random.normal, trials, LEGACY_CUTOFF)
