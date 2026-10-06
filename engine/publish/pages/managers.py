"""Managers: index.html's leaderboard and managers.html's profiles.

Outputs
    data/v1/index.json               page model (schema "index"): leaderboard, current champion
    data/v1/managers/<key>.json      page model (schema "manager"), one per visible manager:
                                     career, seasons, head-to-head, rivals, weekly scores,
                                     schedule luck, franchise leaders, roster stints, best weeks,
                                     draft profile (10 dimensions) and draft board map
    data/preach_manager_stats.csv    legacy view (index.html, managers.html)
    data/franchise_leaders.json      legacy view (managers.html)
    data/best_single_week.json       legacy view (managers.html)
    data/roster_stints.json          legacy view (managers.html)
    pages/managers.html              the page with its inline HEATMAP_DATA replaced (the draft
                                     board performance map, engine/publish/pages/board_map.py)

The math index.html and managers.html did in the browser (data-engine.js:
career totals, ranks, head-to-head, rivals, league averages) is done here,
once. Hidden managers are left out of every manager-level list and rank
(decision 7.3); they still count in league averages.

The draft fingerprint radar's inline FINGERPRINTS (7 measures, retired with
generate_fingerprints.py) is left as it is in Stage A; Stage B rebuilds the
radar on the 10-dimension draft profile the manager files carry.
"""

from __future__ import annotations

import io

import pandas as pd

from engine.analytics import manager_seasons as ms_mod
from engine.analytics import waivers as waivers_mod
from engine.config import conference_labels, excluded_games, excluded_manager_keys
from engine.legacy import Comparison, attach_player_ids, compare, name_to_key
from engine.legacy_manager_seasons import ESPN_COLS, KEYS, RECORD_COLS, _known, legacy_frame
from engine.legacy_records import _per_manager, check_best_weeks, check_franchise_leaders
from engine.legacy_waivers import check_roster_stints
from engine.publish.build import Output
from engine.publish.diff import compare_json
from engine.publish.legacy_view import (Names, csv_text, info_diff, page_roundtrip, read_literal, replace_literal,
                                        site_csv, site_json)
from engine.publish.pages.board_map import board_map_view
from engine.publish.pages.games import legacy_records
from engine.publish.writer import clean

INDEX_SCHEMA, MANAGER_SCHEMA, VERSION = "index", "manager", 1
PAGE = "pages/managers.html"
STATS_COLUMNS = ["Rank_Win%_Overall", "Rank_PPG_Overall", "Weighted_Rank_Ovr", "Weighted_Rank_Overall_Value", "Year",
                 "Placement_within_Year", "Team", "Manager", "Conference", "W", "L", "GP", "W%", "PF", "PA", "PF/G",
                 "PF/G_Rank_within_Year", "PA/G", "PA/G_Rank_within_Year", "Luck_Rating", "LR_zscore",
                 "Dominance_Score", "DIFF", "Playoffs", "Champ_App", "Champ_W", "Draft_Slot"]


# ---------------------------------------------------------------- career and leaderboard

def flag(s: pd.Series) -> pd.Series:
    """A nullable yes/no column (unknown for the live season) as plain booleans, unknown = no."""
    return s.astype("boolean").fillna(False).astype(bool)


def _pct(w: float, l: float, t: float) -> float:
    n = w + l + t
    return (w + 0.5 * t) / n if n else 0.0


def career(ms: pd.DataFrame, hidden: set[str]) -> pd.DataFrame:
    """One row per visible manager over every season in manager_seasons (the
    live season included, as the site shows it), with visible-only ranks."""
    rows = []
    for key, g in ms[~ms["manager_key"].isin(hidden)].groupby("manager_key"):
        g = g.sort_values("season")
        pct = [_pct(w, l, t) for w, l, t in zip(g["wins"], g["losses"], g["ties"])]
        g = g.assign(_pct=pct)
        best = g.sort_values(["_pct", "season"], ascending=[False, True]).iloc[0]
        worst = g.sort_values(["_pct", "season"], ascending=[True, False]).iloc[0]
        w, l, t = int(g["wins"].sum()), int(g["losses"].sum()), int(g["ties"].sum())
        rows.append({
            "manager_key": key, "seasons": int(len(g)), "first_season": int(g["season"].min()),
            "last_season": int(g["season"].max()), "wins": w, "losses": l, "ties": t, "win_pct": _pct(w, l, t),
            "playoffs": int(flag(g["made_playoffs"]).sum()), "championships": int(flag(g["champion"]).sum()),
            "champion_seasons": [int(s) for s in g.loc[flag(g["champion"]), "season"]],
            "avg_pf_per_game": float(g["pf_per_game"].mean()), "avg_pa_z": float(g["pa_z"].mean()),
            "best_season": {"season": int(best["season"]), "wins": int(best["wins"]), "losses": int(best["losses"]),
                            "ties": int(best["ties"])},
            "worst_season": {"season": int(worst["season"]), "wins": int(worst["wins"]),
                             "losses": int(worst["losses"]), "ties": int(worst["ties"])},
        })
    out = pd.DataFrame(rows)
    if len(out):
        for col, asc in (("wins", False), ("losses", True), ("win_pct", False), ("playoffs", False),
                         ("championships", False), ("avg_pf_per_game", False), ("avg_pa_z", True)):
            out[f"rank_{col}"] = out[col].rank(ascending=asc, method="min").astype(int)
        out = out.sort_values(["win_pct", "wins"], ascending=False, kind="stable").reset_index(drop=True)
    return out


def _career_record(r: pd.Series) -> dict:
    ranks = {c[5:]: int(r[c]) for c in r.index if c.startswith("rank_")}
    return {k: clean(r[k]) for k in r.index if not k.startswith("rank_")} | {"ranks": ranks}


def index_model(ctx, ms: pd.DataFrame, hidden: set[str]) -> dict:
    board = career(ms, hidden)
    finished = ms[~ms["is_live"].astype(bool) & flag(ms["champion"])].sort_values("season")
    champ = None
    if len(finished):
        c = finished.iloc[-1]
        champ = {"season": int(c["season"]), "manager_key": c["manager_key"], "team_name": c["team_name"]}
    return {"leaderboard": [_career_record(r) for _, r in board.iterrows()], "champion": champ,
            "visible_managers": int(len(board))}


# ---------------------------------------------------------------- manager files

SEASON_COLS = ["season", "team_name", "conference", "wins", "losses", "ties", "games", "win_pct", "points_for",
               "points_against", "pf_per_game", "pa_per_game", "point_diff_per_game", "pf_rank", "pa_rank",
               "luck_rating", "dominance", "pa_z", "final_rank", "playoff_seed", "made_playoffs", "champion",
               "draft_slot", "is_live"]


def regular_weeks(ctx, games: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Each team's regular-season games, and the league's average score per
    week (games excluded from points per game left out of the average)."""
    reg = {s["season"]: s["regular_season_weeks"] for s in ctx.config["seasons"]}
    g = games[[w <= reg.get(int(s), 0) for s, w in zip(games["season"], games["week"])]]
    sides = pd.concat([
        pd.DataFrame({"season": g["season"], "week": g["week"], "manager_key": g[f"team_{s}_key"],
                      "opponent_key": g[f"team_{o}_key"], "points": g[f"team_{s}_points"],
                      "result": g[f"team_{s}_result"]}) for s, o in (("a", "b"), ("b", "a"))], ignore_index=True)
    out = excluded_games(ctx.cfg, "ppg")
    sides["excluded_from_ppg"] = [(int(s), int(w), k) in out for s, w, k in
                                  zip(sides["season"], sides["week"], sides["manager_key"])]
    avg = (sides[~sides["excluded_from_ppg"]].groupby(["season", "week"])["points"].agg(["mean", "median"])
           .rename(columns={"mean": "league_avg", "median": "league_median"}).reset_index())
    return sides.sort_values(["season", "week"]), avg


def rivals(h2h: pd.DataFrame) -> dict:
    """Best and worst head-to-head record (win % over games, ties half); ties
    broken by more games played, then opponent key, so the pick is stable."""
    if not len(h2h):
        return {"best": None, "worst": None}
    h = h2h.assign(_pct=[_pct(w, l, t) for w, l, t in zip(h2h["wins"], h2h["losses"], h2h["ties"])])
    best = h.sort_values(["_pct", "games", "opponent_key"], ascending=[False, False, True]).iloc[0]
    worst = h.sort_values(["_pct", "games", "opponent_key"], ascending=[True, False, True]).iloc[0]
    pick = lambda r: {"opponent_key": r["opponent_key"], "wins": int(r["wins"]), "losses": int(r["losses"]),
                      "ties": int(r["ties"]), "win_pct": float(r["_pct"])}
    return {"best": pick(best), "worst": pick(worst)}


def manager_models(ctx, a: dict, hidden: set[str]) -> dict[str, dict]:
    ms = a["manager_seasons"]
    board = career(ms, hidden).set_index("manager_key")
    sides, avg = regular_weeks(ctx, a["games"])
    sides = sides.merge(avg, on=["season", "week"], how="left")
    league_pfg = ms.groupby("season")["pf_per_game"].mean()
    h2h = a["head_to_head"]
    h2h = h2h[~h2h["opponent_key"].isin(hidden)]
    luck = a.get("schedule_luck", pd.DataFrame(columns=["manager_key"]))
    fl, rs, bw = a["franchise_leaders"], a["roster_stints"], a["best_weeks"]
    boards = draft_boards(ctx, a, hidden, lambda k: k)
    profiles = draft_profiles(a)
    out = {}
    for key in board.index:
        mine = lambda df: df[df["manager_key"] == key]
        seasons = mine(ms).sort_values("season")
        h = mine(h2h).sort_values("opponent_key")
        stints = mine(rs).sort_values(["season", "start", "player_name"])
        out[key] = {
            "manager_key": key,
            "career": _career_record(pd.concat([pd.Series({"manager_key": key}), board.loc[key]])),
            "seasons": [clean(r) for r in seasons[SEASON_COLS].to_dict(orient="records")],
            "league_pf_per_game": {str(int(s)): float(v) for s, v in league_pfg.items()},
            "head_to_head": [{"opponent_key": r.opponent_key, "wins": int(r.wins), "losses": int(r.losses),
                              "ties": int(r.ties)} for r in h.itertuples()],
            "rivals": rivals(h),
            "weeks": [{"season": int(r.season), "week": int(r.week), "opponent_key": r.opponent_key,
                       "points": float(r.points), "result": r.result, "excluded_from_ppg": bool(r.excluded_from_ppg),
                       "league_avg": float(r.league_avg), "league_median": float(r.league_median)}
                      for r in mine(sides).itertuples()],
            "schedule_luck": [{"season": int(r.season), "games": int(r.games), "actual_wins": float(r.actual_wins),
                               "expected_wins": float(r.expected_wins), "luck": float(r.schedule_luck)}
                              for r in mine(luck).sort_values("season").itertuples()],
            "franchise_leaders": [{"player_id": int(r.player_id), "name": r.player_name, "position": r.position,
                                   "season": int(r.season), "weeks_rostered": int(r.weeks_rostered),
                                   "games_played": int(r.games_played), "total_points": round(float(r.total_points), 2)}
                                  for r in mine(fl).sort_values(["season", "player_name"]).itertuples()],
            "roster_stints": [{"player_id": int(r.player_id), "name": r.player_name, "position": r.position,
                               "season": int(r.season), "start": int(r.start), "end": int(r.end),
                               "started": [int(x) for x in str(r.started).split(",") if x]}
                              for r in stints.itertuples()],
            "best_weeks": [{"player_id": int(r.player_id), "name": r.player_name, "position": r.position,
                            "season": int(r.season), "week": int(r.week), "points": round(float(r.points), 2)}
                           for r in mine(bw).sort_values(["points", "season", "week"],
                                                         ascending=[False, True, True]).itertuples()],
        }
        if key in profiles:
            out[key]["draft_profile"] = profiles[key]
        if key in boards:
            out[key]["draft_board"] = boards[key]
    return out


DRAFT_NEEDS = ("draft_surplus", "draft_career_grades")


def draft_boards(ctx, a: dict, hidden: set[str], names) -> dict:
    """The draft board map per manager (finished seasons), or {} without draft tables."""
    if not all(n in a and len(a[n]) for n in DRAFT_NEEDS):
        return {}
    seasons = sorted(set(int(x) for x in a["draft_surplus"]["season"]) & set(ctx.config["finished_seasons"]))
    return board_map_view(a["draft_surplus"], a["draft_career_grades"], seasons, hidden, names)


def draft_profiles(a: dict) -> dict:
    """The 10-dimension draft profile per manager: each season (live included) and career."""
    from engine.analytics.draft_profiles import RADAR

    s, c = a.get("draft_profile_seasons"), a.get("draft_profile_career")
    if s is None or c is None or not len(s):
        return {}
    dims = [d for d in RADAR if d in s]
    entry = lambda r: {"raw": {d: clean(r[d]) for d in dims},
                       "normalized": {d: clean(r.get(f"norm_{d}")) for d in dims}}
    out = {}
    for key, g in s.sort_values("season").groupby("manager_key"):
        out[key] = {"dims": dims, "seasons": [{"season": int(r["season"]), "live": bool(r["live"]),
                                               "cluster": None if pd.isna(r["cluster"]) else int(r["cluster"]),
                                               **entry(r)} for _, r in g.iterrows()],
                    "career": None}
    for _, r in c.iterrows():
        if r["manager_key"] in out:
            out[r["manager_key"]]["career"] = {"seasons": int(r["n_seasons"]), **entry(r)}
    return out


# ---------------------------------------------------------------- legacy views

def stats_view(ms: pd.DataFrame, names: Names) -> str:
    """data/preach_manager_stats.csv. The four all-time rank columns are left
    blank: no page reads them and no script ever produced them."""
    ms = ms.sort_values(["season", "final_rank", "playoff_seed"], kind="stable")
    live = ms["is_live"].astype(bool)
    placement = ms["final_rank"].where(~live, ms["playoff_seed"])
    df = pd.DataFrame({
        "Rank_Win%_Overall": None, "Rank_PPG_Overall": None, "Weighted_Rank_Ovr": None,
        "Weighted_Rank_Overall_Value": None, "Year": ms["season"].astype(int),
        "Placement_within_Year": placement.astype("Int64"), "Team": ms["team_name"],
        "Manager": ms["manager_key"].map(names), "Conference": ms["conference"],
        "W": ms["wins"].astype(int), "L": ms["losses"].astype(int), "GP": ms["games"].astype(int),
        "W%": ms["win_pct"].round(9), "PF": ms["points_for"].round(2), "PA": ms["points_against"].round(2),
        "PF/G": ms["pf_per_game"].round(9), "PF/G_Rank_within_Year": ms["pf_rank"].astype("Int64"),
        "PA/G": ms["pa_per_game"].round(9), "PA/G_Rank_within_Year": ms["pa_rank"].astype("Int64"),
        "Luck_Rating": ms["luck_rating"].astype("Int64"), "LR_zscore": ms["pa_z"].round(9),
        "Dominance_Score": ms["dominance"].round(9), "DIFF": ms["point_diff_per_game"].round(9),
        "Playoffs": flag(ms["made_playoffs"]).astype(int), "Champ_App": flag(ms["champion_appearance"]).astype(int),
        "Champ_W": flag(ms["champion"]).astype(int), "Draft_Slot": ms["draft_slot"].astype("Int64"),
    })
    return csv_text(df[STATS_COLUMNS])


def franchise_view(fl: pd.DataFrame, names: Names) -> dict:
    out = {}
    for key, g in fl.sort_values(["season", "player_name", "position"]).groupby("manager_key", sort=False):
        out[names(key)] = [{"player": r.player_name, "position": r.position, "season": int(r.season),
                            "weeks_rostered": int(r.weeks_rostered), "games_played": int(r.games_played),
                            "total_points": round(float(r.total_points), 2)} for r in g.itertuples()]
    return dict(sorted(out.items()))


def best_week_view(bw: pd.DataFrame, names: Names) -> dict:
    out = {}
    order = bw.sort_values(["points", "season", "week"], ascending=[False, True, True], kind="stable")
    for key, g in order.groupby("manager_key", sort=False):
        out[names(key)] = [{"player": r.player_name, "position": r.position, "season": int(r.season),
                            "week": int(r.week), "points": round(float(r.points), 1)} for r in g.itertuples()]
    return dict(sorted(out.items()))


def roster_stint_view(rs: pd.DataFrame, names: Names) -> dict:
    """{manager: {player name: {position (from the earliest stint), stints}}}."""
    out = {}
    rs = rs[~rs["hidden"]].sort_values(["season", "start"])
    for (key, player), g in rs.groupby(["manager_key", "player_name"], sort=True):
        entry = out.setdefault(names(key), {}).setdefault(player, {"position": g["position"].iloc[0], "stints": []})
        entry["stints"] += [{"season": int(r.season), "start": int(r.start), "end": int(r.end),
                             "started": [int(x) for x in str(r.started).split(",") if x]} for r in g.itertuples()]
    for m in out.values():
        for v in m.values():
            v["stints"].sort(key=lambda s: (s["season"], s["start"]))
    return dict(sorted(out.items()))


# ---------------------------------------------------------------- Stage A checks

def _legacy_seasons(ctx) -> pd.DataFrame:
    """manager_seasons in legacy mode: finished seasons, plus each live
    season cut at the week the site file's snapshot was taken."""
    gold = legacy_frame(ctx.golden["preach_manager_stats"], ctx.cfg)
    live = {s["season"] for s in ctx.config["seasons"] if s["live"]}
    ex, labels = excluded_manager_keys(ctx.cfg), conference_labels(ctx.cfg)
    parts = [ms_mod.manager_seasons(ctx.tables, ex, legacy_mode=True, conference_labels=labels)]
    parts[0] = parts[0][~parts[0]["season"].isin(live)]
    for season in sorted(live & set(gold["season"])):
        weeks = int(gold.loc[gold["season"] == season, "games"].max())
        t = dict(ctx.tables)
        m = ctx.tables["matchups"]
        t["matchups"] = m[(m["season"] != season) | (m["week"] <= weeks)]
        snap = ms_mod.manager_seasons(t, ex, legacy_mode=True, conference_labels=labels)
        parts.append(snap[snap["season"] == season])
    return pd.concat(parts, ignore_index=True)


def check_stats_view(text: str, ctx) -> list[Comparison]:
    exp_all = legacy_frame(ctx.golden["preach_manager_stats"], ctx.cfg)
    act_all = legacy_frame(pd.read_csv(io.StringIO(text)), ctx.cfg)
    md = ctx.golden["matchup_data"]
    live = {s["season"] for s in ctx.config["seasons"] if s["live"]}
    out = []
    exp, act = exp_all[~exp_all["season"].isin(live)], act_all[~act_all["season"].isin(live)]
    out.append(compare("legacy view data/preach_manager_stats.csv (finished seasons) vs preach_manager_stats.csv",
                       exp, act[act["season"].isin(set(exp["season"]))], keys=KEYS,
                       values=RECORD_COLS + ESPN_COLS + ["conference"], tolerance=1e-6, known=_known(exp, act, md, ctx.cfg)))
    for season in sorted(live & set(exp_all["season"])):
        e, a = exp_all[exp_all["season"] == season], act_all[act_all["season"] == season]
        out.append(compare(f"legacy view data/preach_manager_stats.csv ({season} snapshot) vs preach_manager_stats.csv",
                           e, a, keys=KEYS, values=RECORD_COLS + ["draft_slot"], tolerance=1e-6,
                           known=_known(e, a, md, ctx.cfg)))
    return out


def _parsed(view: dict, lineups: pd.DataFrame, players: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    return attach_player_ids(_per_manager(view, name_to_key(cfg)), lineups, players, ["manager_key", "season"])


def _roster_frame(view: dict, rs: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    lk = name_to_key(cfg)
    ids = rs.drop_duplicates(["manager_key", "player_name"]).set_index(["manager_key", "player_name"])["player_id"]
    rows = [{"manager_key": lk[m.strip().lower()], "player_name": p, "position": v["position"], "season": s["season"],
             "start": s["start"], "end": s["end"], "started": ",".join(str(w) for w in s["started"]), "hidden": False}
            for m, d in view.items() for p, v in d.items() for s in v["stints"]]
    out = pd.DataFrame(rows)
    out["player_id"] = [ids.get((k, p)) for k, p in zip(out["manager_key"], out["player_name"])]
    return out


def legacy_roster_stints(ctx) -> pd.DataFrame:
    """Roster stints on legacy inputs, as `analyze --verify` builds them."""
    from engine.legacy_trades import legacy_positions

    stints = [s for d in ctx.golden["roster_stints"].values() for v in d.values() for s in v["stints"]]
    top = max(s["season"] for s in stints)
    last = max(s["end"] for s in stints if s["season"] == top)
    rt = dict(ctx.tables)
    for n in ("matchups", "lineups"):
        df = ctx.tables[n]
        rt[n] = df[(df["season"] < top) | (df["week"] <= last)]
    rt, _ = legacy_positions(rt, ctx.golden["weekly_rosters_bracket_only"], ctx.cfg)
    return waivers_mod.roster_stints(rt, excluded_manager_keys(ctx.cfg))


def _heatmap_names(text: str) -> list[str]:
    """The page's spelling of each manager in HEATMAP_DATA."""
    try:
        return list(read_literal(text, "HEATMAP_DATA"))
    except (KeyError, ValueError):
        return []


class ManagersPublisher:
    name = "managers"
    NEEDS = ("manager_seasons", "games", "head_to_head", "franchise_leaders", "roster_stints", "best_weeks")

    def outputs(self, ctx) -> list[Output]:
        a = ctx.analysis
        if not all(n in a for n in self.NEEDS):
            return []
        hidden = excluded_manager_keys(ctx.cfg)
        outs = [Output("data/v1/index.json", index_model(ctx, a["manager_seasons"], hidden), INDEX_SCHEMA, VERSION)]
        for key, model in manager_models(ctx, a, hidden).items():
            outs.append(Output(f"data/v1/managers/{key}.json", model, MANAGER_SCHEMA, VERSION))
        stats = site_csv(ctx, "data/preach_manager_stats.csv")
        fl, bw, rs = (site_json(ctx, f"data/{n}.json") or {} for n in ("franchise_leaders", "best_single_week",
                                                                         "roster_stints"))
        outs += [
            Output("data/preach_manager_stats.csv",
                   stats_view(a["manager_seasons"], Names(ctx, [] if stats is None else stats["Manager"]))),
            Output("data/franchise_leaders.json", franchise_view(a["franchise_leaders"], Names(ctx, fl))),
            Output("data/best_single_week.json", best_week_view(a["best_weeks"], Names(ctx, bw))),
            Output("data/roster_stints.json", roster_stint_view(a["roster_stints"], Names(ctx, rs))),
        ]
        page = ctx.site_root / PAGE
        if ctx.legacy_site and page.is_file():
            text = page.read_text(encoding="utf-8")
            board = draft_boards(ctx, a, hidden, Names(ctx, _heatmap_names(text)))
            if board:
                outs.append(Output(PAGE, replace_literal(text, "HEATMAP_DATA", board)))
        return outs

    def verify(self, ctx) -> list:
        a = ctx.analysis
        if not all(n in a for n in self.NEEDS):
            return []
        g = ctx.golden
        checks = check_stats_view(stats_view(_legacy_seasons(ctx), Names(ctx, g["preach_manager_stats"]["Manager"])), ctx)
        adjusted, legacy = legacy_records(ctx)
        for key, view_fn, check_fn, table in (
                ("franchise_leaders", franchise_view, check_franchise_leaders, "franchise_leaders"),
                ("best_single_week", best_week_view, check_best_weeks, "best_weeks")):
            view = view_fn(legacy[table], Names(ctx, g[key]))
            parsed = _parsed(view, adjusted["lineups"], adjusted["players"], ctx.cfg)
            c = check_fn({table: parsed}, g[key], adjusted, ctx.cfg)
            c.name = f"legacy view data/{key}.json vs {key}.json"
            checks.append(c)
        rs = legacy_roster_stints(ctx)
        view = roster_stint_view(rs, Names(ctx, g["roster_stints"]))
        c = check_roster_stints(_roster_frame(view, rs, ctx.cfg), g["roster_stints"], ctx.cfg,
                                ctx.tables["lineups"][["player_id", "position"]].drop_duplicates())
        c.name = "legacy view data/roster_stints.json vs roster_stints.json"
        checks.append(c)
        checks += self.check_board_map(ctx)
        checks += self.info(ctx)
        return checks

    def check_board_map(self, ctx) -> list:
        """managers.html HEATMAP_DATA from the legacy-mode draft analysis vs draft_heatmap.json (= the page)."""
        from engine.publish.pages.draft_common import legacy_draft

        if not all(n in ctx.analysis for n in DRAFT_NEEDS):
            return []
        gold = ctx.golden["draft_heatmap"]
        legacy = legacy_draft(ctx)
        done = set(ctx.config["finished_seasons"])
        seasons = sorted(int(x) for x in legacy["draft_surplus"]["season"].unique() if int(x) in done)
        view = board_map_view(legacy["draft_surplus"], legacy["draft_career_grades"], seasons,
                              excluded_manager_keys(ctx.cfg), Names(ctx, list(gold)))
        page = ctx.site_root / PAGE
        if page.is_file():
            view = page_roundtrip(page.read_text(encoding="utf-8"), {"HEATMAP_DATA": view})["HEATMAP_DATA"]
        checks: list = compare_json(f"legacy view {PAGE} HEATMAP_DATA (draft_heatmap.json)", view, gold,
                                    by_section=False)
        if page.is_file():
            text = page.read_text(encoding="utf-8")
            live = read_literal(text, "HEATMAP_DATA")
            eng = draft_boards(ctx, ctx.analysis, excluded_manager_keys(ctx.cfg), Names(ctx, list(live)))
            cells = lambda d: {(m, c): x["avg_surplus"] for m, v in d.items() for c, x in v["board"].items()}
            lc, ec = cells(live), cells(eng)
            moved = sum(1 for k in lc.keys() & ec.keys() if abs(lc[k] - ec[k]) > 0.005)
            grade = sum(1 for m in live.keys() & eng.keys()
                        if abs((live[m]["career_wtd_avg"] or 0) - (eng[m]["career_wtd_avg"] or 0)) > 0.00005)
            checks.append(f"INFO  {PAGE} draft board map, engine data vs the live page: {len(lc.keys() & ec.keys())} "
                          f"cells in both, {moved} with a different average surplus, {len(ec.keys() - lc.keys())} only in "
                          f"the engine, {len(lc.keys() - ec.keys())} only in the live page; "
                          f"{grade} career grade(s) change")
        return checks

    def info(self, ctx) -> list[str]:
        """What the live page files change to at M1 (engine data vs the live files)."""
        a, out = ctx.analysis, []
        live_stats = site_csv(ctx, "data/preach_manager_stats.csv")
        if live_stats is not None:
            names = Names(ctx, live_stats["Manager"])
            eng = legacy_frame(pd.read_csv(io.StringIO(stats_view(a["manager_seasons"], names))), ctx.cfg)
            out.append(info_diff("data/preach_manager_stats.csv", legacy_frame(live_stats, ctx.cfg), eng, KEYS,
                                 ["wins", "losses", "points_for", "points_against", "pf_rank", "pa_rank", "draft_slot"]))
        lk = name_to_key(ctx.cfg)
        for key, fn, table, values in (
                ("franchise_leaders", franchise_view, "franchise_leaders", ["weeks_rostered", "games_played", "total_points"]),
                ("best_single_week", best_week_view, "best_weeks", ["points"])):
            live = site_json(ctx, f"data/{key}.json")
            if live is None:
                continue
            eng = pd.DataFrame(_per_manager(fn(a[table], Names(ctx, live)), lk))
            lv = pd.DataFrame(_per_manager(live, lk))
            k = ["manager_key", "season", "player"] + (["week"] if key == "best_single_week" else [])
            out.append(info_diff(f"data/{key}.json", lv.drop_duplicates(k), eng.drop_duplicates(k), k, values))
        live = site_json(ctx, "data/roster_stints.json")
        if live is not None:
            flat = lambda v: pd.DataFrame([{"manager_key": lk[m.strip().lower()], "player": p, "season": s["season"],
                                            "start": s["start"], "end": s["end"], "started": str(s["started"])}
                                           for m, d in v.items() for p, x in d.items() for s in x["stints"]])
            eng = roster_stint_view(a["roster_stints"], Names(ctx, live))
            out.append(info_diff("data/roster_stints.json", flat(live), flat(eng),
                                 ["manager_key", "player", "season", "start"], ["end", "started"]))
        return out
