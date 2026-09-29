"""Compare the records and lineups analysis with the legacy site files.

Golden files:
    records/matchups.json.gz             data/matchups.json (2020 through the
                                         last 2026 week the site was updated)
    records/franchise_leaders.json.gz    data/franchise_leaders.json
    records/best_single_week.json.gz     data/best_single_week.json
    records/lineup_blunders.csv.gz       the 10 manager-weeks hardcoded in
                                         generate_blunder_rosters.py
    trades/lineup_efficiency.csv.gz      generate_lineup_efficiency.py output

Legacy files name players (not ids) and use cleaned-up spellings in places,
so rows are matched to player ids through engine.legacy.attach_player_ids
and names are not compared. The analysis runs on the tables with the legacy
positions put back (see legacy_trades.legacy_positions), so the known
position difference does not ripple into lineups and optimal scores.

Known legacy differences, excused by pattern:
- lineup_efficiency.csv was built from an older matchup_data.csv; where its
  scores differ, the engine matches the current matchup_data.csv
- best_single_week keeps the top 25 per manager, position, and season with an
  unstable sort, so a different player-week can fill a tied last place
- best_single_week counted 2020 regular-season bye weeks; only games count
- matchups.json lists late-2025 and 2026 games with the teams in a different
  order (team A is otherwise the away team); games are compared by manager
- bench players tied on points can appear in either order
The live season is compared only through the last week the site files cover.
"""

from __future__ import annotations

import itertools
import json

import pandas as pd

from engine.analytics import records as records_mod
from engine.config import excluded_manager_keys
from engine.legacy import Comparison, attach_player_ids, compare, name_to_key, resolve_names


def _sides(games_json: list[dict], lookup: dict) -> pd.DataFrame:
    rows = []
    for g in games_json:
        for side in ("teamA", "teamB"):
            s = g[side]
            rows.append({
                "season": g["season"], "week": g["week"], "manager_key": lookup[s["manager"].strip().lower()],
                "side": side, "week_label": g["weekLabel"], "is_playoff": g["isPlayoff"],
                "team_name": s["fantasyTeam"], "points": s["score"],
                "result": {"Win": "W", "Loss": "L", "Tie": "T"}[s["outcome"]],
                "starters": [(p["name"], p["pos"], p["slot"], round(p["pts"], 2)) for p in s["starters"]],
                "bench": [(p["name"], p["pos"], p["slot"], round(p["pts"], 2)) for p in s["bench"]],
            })
    return pd.DataFrame(rows)


def _engine_sides(analysis: dict) -> pd.DataFrame:
    g = analysis["games"]
    parts = []
    for s, side in (("a", "teamA"), ("b", "teamB")):
        parts.append(pd.DataFrame({
            "season": g["season"], "week": g["week"], "manager_key": g[f"team_{s}_key"], "side": side,
            "week_label": g["week_label"], "is_playoff": g["is_playoff"], "team_name": g[f"team_{s}_name"],
            "points": g[f"team_{s}_points"], "result": g[f"team_{s}_result"]}))
    out = pd.concat(parts, ignore_index=True)
    box = {}
    for key, grp in analysis["box_scores"].groupby(["season", "week", "manager_key"]):
        grp = grp.sort_values("order")
        as_list = lambda d: [(r.player_name, r.position, r.slot, round(r.points, 2)) for r in d.itertuples()]
        box[key] = (as_list(grp[grp["role"] == "starter"]), as_list(grp[grp["role"] == "bench"]))
    keys = list(zip(out["season"], out["week"], out["manager_key"]))
    out["starters"] = [box.get(k, ([], []))[0] for k in keys]
    out["bench"] = [box.get(k, ([], []))[1] for k in keys]
    return out


def _tie_groups(players: list) -> str:
    return json.dumps([sorted(g) for _, g in itertools.groupby(players, key=lambda p: p[3])])


def check_games(analysis: dict, games_json: list[dict], cfg: dict) -> Comparison:
    exp = _sides(games_json, name_to_key(cfg))
    act = _engine_sides(analysis)
    act = act.merge(exp[["season", "week"]].drop_duplicates(), on=["season", "week"])
    for df in (exp, act):
        df["starters"] = df["starters"].map(json.dumps)
        df["bench_ties"] = df["bench"].map(_tie_groups)
    r = compare("games vs matchups.json", exp, act, keys=["season", "week", "manager_key"],
                values=["week_label", "is_playoff", "team_name", "points", "result", "starters", "bench_ties"])
    both = exp.merge(act, on=["season", "week", "manager_key"], suffixes=("_l", "_e"))
    swapped = int((both["side_l"] != both["side_e"]).sum())
    if swapped:
        r.known["team A/B listed in the other order (late-2025 and 2026 games); compared by manager"] = swapped
    ties = int((both["bench_l"].map(json.dumps) != both["bench_e"].map(json.dumps)).sum())
    if ties:
        r.known["bench players tied on points listed in another order"] = ties
    return r


def check_lineup_efficiency(analysis: dict, legacy: pd.DataFrame, matchup_data: pd.DataFrame, cfg: dict) -> Comparison:
    lookup = name_to_key(cfg)
    exp = pd.DataFrame({
        "season": legacy["Season"].astype(int), "week": legacy["Week"].astype(int),
        "manager_key": resolve_names(legacy["Manager"], lookup),
        "actual_points": legacy["Actual_Points"], "optimal_points": legacy["Optimal_Points"],
        "points": legacy["Team_Score"], "opponent_points": legacy["Opponent_Score"],
        "result": legacy["Outcome"].map({"Win": "W", "Loss": "L", "Tie": "T"}),
        "would_have_won": legacy["Would_Have_Beaten_Opponent"].astype(bool),
        "missed_win": legacy["Missed_Win"].astype(bool), "forfeited": legacy["Forfeited_Lineup"].astype(bool),
    })
    act = analysis["lineup_efficiency"]
    act = act[~act["manager_key"].isin(excluded_manager_keys(cfg)) & act["season"].isin(exp["season"].unique())]

    # Where the legacy scores differ, excuse them only if the engine matches the
    # current matchup_data.csv (the legacy file was built from an older copy).
    reg = {}
    for season, g in analysis["games"].groupby("season"):
        labels = g[g["week_label"].str.startswith("Week ")]["week"]
        reg[int(season)] = int(labels.max())
    md = matchup_data.assign(
        season=matchup_data["Season_Year"].astype(int),
        manager_key=resolve_names(matchup_data["Team_Name"], lookup))
    num = md["Week"].str.extract(r"(\d+)$")[0].astype(int)
    md["week"] = num.where(~md["Week"].str.startswith("Playoff"), md["season"].map(reg) + num)
    current = md[["season", "week", "manager_key", "Team_Score", "Opponent_Score"]]
    both = exp.merge(act[["season", "week", "manager_key", "points", "opponent_points"]],
                     on=["season", "week", "manager_key"], suffixes=("", "_e")).merge(
        current, on=["season", "week", "manager_key"], how="left")
    reason = "legacy file used an older matchup_data.csv; engine matches the current one"
    known = []
    for col, cur in (("points", "Team_Score"), ("opponent_points", "Opponent_Score")):
        diff = (both[col] - both[f"{col}_e"]).abs() > 0.005
        ok = diff & ((both[f"{col}_e"] - both[cur]).abs() <= 0.005)
        known.append(both.loc[ok, ["season", "week", "manager_key"]].assign(column=col, reason=reason))
        # the optimal lineup would-have-won flag follows the score it is compared with
        if col == "opponent_points":
            known.append(both.loc[ok, ["season", "week", "manager_key"]].assign(column="would_have_won", reason=reason))
    return compare("lineup efficiency vs lineup_efficiency.csv", exp, act, keys=["season", "week", "manager_key"],
                   values=["actual_points", "optimal_points", "points", "opponent_points", "result",
                           "would_have_won", "missed_win", "forfeited"],
                   known=pd.concat(known, ignore_index=True))


def check_blunders(analysis: dict, legacy: pd.DataFrame, cfg: dict) -> Comparison:
    exp = pd.DataFrame({"rank": range(1, len(legacy) + 1), "season": legacy["season"].astype(int),
                        "week": legacy["week"].astype(int),
                        "manager_key": resolve_names(legacy["manager"], name_to_key(cfg))})
    b = analysis["lineup_blunders"].reset_index(drop=True)
    act = pd.DataFrame({"rank": range(1, len(b) + 1), "season": b["season"], "week": b["week"],
                        "manager_key": b["manager_key"]})
    return compare("lineup blunders vs generate_blunder_rosters.py", exp, act, keys=["rank"],
                   values=["season", "week", "manager_key"])


def _per_manager(data: dict, lookup: dict) -> pd.DataFrame:
    return pd.DataFrame([dict(r, manager_key=lookup[m.strip().lower()]) for m, rows in data.items() for r in rows])


def check_franchise_leaders(analysis: dict, data: dict, tables: dict, cfg: dict) -> Comparison:
    exp = attach_player_ids(_per_manager(data, name_to_key(cfg)), tables["lineups"], tables["players"],
                            ["manager_key", "season"])
    act = analysis["franchise_leaders"]
    act = act[act["season"].isin(exp["season"].unique())]
    r = compare("franchise leaders vs franchise_leaders.json", exp, act, keys=["manager_key", "season", "player_id"],
                values=["position", "weeks_rostered", "games_played", "total_points"])
    _note_names(r, exp)
    return r


def check_best_weeks(analysis: dict, data: dict, tables: dict, cfg: dict) -> Comparison:
    exp = attach_player_ids(_per_manager(data, name_to_key(cfg)), tables["lineups"], tables["players"],
                            ["manager_key", "season"])
    act = analysis["best_weeks"].assign(points=lambda d: d["points"].round(1))
    act = act[act["season"].isin(exp["season"].unique())]
    keys = ["manager_key", "season", "week", "player_id"]
    exp["player_id"] = exp["player_id"].astype("Int64")
    act = act.assign(player_id=act["player_id"].astype("Int64"))

    # Tied last place in a top-25 group: legacy's unstable sort kept another
    # player-week with the same points. Excuse only pairs at the group's cutoff.
    grp = ["manager_key", "season", "position"]
    in_exp = exp[keys].merge(act[keys].assign(_x=True), on=keys, how="left")["_x"].eq(True).to_numpy()
    in_act = act[keys].merge(exp[keys].assign(_x=True), on=keys, how="left")["_x"].eq(True).to_numpy()
    cutoff = act.groupby(grp)["points"].min().rename("cutoff").reset_index()

    def at_cutoff(df: pd.DataFrame) -> pd.DataFrame:
        d = df[grp + ["points"]].merge(cutoff, on=grp, how="left")
        return d[d["points"] == d["cutoff"]][grp + ["points"]].drop_duplicates()

    ties = at_cutoff(exp[~in_exp]).merge(at_cutoff(act[~in_act]), on=grp + ["points"])

    def keep(df: pd.DataFrame, matched: object) -> pd.DataFrame:
        tied = df[grp + ["points"]].merge(ties.assign(_t=True), on=grp + ["points"], how="left")["_t"].eq(True)
        return df[matched | ~tied.to_numpy()]

    exp_k, act_k = keep(exp, in_exp), keep(act, in_act)

    # Legacy counted 2020 regular-season bye weeks; the engine counts games
    # only. Set aside legacy rows from a week that manager had a bye, and the
    # engine rows that fill the freed top-25 places in those same groups.
    byes = tables["matchups"].loc[tables["matchups"]["is_bye"], ["season", "week", "manager_key"]]
    from_bye = exp_k[["season", "week", "manager_key"]].merge(byes.assign(_b=True), how="left")["_b"].eq(True).to_numpy()
    bye_groups = exp_k.loc[from_bye, grp].drop_duplicates()
    n_bye = int(from_bye.sum())
    exp_k = exp_k[~from_bye]
    in_exp_k = act_k[keys].merge(exp_k[keys].assign(_x=True), on=keys, how="left")["_x"].eq(True).to_numpy()
    in_bye_group = act_k[grp].merge(bye_groups.assign(_g=True), on=grp, how="left")["_g"].eq(True).to_numpy()
    n_fill = int((~in_exp_k & in_bye_group).sum())
    act_k = act_k[in_exp_k | ~in_bye_group]
    r = compare("best single weeks vs best_single_week.json", exp_k, act_k, keys=keys, values=["position", "points"])
    n = len(exp) - len(exp_k) - n_bye
    if n:
        r.known["tied last place in a top-25 group; legacy kept another player-week with the same points"] = n
    if n_bye:
        r.known["legacy counted a 2020 bye week (not a game); set aside"] = n_bye
    if n_fill:
        r.known["engine rows filling the top-25 places those bye weeks held"] = n_fill
    _note_names(r, exp)
    return r


def _note_names(r: Comparison, exp: pd.DataFrame) -> None:
    fuzzy = int(exp["name_match"].isin(["normalized", "surname"]).sum())
    if fuzzy:
        r.known["legacy name spelled differently (suffix, punctuation, or nickname); matched to the ESPN player"] = fuzzy


def through_golden_weeks(tables: dict, games_json: list[dict]) -> dict:
    """Cut each season's weeks at the last week the site files cover. The
    live season keeps moving (the site files stop at the week they were last
    updated), so later weeks would show up as rows the legacy files lack."""
    last = pd.DataFrame([(g["season"], g["week"]) for g in games_json], columns=["season", "week"]).groupby("season")["week"].max()
    out = dict(tables)
    for name in ("matchups", "lineups"):
        df = tables[name]
        cap = df["season"].map(last)
        out[name] = df[cap.isna() | (df["week"] <= cap)]
    return out


def verify_records(tables: dict, golden: dict, cfg: dict) -> list[Comparison]:
    from engine.legacy_trades import legacy_positions

    adjusted, _ = legacy_positions(tables, golden["weekly_rosters_bracket_only"], cfg)
    adjusted = through_golden_weeks(adjusted, golden["matchups"])
    analysis = records_mod.analyze_records(adjusted, excluded_manager_keys(cfg))
    return [
        check_games(analysis, golden["matchups"], cfg),
        check_lineup_efficiency(analysis, golden["lineup_efficiency"], golden["matchup_data"], cfg),
        check_blunders(analysis, golden["lineup_blunders"], cfg),
        check_franchise_leaders(analysis, golden["franchise_leaders"], adjusted, cfg),
        check_best_weeks(analysis, golden["best_single_week"], adjusted, cfg),
    ]
