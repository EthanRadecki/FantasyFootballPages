"""Week-level building blocks shared by every analysis.

- which weeks and games count: finished weeks only; the whole regular season
  plus winners-bracket games in the playoffs; consolation games never count
- forfeited lineups (a team that scored 0 in a real game because nothing was
  started), excluded from anything that measures decisions
- playoff week weights (a week matters more with the season on the line)
- the weekly position baseline and each player's position-relative z-score

All functions are pure: canonical tables in, DataFrames out.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Playoff weighting, counted back from the final: championship week, then the
# semifinal, the quarterfinal, and any earlier round. Regular season is 1.0.
REGULAR_WEIGHT = 1.0
ROUND_WEIGHTS_FROM_FINAL = [2.0, 1.6, 1.3, 1.15]   # Championship, Semifinal, Quarterfinal, First Round


def completed_weeks(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """(season, week) where every regular-season or winners-bracket game has
    a final result. A week in progress (ESPN winner UNDECIDED) is left out of
    every analysis. Consolation games do not decide it."""
    m = tables["matchups"]
    games = m[~m["is_bye"] & (~m["is_playoff_week"] | m["tier"].eq("WINNERS_BRACKET"))]
    done = games.groupby(["season", "week"])["result"].apply(lambda r: r.isin(["W", "L", "T"]).all())
    return done[done].reset_index()[["season", "week"]]


def live_seasons(tables: dict[str, pd.DataFrame]) -> set[int]:
    """Seasons whose final scoring period has not been completed."""
    done = completed_weeks(tables).groupby("season")["week"].max()
    final = tables["seasons"].set_index("season")["final_scoring_period"]
    return {int(s) for s, f in final.items() if done.get(s, 0) < f}


def counted_games(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Matchup rows that count toward records and stats: finished regular
    season games and winners-bracket games. No byes, no consolation games."""
    m = tables["matchups"].merge(completed_weeks(tables), on=["season", "week"])
    return m[~m["is_bye"] & (~m["is_playoff_week"] | m["tier"].eq("WINNERS_BRACKET"))]


def bracket_lineups(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Lineup rows for weeks that count, as the trade analysis uses them: every
    finished regular-season week (a bye team included) and, in playoff weeks,
    only teams playing a winners-bracket game."""
    m = tables["matchups"].merge(completed_weeks(tables), on=["season", "week"])
    keep = m[~m["is_playoff_week"] | (m["tier"].eq("WINNERS_BRACKET") & ~m["is_bye"])]
    keep = keep[["season", "week", "team_id"]].drop_duplicates()
    return tables["lineups"].merge(keep, on=["season", "week", "team_id"])


def game_lineups(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Lineup rows for teams that played a counted game that week (see
    counted_games). Unlike bracket_lineups, a bye week is left out."""
    keep = counted_games(tables)[["season", "week", "team_id"]].drop_duplicates()
    return tables["lineups"].merge(keep, on=["season", "week", "team_id"])


def forfeited_weeks(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """(season, week, manager_key) where a team scored 0 in a finished game.

    A final score of 0 means the manager never set a playable lineup (the
    2024 example started six players who were all out). It is still a bracket
    week, so filtering consolation games alone does not remove it. Games not
    yet decided (ESPN winner UNDECIDED, so no result) are never forfeits: a
    team sits at 0 before its players take the field.
    """
    m = tables["matchups"]
    f = m[~m["is_bye"] & m["points"].eq(0) & m["result"].isin(["W", "L", "T"])]
    return f[["season", "week", "manager_key"]].drop_duplicates().reset_index(drop=True)


def drop_forfeits(lineups: pd.DataFrame, forfeits: pd.DataFrame) -> pd.DataFrame:
    keys = ["season", "week", "manager_key"]
    flagged = lineups[keys].merge(forfeits.assign(_f=True), on=keys, how="left")["_f"].notna().to_numpy()
    return lineups[~flagged]


def week_weights(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """(season, week, weight). Playoff rounds are the playoff weeks that had a
    winners-bracket game; each is weighted by its distance from the final."""
    m = tables["matchups"]
    rows = []
    for season, g in m.groupby("season"):
        rounds = sorted(g.loc[g["is_playoff_week"] & g["tier"].eq("WINNERS_BRACKET") & ~g["is_bye"], "week"].unique())
        from_final = {wk: len(rounds) - 1 - i for i, wk in enumerate(rounds)}
        for wk in sorted(g["week"].unique()):
            if wk in from_final:
                i = min(from_final[wk], len(ROUND_WEIGHTS_FROM_FINAL) - 1)
                w = ROUND_WEIGHTS_FROM_FINAL[i]
            else:
                w = REGULAR_WEIGHT
            rows.append({"season": int(season), "week": int(wk), "week_weight": w})
    return pd.DataFrame(rows, columns=["season", "week", "week_weight"])


IR_SLOT = "IR"


def position_baseline(lineups: pd.DataFrame, include_ir: bool = False) -> pd.DataFrame:
    """Mean and sample standard deviation of points per season, week, and
    position, over every rostered player: starters and bench, not IR (an
    injured player's 0 is not a real week at that position).

    include_ir=True reproduces the legacy baseline, which counted IR players.
    """
    if not include_ir:
        lineups = lineups[lineups["slot"] != IR_SLOT]
    g = lineups.groupby(["season", "week", "position"])["points"]
    return pd.DataFrame({"pos_mean": g.mean(), "pos_std": g.std()}).reset_index()


def with_z(lineups: pd.DataFrame, baseline: pd.DataFrame, weights: pd.DataFrame) -> pd.DataFrame:
    """Adds z (position-relative score), week_weight, and weighted_z."""
    out = lineups.merge(baseline, on=["season", "week", "position"], how="left")
    out = out.merge(weights, on=["season", "week"], how="left")
    out["week_weight"] = out["week_weight"].fillna(REGULAR_WEIGHT)
    z = (out["points"] - out["pos_mean"]) / out["pos_std"]
    out["z"] = z.replace([np.inf, -np.inf], np.nan)
    out["weighted_z"] = out["z"] * out["week_weight"]
    return out
