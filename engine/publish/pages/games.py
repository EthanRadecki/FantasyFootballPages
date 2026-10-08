"""Games: matchups.html (every counted game with box scores) and the
matchup_data.csv that managers.html reads.

Outputs
    data/v1/matchups.json    page model (schema "matchups")
    data/matchups.json       legacy view (matchups.html today)
    data/matchup_data.csv    legacy view (managers.html today): every finished
                             game, consolation games included, one row per team

Stage A checks: each legacy view, built from legacy-mode inputs, against its
golden, with the excuses the analyze checks already carry.
"""

from __future__ import annotations

import json

import pandas as pd

from engine.analytics import records as records_mod
from engine.analytics import weeks as weeks_mod
from engine.config import excluded_games, excluded_manager_keys
from engine.legacy import Comparison, compare, legacy_week, name_to_key, resolve_names
from engine.legacy_records import _sides, _tie_groups, through_golden_weeks
from engine.publish.build import Output
from engine.publish.legacy_view import Names, csv_text, info_diff, site_csv, site_json

SCHEMA = "matchups"
VERSION = 1
RESULT_WORD = {"W": "Win", "L": "Loss", "T": "Tie"}


# ---------------------------------------------------------------- shared inputs

def box_lists(box: pd.DataFrame) -> dict:
    """(season, week, manager_key) -> (starters, bench), each a list of player dicts in display order."""
    out = {}
    for key, grp in box.sort_values("order").groupby(["season", "week", "manager_key"], sort=False):
        rows = [{"player_id": int(r.player_id), "name": r.player_name, "pos": r.position, "slot": r.slot,
                 "pts": float(r.points)} for r in grp.itertuples()]
        roles = grp["role"].tolist()
        out[(int(key[0]), int(key[1]), key[2])] = ([p for p, r in zip(rows, roles) if r == "starter"],
                                                    [p for p, r in zip(rows, roles) if r == "bench"])
    return out


def legacy_records(ctx) -> dict:
    """The records analysis on legacy inputs, as `analyze --verify` runs it:
    legacy positions put back, weeks cut at the last week the site files cover."""
    def run():
        from engine.legacy_trades import legacy_positions

        adjusted, _ = legacy_positions(ctx.tables, ctx.golden["weekly_rosters_bracket_only"], ctx.cfg)
        adjusted = through_golden_weeks(adjusted, ctx.golden["matchups"])
        return adjusted, records_mod.analyze_records(adjusted, excluded_manager_keys(ctx.cfg))
    return ctx.memo("legacy_records", run)


# ---------------------------------------------------------------- page model

def matchups_model(ctx, games: pd.DataFrame, box: pd.DataFrame) -> dict:
    rounds = {s["season"]: s["rounds"] for s in ctx.config["seasons"]}
    ppg_out = excluded_games(ctx.cfg, "ppg")
    lists = box_lists(box)
    out = []
    for g in games.itertuples():
        season, week = int(g.season), int(g.week)
        teams = []
        for side in ("a", "b"):
            key = getattr(g, f"team_{side}_key")
            starters, bench = lists.get((season, week, key), ([], []))
            teams.append({"manager_key": key, "team_id": int(getattr(g, f"team_{side}_id")),
                          "team_name": getattr(g, f"team_{side}_name"),
                          "points": float(getattr(g, f"team_{side}_points")),
                          "result": getattr(g, f"team_{side}_result"), "starters": starters, "bench": bench})
            if getattr(g, "weeks", 1) > 1:          # a two-week round: ESPN's total beside the per-week score
                teams[-1]["points_total"] = float(getattr(g, f"team_{side}_total"))
        out.append({
            "id": f"{season}-{week}-{int(g.game_id)}", "season": season, "week": week,
            "round": rounds.get(season, {}).get(str(week)) if g.is_playoff else None,
            "is_playoff": bool(g.is_playoff),
            "superlative_excluded": any((season, week, t["manager_key"]) in ppg_out for t in teams),
            "teams": teams, "margin": float(g.margin), "combined": float(g.combined),
            **({"weeks": int(g.weeks), "first_week": int(g.first_week)} if getattr(g, "weeks", 1) > 1 else {}),
        })
    return {"games": out}


# ---------------------------------------------------------------- legacy views

def matchups_view(games: pd.DataFrame, box: pd.DataFrame, names: Names) -> list[dict]:
    """data/matchups.json as matchups.html reads it."""
    lists = box_lists(box)

    def side(g, s):
        key = getattr(g, f"team_{s}_key")
        starters, bench = lists.get((int(g.season), int(g.week), key), ([], []))
        strip = lambda ps: [{"name": p["name"], "pos": p["pos"], "slot": p["slot"], "pts": p["pts"]} for p in ps]
        return {"manager": names(key), "lastName": names.short(key), "fantasyTeam": getattr(g, f"team_{s}_name"),
                "score": float(getattr(g, f"team_{s}_points")), "outcome": RESULT_WORD[getattr(g, f"team_{s}_result")],
                "starters": strip(starters), "bench": strip(bench)}

    out = []
    for g in games.itertuples():
        a, b = side(g, "a"), side(g, "b")
        tag = lambda n: n.replace(" ", "").replace(".", "")
        pair = "-".join(sorted([tag(a["manager"]), tag(b["manager"])]))     # the page keys superlative exclusions on this
        out.append({"id": f"{int(g.season)}-{int(g.week)}-{pair}",
                    "season": int(g.season), "week": int(g.week), "weekLabel": g.week_label,
                    "isPlayoff": bool(g.is_playoff), "teamA": a, "teamB": b,
                    "margin": float(g.margin), "combined": float(g.combined)})
    return out


def matchup_data_view(tables: dict, names: Names) -> str:
    """data/matchup_data.csv: every finished game (consolation included, byes
    left out), one row per team; Is_Playoff = Yes for winners-bracket games."""
    m = tables["matchups"].merge(weeks_mod.completed_weeks(tables), on=["season", "week"])
    m = m[~m["is_bye"] & m["result"].isin(["W", "L", "T"])].sort_values(["season", "week", "game_id", "team_id"])
    reg = dict(zip(tables["seasons"]["season"], tables["seasons"]["regular_season_periods"]))
    df = pd.DataFrame({
        "Team_Name": m["manager_key"].map(names), "Outcome": m["result"].map(RESULT_WORD),
        "Team_Score": m["points"].astype(float), "Opponent_Name": m["opponent_manager_key"].map(names),
        "Opponent_Score": m["opponent_points"].astype(float),
        "Week": [records_mod.week_label(reg, s, w) for s, w in zip(m["season"], m["week"])],
        "Season_Year": m["season"].astype(int), "Is_Playoff": m["tier"].eq("WINNERS_BRACKET").map({True: "Yes", False: "No"}),
    })
    df.index = range(1, len(df) + 1)
    return csv_text(df, index_label="")


# ---------------------------------------------------------------- Stage A checks

def check_matchups_view(view: list[dict], golden: list[dict], cfg: dict) -> Comparison:
    """The generated matchups.json against the site's, compared the way check_games does."""
    lookup = name_to_key(cfg)
    exp, act = _sides(golden, lookup), _sides(view, lookup)
    for df in (exp, act):
        df["starters"] = df["starters"].map(json.dumps)
        df["bench_ties"] = df["bench"].map(_tie_groups)
    ids = lambda games: {(g["season"], g["week"], lookup[g[s]["manager"].strip().lower()]): g["id"]
                         for g in games for s in ("teamA", "teamB")}
    for df, games in ((exp, golden), (act, view)):
        m = ids(games)
        df["game_id_text"] = [m[k] for k in zip(df["season"], df["week"], df["manager_key"])]
    r = compare("legacy view data/matchups.json vs matchups.json", exp, act, keys=["season", "week", "manager_key"],
                values=["week_label", "is_playoff", "team_name", "points", "result", "starters", "bench_ties",
                        "game_id_text"])
    both = exp.merge(act, on=["season", "week", "manager_key"], suffixes=("_l", "_e"))
    swapped = int((both["side_l"] != both["side_e"]).sum())
    if swapped:
        r.known["team A/B listed in the other order (late-2025 and 2026 games); compared by manager"] = swapped
    ties = int((both["bench_l"].map(json.dumps) != both["bench_e"].map(json.dumps)).sum())
    if ties:
        r.known["bench players tied on points listed in another order"] = ties
    return r


def parse_matchup_data(text_or_df, tables: dict, cfg: dict) -> pd.DataFrame:
    """A matchup_data.csv back into canonical matchups columns."""
    import io
    md = pd.read_csv(io.StringIO(text_or_df)) if isinstance(text_or_df, str) else text_or_df
    lookup = name_to_key(cfg)
    reg = dict(zip(tables["seasons"]["season"], tables["seasons"]["regular_season_periods"]))
    return pd.DataFrame({
        "season": md["Season_Year"].astype(int),
        "week": legacy_week(md["Week"], md["Season_Year"], reg),
        "manager_key": resolve_names(md["Team_Name"], lookup),
        "opponent_manager_key": resolve_names(md["Opponent_Name"], lookup),
        "points": md["Team_Score"].astype(float), "opponent_points": md["Opponent_Score"].astype(float),
        "result": md["Outcome"].map({"Win": "W", "Loss": "L", "Tie": "T"}),
        "tier": md["Is_Playoff"].map({"Yes": "WINNERS_BRACKET", "No": "OTHER"}), "is_bye": False,
    })


def check_matchup_data_view(text: str, golden: pd.DataFrame, tables: dict, cfg: dict) -> Comparison:
    """The generated matchup_data.csv, read back, through legacy.check_matchups."""
    from engine.legacy import check_matchups

    parsed = parse_matchup_data(text, tables, cfg)
    r = check_matchups({"seasons": tables["seasons"], "matchups": parsed}, golden, cfg)
    r.name = "legacy view data/matchup_data.csv vs matchup_data.csv"
    return r


class GamesPublisher:
    name = "games"

    def outputs(self, ctx) -> list[Output]:
        a = ctx.analysis
        if "games" not in a or "box_scores" not in a:
            return []
        games, box = a["games"], a["box_scores"]
        site_games = site_json(ctx, "data/matchups.json") or []
        site_md = site_csv(ctx, "data/matchup_data.csv")
        g_names = Names(ctx, [s[t]["manager"] for s in site_games for t in ("teamA", "teamB")])
        md_names = Names(ctx, [] if site_md is None else site_md["Team_Name"])
        return [
            Output("data/v1/matchups.json", matchups_model(ctx, games, box), SCHEMA, VERSION),
            Output("data/matchups.json", matchups_view(games, box, g_names)),
            Output("data/matchup_data.csv", matchup_data_view(ctx.tables, md_names)),
        ]

    def verify(self, ctx) -> list[Comparison]:
        if "games" not in ctx.analysis:
            return []
        adjusted, legacy = legacy_records(ctx)
        golden_games = ctx.golden["matchups"]
        names = Names(ctx, [s[t]["manager"] for s in golden_games for t in ("teamA", "teamB")])
        view = matchups_view(legacy["games"], legacy["box_scores"], names)
        md_golden = ctx.golden["matchup_data"]
        md_names = Names(ctx, md_golden["Team_Name"])
        finished = {int(s) for s in md_golden["Season_Year"].unique()}
        t = dict(ctx.tables)
        t["matchups"] = ctx.tables["matchups"][ctx.tables["matchups"]["season"].isin(finished)]
        checks = [check_matchups_view(view, golden_games, ctx.cfg),
                  check_matchup_data_view(matchup_data_view(t, md_names), md_golden, ctx.tables, ctx.cfg)]
        # what the live site will change to at M1: engine data against the live files
        lookup = name_to_key(ctx.cfg)
        live = site_json(ctx, "data/matchups.json")
        if live is not None:
            eng = matchups_view(ctx.analysis["games"], ctx.analysis["box_scores"], names)
            checks.append(info_diff("data/matchups.json", _sides(live, lookup), _sides(eng, lookup),
                                    ["season", "week", "manager_key"], ["points", "result", "team_name"]))
        live_md = site_csv(ctx, "data/matchup_data.csv")
        if live_md is not None:
            eng_md = parse_matchup_data(matchup_data_view(ctx.tables, md_names), ctx.tables, ctx.cfg)
            checks.append(info_diff("data/matchup_data.csv", parse_matchup_data(live_md, ctx.tables, ctx.cfg), eng_md,
                                    ["season", "week", "manager_key"], ["points", "opponent_points", "result", "tier"]))
        return checks
