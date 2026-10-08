"""Games, box scores, and player records per manager.

Replaces the legacy build_matchups_json.py, generate_franchise_leaders.py,
generate_best_single_week.py, and the matching parts of update_2026.py (one
code path for every season, finished weeks only).

All use counted games only: finished regular-season and winners-bracket
games (weeks.counted_games). Byes and consolation games never count.
"""

from __future__ import annotations

import pandas as pd

from engine.analytics import lineups as lineups_mod
from engine.analytics import weeks

BEST_WEEKS_PER_GROUP = 25   # per manager, position, and season


def week_label(season_regular_weeks: dict[int, int], season: int, week: int,
               playoff_weeks: dict[int, list[int]] | None = None) -> str:
    """'Week 7', or 'Playoff Round 2' for the season's second playoff game week (playoff_weeks:
    weeks.playoff_game_weeks; without it, the second week after the regular season). A two-week round
    is one round, labelled at its last week."""
    reg = season_regular_weeks[int(season)]
    if week <= reg:
        return f"Week {week}"
    pw = (playoff_weeks or {}).get(int(season))
    return f"Playoff Round {pw.index(int(week)) + 1 if pw and int(week) in pw else week - reg}"


def games(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """One row per counted game. Team A is the away team, team B the home team
    (ESPN lists home first)."""
    g = weeks.counted_games(tables)
    reg = dict(zip(tables["seasons"]["season"], tables["seasons"]["regular_season_periods"]))
    pw = weeks.playoff_game_weeks(tables)
    names = tables["teams"].set_index(["season", "team_id"])["team_name"]
    rows = []
    for (season, week, game_id), pair in g.groupby(["season", "week", "game_id"], sort=True):
        home, away = pair.iloc[0], pair.iloc[-1]
        rows.append({
            "season": int(season), "week": int(week), "game_id": int(game_id),
            "week_label": week_label(reg, season, week, pw),
            "weeks": int(home["period_weeks"]) if "period_weeks" in pair and pd.notna(home["period_weeks"]) else 1,
            "first_week": int(home["first_week"]) if "first_week" in pair and pd.notna(home["first_week"]) else int(week),
            "team_a_total": float(away["points_total"]) if "points_total" in pair else float(away["points"]),
            "team_b_total": float(home["points_total"]) if "points_total" in pair else float(home["points"]),
            "is_playoff": bool(home["tier"] == "WINNERS_BRACKET"),
            "team_a_key": away["manager_key"], "team_a_id": int(away["team_id"]),
            "team_a_name": names.get((season, away["team_id"])),
            "team_a_points": float(away["points"]), "team_a_result": away["result"],
            "team_b_key": home["manager_key"], "team_b_id": int(home["team_id"]),
            "team_b_name": names.get((season, home["team_id"])),
            "team_b_points": float(home["points"]), "team_b_result": home["result"],
        })
    out = pd.DataFrame(rows)
    out["margin"] = (out["team_a_points"] - out["team_b_points"]).abs().round(2)
    out["combined"] = (out["team_a_points"] + out["team_b_points"]).round(2)
    return out


def box_scores(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Every counted game's lineups, one row per player, with role
    (starter or bench) and display order within the role."""
    lu = weeks.game_lineups(tables)
    slots = lineups_mod.lineup_slots(lu)
    parts = []
    for (season, week, team_id), roster in lu.groupby(["season", "week", "team_id"], sort=True):
        st, be = lineups_mod.box_score(roster, slots[int(season)])
        gw = int(roster["game_week"].iloc[0]) if "game_week" in roster else int(week)
        parts.append(st.assign(role="starter", order=range(len(st)), game_week=gw))
        parts.append(be.assign(role="bench", order=range(len(be)), game_week=gw))
    box = pd.concat(parts, ignore_index=True)
    multi = box["week"] != box["game_week"]
    if not multi.any() and (box.groupby(["season", "game_week", "team_id"])["week"].nunique() <= 1).all():
        return box.drop(columns="game_week")
    return _combine_weeks(box)


def _combine_weeks(box: pd.DataFrame) -> pd.DataFrame:
    """A two-week round's box score, one per game: each player's points added over the weeks he was a
    starter (and, if he never started, over his bench weeks), starters first in the first week's order,
    so the starters add up to ESPN's two-week total. Ordinary games pass through unchanged."""
    out = []
    for (season, gw, team_id), g in box.groupby(["season", "game_week", "team_id"], sort=True):
        if g["week"].nunique() == 1:
            out.append(g)
            continue
        g = g.sort_values(["role", "week", "order"], ascending=[False, True, True])   # starters first
        st = g[g["role"] == "starter"]
        started = set(st["player_id"])
        be = g[(g["role"] == "bench") & ~g["player_id"].isin(started)]
        for role, part in (("starter", st), ("bench", be)):
            agg = (part.groupby("player_id", sort=False)
                   .agg(**{c: (c, "first") for c in part.columns if c not in ("player_id", "points")},
                        points=("points", "sum")).reset_index())
            agg["points"] = agg["points"].round(2)
            agg["week"] = int(gw)
            agg["order"] = range(len(agg))
            out.append(agg[part.columns])
    return pd.concat(out, ignore_index=True).drop(columns="game_week")


def player_seasons_by_manager(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Per manager, player, and season: weeks rostered (any slot), games
    started, and points while started. Feeds Franchise Leaders."""
    lu = weeks.game_lineups(tables)
    keys = ["manager_key", "player_id", "season"]
    out = lu.groupby(keys).agg(weeks_rostered=("week", "size"), position=("position", "last")).reset_index()
    started = lu[lu["started"]].groupby(keys).agg(games_played=("week", "size"), total_points=("points", "sum"))
    out = out.join(started, on=keys)
    out["games_played"] = out["games_played"].fillna(0).astype(int)
    out["total_points"] = out["total_points"].fillna(0.0).round(2)
    info = tables["player_seasons"][["season", "player_id", "player_name"]]
    return out.merge(info, on=["season", "player_id"], how="left")


def best_weeks(tables: dict[str, pd.DataFrame], per_group: int = BEST_WEEKS_PER_GROUP) -> pd.DataFrame:
    """Each manager's best started weeks: the top per_group scores for every
    position and season, highest first. Counted games only: bye weeks and
    consolation games never count (the legacy file counted 2020 bye weeks)."""
    lu = weeks.game_lineups(tables)
    st = lu[lu["started"]]
    st = st.sort_values(["points", "season", "week", "player_id"], ascending=[False, True, True, True], kind="stable")
    top = st.groupby(["manager_key", "position", "season"], sort=False).head(per_group)
    return top[["manager_key", "player_id", "player_name", "position", "season", "week", "points"]].reset_index(drop=True)


def analyze_records(tables: dict[str, pd.DataFrame], exclude_managers: set[str] = frozenset(),
                    legacy_mode: bool = False) -> dict[str, pd.DataFrame]:
    eff = lineups_mod.efficiency(tables, exclude_managers, legacy_mode=legacy_mode)
    leaders = player_seasons_by_manager(tables)
    best = best_weeks(tables)
    return {
        "games": games(tables),
        "box_scores": box_scores(tables),
        "lineup_efficiency": eff,
        "lineup_blunders": lineups_mod.blunders(eff, exclude_managers),
        "franchise_leaders": leaders[~leaders["manager_key"].isin(exclude_managers)].reset_index(drop=True),
        "best_weeks": best[~best["manager_key"].isin(exclude_managers)].reset_index(drop=True),
    }
