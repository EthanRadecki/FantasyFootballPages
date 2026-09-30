"""Matchup history: head-to-head records, closest games, and conference
analysis (extra-analytics.html).

All from counted games (finished regular-season and winners-bracket games;
no byes, no consolation games). The Castaldo 2024 week 14 forfeit is a real
game here: the loss counts.

Head-to-head
    Every manager's record against every other manager.

Closest games
    The smallest winning margins, from the records module's `games` table;
    closest() picks them for a scope (all, regular season, playoffs).

Conference analysis
    Each manager's conference is league.yaml league.conference_labels for
    the division ESPN put their team in that season. Tables:
    conference_managers   each manager's record against the other
                          conference, points for and against per game (a
                          game in league.yaml exclude_games, from: [ppg]:
                          the forfeiter's 0 leaves his PF/G and his
                          opponent's PA/G; the opponent's points and the
                          result still count)
    conference_seasons    each conference's record against the other, by
                          season
    conference_summary    per conference: titles, title-game trips, playoff
                          trips, wins against the other conference (regular
                          season, playoffs), points per game over all
                          counted games (regular season and playoffs)
    rivalries             every pair's meetings and record; publish orders
                          them by meetings, then the closest record, then
                          the names

Excluded managers (Sullivan, Serafin) count in every calculation and are
hidden from view: games against them count in their opponents' records, and
rows about them carry `hidden`. Legacy dropped their games from the
conference analysis.

All functions are pure: tables in, DataFrames out.
"""

from __future__ import annotations

import pandas as pd

from engine.analytics.weeks import counted_games, live_seasons

ENGINE_CHANGES = {
    "ppg_forfeiter_only": "a game in league.yaml exclude_games (from: [ppg]): the forfeiter's 0 leaves his PF/G and "
                          "his opponent's PA/G, as in the season stats; the opponent's points count for the "
                          "opponent's PF and the forfeiter's PA; legacy left the whole game out of both teams' "
                          "PF and PA averages",
    "include_excluded": "games against excluded managers (Sullivan, Serafin, 2020) count in the conference records "
                        "and totals, and their own titles and playoff trips count for their conference; their rows "
                        "are hidden; legacy dropped them",
}


def _fixes(legacy_mode: bool, fixes) -> frozenset:
    if fixes is not None:
        return frozenset(fixes)
    return frozenset() if legacy_mode else frozenset(ENGINE_CHANGES)


def _record(g: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    """Record and per-game points. Rows may carry pf_counts / pa_counts (False
    leaves that side's points out of the per-game average, not the record)."""
    pf_ok = g["pf_counts"] if "pf_counts" in g else pd.Series(True, index=g.index)
    pa_ok = g["pa_counts"] if "pa_counts" in g else pd.Series(True, index=g.index)
    out = g.assign(w=g["result"].eq("W").astype(int), l=g["result"].eq("L").astype(int),
                   t=g["result"].eq("T").astype(int), pf=g["points"].where(pf_ok, 0.0),
                   pa=g["opponent_points"].where(pa_ok, 0.0), pfn=pf_ok.astype(int), pan=pa_ok.astype(int)).groupby(by).agg(
        wins=("w", "sum"), losses=("l", "sum"), ties=("t", "sum"), games=("week", "size"),
        points_for=("pf", "sum"), points_against=("pa", "sum"), pf_games=("pfn", "sum"),
        pa_games=("pan", "sum")).reset_index()
    out["win_pct"] = (out["wins"] + out["ties"] / 2) / out["games"]
    return out


def _flag_ppg(g: pd.DataFrame, ppg_exclusions, forfeiter_only: bool) -> pd.DataFrame:
    """pf_counts / pa_counts for games in league.yaml exclude_games (ppg)."""
    g = g.copy()
    own = pd.Series([(int(s), int(w), m) in ppg_exclusions for s, w, m in
                     zip(g["season"], g["week"], g["manager_key"])], index=g.index)
    opp = pd.Series([(int(s), int(w), m) in ppg_exclusions for s, w, m in
                     zip(g["season"], g["week"], g["opponent_manager_key"])], index=g.index)
    if forfeiter_only:
        g["pf_counts"], g["pa_counts"] = ~own, ~opp
    else:
        g["pf_counts"] = g["pa_counts"] = ~(own | opp)
    return g


def head_to_head(tables: dict[str, pd.DataFrame], exclude_managers: set[str] = frozenset()) -> pd.DataFrame:
    """(manager_key, opponent_key, wins, losses, ties, games, win_pct, hidden)."""
    out = _record(counted_games(tables).rename(columns={"opponent_manager_key": "opponent_key"}),
                  ["manager_key", "opponent_key"])
    out["hidden"] = out["manager_key"].isin(exclude_managers) | out["opponent_key"].isin(exclude_managers)
    return out.drop(columns=["points_for", "points_against", "pf_games", "pa_games"])


def closest(games: pd.DataFrame, scope: str = "all", k: int = 10,
            exclude_managers: set[str] = frozenset()) -> pd.DataFrame:
    """The k smallest winning margins among decided games of the records
    `games` table, for scope all, regular, or playoff. Games with a hidden
    manager are left out (a list, not a calculation)."""
    g = games[games["team_a_result"].isin(["W", "L"])]
    g = g[~g["team_a_key"].isin(exclude_managers) & ~g["team_b_key"].isin(exclude_managers)]
    if scope != "all":
        g = g[g["is_playoff"] == (scope == "playoff")]
    a_won = g["team_a_points"] > g["team_b_points"]
    out = pd.DataFrame({
        "season": g["season"], "week": g["week"], "week_label": g["week_label"], "is_playoff": g["is_playoff"],
        "winner_key": g["team_a_key"].where(a_won, g["team_b_key"]),
        "winner_points": g["team_a_points"].where(a_won, g["team_b_points"]),
        "loser_key": g["team_b_key"].where(a_won, g["team_a_key"]),
        "loser_points": g["team_b_points"].where(a_won, g["team_a_points"]), "margin": g["margin"]})
    return out.sort_values(["margin", "season", "week"], kind="stable").head(k).reset_index(drop=True)


def _conference_games(tables: dict[str, pd.DataFrame], labels: dict[int, str]) -> pd.DataFrame:
    teams = tables["teams"]
    conf = {(int(s), m): labels.get(int(d)) for s, m, d in zip(teams["season"], teams["manager_key"], teams["division_id"])
            if pd.notna(d)}
    g = counted_games(tables).copy()
    g["conference"] = [conf.get((int(s), m)) for s, m in zip(g["season"], g["manager_key"])]
    g["opponent_conference"] = [conf.get((int(s), m)) for s, m in zip(g["season"], g["opponent_manager_key"])]
    return g


def conference_tables(tables: dict[str, pd.DataFrame], labels: dict[int, str],
                      exclude_managers: set[str] = frozenset(),
                      ppg_exclusions: set[tuple[int, int, str]] = frozenset(),
                      legacy_mode: bool = False, fixes=None) -> dict[str, pd.DataFrame]:
    fx = _fixes(legacy_mode, fixes)
    if not labels:
        return {}
    g = _flag_ppg(_conference_games(tables, labels), ppg_exclusions, "ppg_forfeiter_only" in fx)
    if "include_excluded" not in fx:
        g = g[~g["manager_key"].isin(exclude_managers) & ~g["opponent_manager_key"].isin(exclude_managers)]
    inter = g[g["conference"].notna() & g["opponent_conference"].notna() & (g["conference"] != g["opponent_conference"])]

    mgr = _record(inter, ["manager_key"])
    latest = g.sort_values("season").groupby("manager_key")["conference"].last()
    mgr["conference"] = mgr["manager_key"].map(latest)
    mgr["pf_per_game"] = mgr["points_for"] / mgr["pf_games"]
    mgr["pa_per_game"] = mgr["points_against"] / mgr["pa_games"]
    mgr["margin"] = mgr["pf_per_game"] - mgr["pa_per_game"]
    mgr["hidden"] = mgr["manager_key"].isin(exclude_managers)

    seasons = _record(inter, ["season", "conference"])

    teams = tables["teams"].copy()
    teams["conference"] = teams["division_id"].map(lambda d: labels.get(int(d)) if pd.notna(d) else None)
    teams = teams[~teams["season"].isin(live_seasons(tables))]
    if "include_excluded" not in fx:
        teams = teams[~teams["manager_key"].isin(exclude_managers)]
    count = dict(zip(tables["seasons"]["season"], tables["seasons"]["playoff_team_count"]))
    teams["made_playoffs"] = teams["playoff_seed"] <= teams["season"].map(count)
    by = teams.groupby("conference")
    summary = pd.DataFrame({
        "titles": by["final_rank"].apply(lambda r: int((r == 1).sum())),
        "title_games": by["final_rank"].apply(lambda r: int(r.between(1, 2).sum())),
        "playoff_trips": by["made_playoffs"].sum().astype(int)})
    wins = inter[inter["result"].eq("W")]
    summary["wins_regular"] = wins[~wins["is_playoff_week"]].groupby("conference").size()
    summary["wins_playoff"] = wins[wins["is_playoff_week"]].groupby("conference").size()
    own = g if "include_excluded" in fx else g[~g["manager_key"].isin(exclude_managers)]
    own = own[own["pf_counts"]]
    summary["pf_per_game"] = own.groupby("conference")["points"].mean()
    summary = summary.fillna(0).reset_index().rename(columns={"index": "conference"})

    pair = g[g["manager_key"] < g["opponent_manager_key"]]
    riv = _record(pair.rename(columns={"opponent_manager_key": "opponent_key"}), ["manager_key", "opponent_key"])
    riv = riv.drop(columns=["points_for", "points_against", "pf_games", "pa_games", "win_pct"])
    riv["hidden"] = riv["manager_key"].isin(exclude_managers) | riv["opponent_key"].isin(exclude_managers)
    drop = ["points_for", "points_against", "pf_games", "pa_games"]
    return {"conference_managers": mgr.drop(columns=drop), "conference_seasons": seasons.drop(columns=drop),
            "conference_summary": summary, "rivalries": riv}


def order_rivalries(riv: pd.DataFrame, names: dict[str, str], k: int = 8) -> pd.DataFrame:
    """Publish order: most meetings, then the closest record, then the pair
    by name (each pair written with the alphabetically first name first)."""
    r = riv[~riv["hidden"]].copy()
    a, b = r["manager_key"].map(names), r["opponent_key"].map(names)
    flip = a > b
    r["first_key"] = r["manager_key"].where(~flip, r["opponent_key"])
    r["second_key"] = r["opponent_key"].where(~flip, r["manager_key"])
    r["first_wins"] = r["wins"].where(~flip, r["losses"])
    r["second_wins"] = r["losses"].where(~flip, r["wins"])
    r["first_name"], r["second_name"] = r["first_key"].map(names), r["second_key"].map(names)
    r["gap"] = (r["first_wins"] - r["second_wins"]).abs()
    r = r.sort_values(["games", "gap", "first_name", "second_name"], ascending=[False, True, True, True])
    return r.head(k).reset_index(drop=True)


def analyze_matchup_history(tables: dict[str, pd.DataFrame], conference_labels: dict[int, str],
                            exclude_managers: set[str] = frozenset(),
                            ppg_exclusions: set[tuple[int, int, str]] = frozenset()) -> dict[str, pd.DataFrame]:
    return {"head_to_head": head_to_head(tables, exclude_managers),
            **conference_tables(tables, conference_labels, exclude_managers, ppg_exclusions)}
