"""Manager season stats: one row per manager and season.

Replaces data/preach_manager_stats.csv, which was maintained by hand (no
script wrote it). The site reads it on index.html and managers.html, and the
champions gauntlet (extra-analytics.html) reads its dominance score.

Games are finished regular-season games only (no byes, no playoff games of
any tier), so every team's record covers the same weeks. The live season
covers the weeks finished so far.

Columns
    wins, losses, ties, games, win_pct     win_pct = (wins + ties / 2) / games
    points_for, points_against             season totals
    pf_per_game, pa_per_game, point_diff_per_game
    pf_rank, pa_rank                       within the season; 1 = most points
                                           scored, 1 = fewest allowed; tied
                                           values share the best rank
    luck_rating                            pf_rank - pa_rank: positive when a
                                           team allowed fewer points than its
                                           scoring would suggest
    dominance                              PF/G as a z-score within the season
                                           (sample standard deviation), every
                                           manager included
    pa_z                                   PA/G as a z-score the same way (the
                                           legacy file called it LR_zscore)
    final_rank, playoff_seed, made_playoffs, champion_appearance, champion
                                           from ESPN; None while the season is
                                           live
    draft_slot, team_name, division_id
    division_name                          that season's name from ESPN (renamed
                                           over the years)
    conference                             the league's stable label for the
                                           division (league.yaml
                                           league.conference_labels, by ESPN
                                           division id), for comparing seasons
    hidden                                 excluded manager (league.yaml
                                           analysis.exclude_managers)

Excluded managers count in every calculation (their games, the league
averages behind the z-scores) and are only hidden from view. Ranks and the
luck rating count visible managers only.

legacy_mode=True reproduces the legacy file's formulas. The engine default
applies every fix in ENGINE_CHANGES; `fixes` picks a subset, and
`engine analyze --verify` prints the effect of each one alone.

All functions are pure: canonical tables in, DataFrames out.
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

from engine.analytics.weeks import counted_games, live_seasons

ENGINE_CHANGES = {
    "per_game_diff": "point differential is per game played (legacy divided by the regular-season weeks played, "
                     "so 2020 teams with a bye week were divided by 13 for 12 games)",
    "ppg_exclusions": "a game in league.yaml analysis.exclude_games with from: [ppg] (the Castaldo 2024 week 14 "
                      "forfeit): the forfeiter's 0 leaves his PF/G (and so the dominance score) and his "
                      "opponent's PA/G; the opponent's points and the result still count",
    "visible_ranks": "PF/G and PA/G ranks, and the luck rating built from them, count visible managers only",
}

COLUMNS = ["season", "manager_key", "team_id", "team_name", "division_id", "division_name", "conference",
           "wins", "losses", "ties", "games", "win_pct", "points_for", "points_against",
           "pf_per_game", "pa_per_game", "point_diff_per_game", "pf_rank", "pa_rank", "luck_rating",
           "dominance", "pa_z", "final_rank", "playoff_seed", "made_playoffs", "champion_appearance",
           "champion", "draft_slot", "is_live", "hidden"]


def _fixes(legacy_mode: bool, fixes) -> frozenset:
    if fixes is not None:
        return frozenset(fixes)
    return frozenset() if legacy_mode else frozenset(ENGINE_CHANGES)


def zscore(values: pd.Series) -> pd.Series:
    """(x - mean) / sample standard deviation; 0 when every value is equal."""
    sd = values.std(ddof=1)
    if not sd or np.isnan(sd):
        return pd.Series(0.0, index=values.index)
    return (values - values.mean()) / sd


def manager_seasons(tables: dict[str, pd.DataFrame], exclude_managers: set[str] = frozenset(),
                    ppg_exclusions: set[tuple[int, int, str]] = frozenset(),
                    legacy_mode: bool = False, fixes=None,
                    conference_labels: dict[int, str] | None = None) -> pd.DataFrame:
    fx = _fixes(legacy_mode, fixes)
    g = counted_games(tables)
    g = g[~g["is_playoff_week"]].copy()
    g["win"] = g["result"].eq("W").astype(int)
    g["loss"] = g["result"].eq("L").astype(int)
    g["tie"] = g["result"].eq("T").astype(int)
    if "ppg_exclusions" in fx and ppg_exclusions:
        # The forfeiter's own points leave their PF/G and their opponent's PA/G;
        # the opponent's points and the result still count.
        idx = pd.MultiIndex.from_frame(g[["season", "week", "manager_key"]].astype({"season": int, "week": int}))
        opp = pd.MultiIndex.from_frame(g[["season", "week", "opponent_manager_key"]].astype({"season": int, "week": int}))
        g["pf_counts"] = ~idx.isin(list(ppg_exclusions))
        g["pa_counts"] = ~opp.isin(list(ppg_exclusions))
    else:
        g["pf_counts"] = g["pa_counts"] = True
    g["pf_counted"] = g["points"].where(g["pf_counts"], 0.0)
    g["pa_counted"] = g["opponent_points"].where(g["pa_counts"], 0.0)

    out = g.groupby(["season", "manager_key"]).agg(
        team_id=("team_id", "first"), wins=("win", "sum"), losses=("loss", "sum"), ties=("tie", "sum"),
        games=("week", "size"), points_for=("points", "sum"), points_against=("opponent_points", "sum"),
        pf_games=("pf_counts", "sum"), pf_counted=("pf_counted", "sum"),
        pa_games=("pa_counts", "sum"), pa_counted=("pa_counted", "sum")).reset_index()
    out["win_pct"] = (out["wins"] + out["ties"] / 2) / out["games"]
    out["pf_per_game"] = out["pf_counted"] / out["pf_games"]
    out["pa_per_game"] = out["pa_counted"] / out["pa_games"]
    if "per_game_diff" in fx:
        out["point_diff_per_game"] = out["pf_per_game"] - out["pa_per_game"]
    else:
        # Legacy divided by the regular-season weeks played so far, a bye week included.
        weeks_played = g.groupby("season")["week"].nunique()
        out["point_diff_per_game"] = (out["points_for"] - out["points_against"]) / out["season"].map(weeks_played)
    out["hidden"] = out["manager_key"].isin(exclude_managers)

    by = out.groupby("season")
    out["dominance"] = by["pf_per_game"].transform(zscore)
    out["pa_z"] = by["pa_per_game"].transform(zscore)
    ranked = out[~out["hidden"]] if "visible_ranks" in fx else out
    out["pf_rank"] = ranked.groupby("season")["pf_per_game"].rank(ascending=False, method="min")
    out["pa_rank"] = ranked.groupby("season")["pa_per_game"].rank(ascending=True, method="min")
    out["pf_rank"] = out["pf_rank"].astype("Int64")
    out["pa_rank"] = out["pa_rank"].astype("Int64")
    out["luck_rating"] = out["pf_rank"] - out["pa_rank"]

    teams = tables["teams"].copy()
    if "division_name" not in teams:
        teams["division_name"] = None
    teams["division_name"] = teams["division_name"].map(lambda d: d.strip() if isinstance(d, str) else None)
    labels = conference_labels or {}
    teams["conference"] = teams["division_id"].map(lambda d: labels.get(int(d)) if pd.notna(d) else None)
    teams["team_name"] = teams["team_name"].map(lambda n: re.sub(r"\s+", " ", n).strip() if isinstance(n, str) else n)
    out = out.merge(teams[["season", "team_id", "team_name", "division_id", "division_name", "conference",
                           "final_rank", "playoff_seed"]], on=["season", "team_id"], how="left")
    playoff_count = dict(zip(tables["seasons"]["season"], tables["seasons"]["playoff_team_count"]))
    live = live_seasons(tables)
    out["is_live"] = out["season"].isin(live)
    final = out["final_rank"].where(~out["is_live"] & out["final_rank"].gt(0))
    out["final_rank"] = final.astype("Int64")
    done = final.notna()
    out["made_playoffs"] = (out["playoff_seed"] <= out["season"].map(playoff_count)).astype("boolean").where(done)
    out["champion_appearance"] = final.le(2).astype("boolean").where(done)
    out["champion"] = final.eq(1).astype("boolean").where(done)

    slots = tables["draft_picks"].groupby(["season", "manager_key"])["draft_slot"].first().reset_index()
    out = out.merge(slots, on=["season", "manager_key"], how="left")
    out["draft_slot"] = out["draft_slot"].astype("Int64")
    return out[COLUMNS].sort_values(["season", "manager_key"]).reset_index(drop=True)


def analyze_manager_seasons(tables: dict[str, pd.DataFrame], exclude_managers: set[str] = frozenset(),
                            ppg_exclusions: set[tuple[int, int, str]] = frozenset(),
                            conference_labels: dict[int, str] | None = None) -> dict[str, pd.DataFrame]:
    return {"manager_seasons": manager_seasons(tables, exclude_managers, ppg_exclusions,
                                               conference_labels=conference_labels)}
