"""Compare waiver stints, the waiver page aggregates, and roster stints with the legacy files.

Golden files (waivers/):
    waiver_stints_full.csv.gz   the legacy stint table (builder lost; the same
                                stints are inline on waiver-value.html)
    waiver_page.json.gz         LEADERBOARD_FULL, CONTESTED_SPLIT,
                                BEST_BY_MANAGER, BEST_PICKUPS_BY_FILTER from
                                waiver-value.html
    roster_stints.json.gz       data/roster_stints.json (managers page),
                                2020 through 2026 week 2

Legacy mode must reproduce the stint table and every page aggregate exactly.
Roster stints are keyed by player name on the site; names are matched after
normalizing suffixes and punctuation (2026 rows use ESPN's current names,
e.g. James Cook III).
"""

from __future__ import annotations

import gzip
import json

import numpy as np
import pandas as pd

from engine.analytics import waivers as waivers_mod
from engine.analytics.weeks import completed_weeks
from engine.config import excluded_manager_keys
from engine.legacy import Comparison, _name_norm, compare, name_to_key, resolve_names


def _legacy_tables(tables: dict, golden: dict, cfg: dict) -> dict:
    from engine.legacy_trades import legacy_positions

    t = dict(tables)
    t["matchups"] = tables["matchups"][tables["matchups"]["season"] <= 2025]
    t["lineups"] = tables["lineups"][tables["lineups"]["season"] <= 2025]
    t, _ = legacy_positions(t, golden["weekly_rosters_bracket_only"], cfg)
    return t


def check_stints(stints: pd.DataFrame, legacy: pd.DataFrame, cfg: dict) -> Comparison:
    exp = pd.DataFrame({
        "season": legacy["Season"].astype(int), "manager_key": resolve_names(legacy["Manager"], name_to_key(cfg)),
        "player_id": legacy["Player_ID"].astype(int), "start_week": legacy["Start_Week"].astype(int),
        "end_week": legacy["End_Week"], "type": legacy["Type"], "weeks_rostered": legacy["Weeks_Rostered"],
        "total_points": legacy["Total_Points"], "ppw": legacy["PPW"], "avg_z": legacy["Avg_Z"],
        "total_z": legacy["Total_Z"], "position": legacy["Position"]})
    act = stints.assign(avg_z=np.round(stints["avg_z"], 3), total_z=np.round(stints["total_z"], 3))
    return compare("waiver stints vs waiver_stints_full.csv", exp, act,
                   keys=["season", "manager_key", "player_id", "start_week"],
                   values=["end_week", "type", "weeks_rostered", "total_points", "ppw", "avg_z", "total_z", "position"],
                   tolerance=1e-9)


def _page_rows(block: dict, lookup: dict, fields: dict) -> pd.DataFrame:
    rows = []
    for scope, by_pos in block.items():
        for pos, items in by_pos.items():
            for r in items:
                rows.append({"scope": scope, "position": pos, "manager_key": lookup[r["m"].strip().lower()],
                             **{new: r[old] for old, new in fields.items()}})
    return pd.DataFrame(rows)


def check_leaderboard(board: pd.DataFrame, page: dict, cfg: dict) -> Comparison:
    exp = _page_rows(page["LEADERBOARD_FULL"], name_to_key(cfg), {"ppw": "ppw", "z": "z", "n": "pickups"})
    b = board[board["type"] == "ALL"]
    act = b.assign(ppw=np.round(b["ppw"], 2), z=np.round(b["z_per_week"], 3))
    return compare("waiver leaderboard vs LEADERBOARD_FULL", exp, act, keys=["scope", "position", "manager_key"],
                   values=["ppw", "z", "pickups"], tolerance=1e-9)


def check_contested(board: pd.DataFrame, page: dict, cfg: dict) -> Comparison:
    lk = name_to_key(cfg)
    exp = pd.DataFrame([{"manager_key": lk[r["m"].strip().lower()], "fa_ppw": r["faPpw"], "fa_z": r["faZ"],
                         "fa_n": r["faN"], "wv_ppw": r["wvPpw"], "wv_z": r["wvZ"], "wv_n": r["wvN"],
                         "career_ppw": r["careerPpw"], "career_z": r["careerZ"]} for r in page["CONTESTED_SPLIT"]])
    c = board[(board["scope"] == "career") & (board["position"] == "ALL")].set_index(["manager_key", "type"])
    rows = []
    for mk in exp["manager_key"]:
        get = lambda t, col, d: np.round(c.loc[(mk, t), col], d) if (mk, t) in c.index else np.nan
        rows.append({"manager_key": mk, "fa_ppw": get("FREEAGENT", "ppw", 2), "fa_z": get("FREEAGENT", "z_per_week", 3),
                     "fa_n": get("FREEAGENT", "pickups", 0), "wv_ppw": get("WAIVER", "ppw", 2),
                     "wv_z": get("WAIVER", "z_per_week", 3), "wv_n": get("WAIVER", "pickups", 0),
                     "career_ppw": get("ALL", "ppw", 2), "career_z": get("ALL", "z_per_week", 3)})
    return compare("waiver FA vs claim split vs CONTESTED_SPLIT", exp, pd.DataFrame(rows), keys=["manager_key"],
                   values=["fa_ppw", "fa_z", "fa_n", "wv_ppw", "wv_z", "wv_n", "career_ppw", "career_z"], tolerance=1e-9)


def _scoped(stints: pd.DataFrame) -> pd.DataFrame:
    parts = []
    for scope in ["career"] + sorted(stints["season"].astype(str).unique()):
        s = stints if scope == "career" else stints[stints["season"].astype(str) == scope]
        for pos in ["ALL"] + sorted(s["position"].unique()):
            parts.append((s if pos == "ALL" else s[s["position"] == pos]).assign(scope=scope, pos=pos))
    return pd.concat(parts, ignore_index=True).drop(columns="position")


def check_best(stints: pd.DataFrame, page: dict, cfg: dict) -> list[Comparison]:
    lk = name_to_key(cfg)
    sc = _scoped(stints)
    # best pickups: top 12 by total z in each scope and position
    exp = pd.DataFrame([{"scope": scope, "position": pos, "rank": i + 1, "season": r["s"],
                         "manager_key": lk[r["m"].strip().lower()], "weeks": r["wk"], "total_z": r["totalz"],
                         "avg_z": r["avgz"], "ppw": r["ppw"], "type": r["type"]}
                        for scope, by_pos in page["BEST_PICKUPS_BY_FILTER"].items() for pos, items in by_pos.items()
                        for i, r in enumerate(items)])
    top = waivers_mod.best_pickups(stints)
    act = top.drop(columns="position").rename(columns={"list_position": "position", "weeks_rostered": "weeks"})
    act = act.assign(total_z=np.round(act["total_z"], 3), avg_z=np.round(act["avg_z"], 3))
    # pickups tied on total z can sit in either order (legacy sort was not stable)
    both = exp.merge(act, on=["scope", "position", "rank"], suffixes=("_l", "_e"))
    tied = both[(both["total_z_l"] - both["total_z_e"]).abs() < 1e-9]
    dup = act.groupby(["scope", "position", "total_z"])["rank"].transform("size") > 1
    tie_keys = act.loc[dup, ["scope", "position", "rank"]].merge(tied[["scope", "position", "rank"]])
    known = pd.concat([tie_keys.assign(column=c, reason="pickups tied on total z; legacy's unstable sort kept the other order")
                       for c in ("season", "manager_key", "weeks", "avg_z", "ppw", "type")], ignore_index=True)
    best = compare("best pickups vs BEST_PICKUPS_BY_FILTER", exp, act, keys=["scope", "position", "rank"],
                   values=["season", "manager_key", "weeks", "total_z", "avg_z", "ppw", "type"], tolerance=1e-9,
                   known=known)
    exp2 = pd.DataFrame(
        [{"scope": scope, "position": pos, "manager_key": lk[m.strip().lower()], "total_z": r["tz"], "weeks": r["wk"]}
         for scope, by_pos in page["BEST_BY_MANAGER"].items() for pos, d in by_pos.items() for m, r in d.items()])
    bm = sc.sort_values("total_z", ascending=False, kind="stable").drop_duplicates(["scope", "pos", "manager_key"])
    act2 = bm.rename(columns={"pos": "position", "weeks_rostered": "weeks"})
    act2 = act2.assign(total_z=[round(float(v), 2) for v in act2["total_z"]])   # Python rounding, as the page
    per = compare("best pickup per manager vs BEST_BY_MANAGER", exp2, act2, keys=["scope", "position", "manager_key"],
                  values=["total_z", "weeks"], tolerance=1e-9)
    return [best, per]


def check_roster_stints(stints: pd.DataFrame, golden: dict, cfg: dict, positions: pd.DataFrame) -> Comparison:
    lk = name_to_key(cfg)
    exp = pd.DataFrame([{"manager_key": lk[m.strip().lower()], "name": _name_norm(p), "position": v["position"],
                         "season": s["season"], "start": s["start"], "end": s["end"],
                         "started": ",".join(str(w) for w in s["started"])}
                        for m, d in golden.items() for p, v in d.items() for s in v["stints"]])
    act = stints[~stints["hidden"]].assign(name=lambda d: d["player_name"].map(_name_norm))
    # the site kept one position per manager and player; where that is the
    # player's ESPN position from another season, it is the known legacy pattern
    other = positions.groupby("player_id")["position"].apply(set)
    both = exp.merge(act, on=["manager_key", "name", "season", "start"], suffixes=("_l", "_e"))
    ok = [pl in other.get(pid, set()) for pl, pid in zip(both["position_l"], both["player_id"])]
    known = both.loc[(both["position_l"] != both["position_e"]) & pd.Series(ok, index=both.index),
                     ["manager_key", "name", "season", "start"]].assign(
        column="position", reason="legacy kept a player's position from another season")
    return compare("roster stints vs roster_stints.json", exp, act, keys=["manager_key", "name", "season", "start"],
                   values=["end", "started", "position"], tolerance=1e-9, known=known)


def verify_waivers(tables: dict, golden: dict, cfg: dict) -> tuple[list[Comparison], list[str]]:
    exclude = excluded_manager_keys(cfg)
    lt = _legacy_tables(tables, golden, cfg)
    legacy = waivers_mod.waiver_stints(lt, exclude, legacy_mode=True)
    # the page aggregates were computed from the file's rounded values, in file
    # order (season, manager name, player id), which also breaks ties
    names = {m["id"]: m["name"] for m in cfg.get("managers") or []}
    as_file = legacy.assign(total_z=np.round(legacy["total_z"], 3), avg_z=np.round(legacy["avg_z"], 3),
                            _name=legacy["manager_key"].map(names))
    as_file = as_file.sort_values(["season", "_name", "player_id"], kind="stable").drop(columns="_name")
    board = waivers_mod.waiver_leaderboard(as_file)
    page = golden["waiver_page"]
    checks = [check_stints(legacy, golden["waiver_stints_full"], cfg), check_leaderboard(board, page, cfg),
              check_contested(board, page, cfg), *check_best(as_file, page, cfg)]
    # roster stints: the site file stops at the last 2026 week it was updated for
    rs_json = golden["roster_stints"]
    last26 = max(s["end"] for d in rs_json.values() for v in d.values() for s in v["stints"] if s["season"] == 2026)
    rt = dict(tables)
    for n in ("matchups", "lineups"):
        df = tables[n]
        rt[n] = df[(df["season"] < 2026) | (df["week"] <= last26)]
    from engine.legacy_trades import legacy_positions

    rt, _ = legacy_positions(rt, golden["weekly_rosters_bracket_only"], cfg)
    rs = waivers_mod.roster_stints(rt, exclude)
    first = (rt["lineups"].sort_values(["season", "week"]).drop_duplicates(["manager_key", "player_id"])
             .set_index(["manager_key", "player_id"])["position"])
    rs["position"] = first.reindex(pd.MultiIndex.from_arrays([rs["manager_key"], rs["player_id"]])).to_numpy()
    checks.append(check_roster_stints(rs, rs_json, cfg, tables["lineups"][["player_id", "position"]].drop_duplicates()))
    info = [f"INFO  legacy mode: {len(legacy)} stints, seasons 2020-2025, excluded managers left out"]
    return checks, info + engine_changes(tables, legacy, exclude, cfg)


def engine_changes(tables: dict, legacy: pd.DataFrame, exclude: set[str], cfg: dict) -> list[str]:
    names = {m["id"]: m["name"] for m in cfg.get("managers") or []}
    t = dict(tables)
    t["matchups"] = tables["matchups"][tables["matchups"]["season"] <= 2025]
    t["lineups"] = tables["lineups"][tables["lineups"]["season"] <= 2025]
    k = ["season", "manager_key", "player_id", "start_week"]
    base = waivers_mod.waiver_stints(t, exclude, fixes=set())
    lines = []
    for fix, text in waivers_mod.ENGINE_CHANGES.items():
        e = waivers_mod.waiver_stints(t, exclude, fixes={fix})
        m = base.merge(e, on=k, how="outer", suffixes=("_l", "_e"), indicator=True)
        both = m[m["_merge"] == "both"]
        changed = both[((both["total_z_l"] - both["total_z_e"]).abs() > 1e-9)
                       | (both["weeks_rostered_l"] != both["weeks_rostered_e"])
                       | (both["end_week_l"] != both["end_week_e"]) | (both["type_l"] != both["type_e"])]
        lines.append(f"INFO  engine fix [{fix}] {text}: {len(changed)} stint(s) change, "
                     f"{int((m['_merge'] == 'left_only').sum())} dropped, {int((m['_merge'] == 'right_only').sum())} added")
    eng = waivers_mod.waiver_stints(t, exclude)
    vis = eng[~eng["hidden"]]
    lines.append(f"INFO  all fixes (2020-2025): {len(eng)} stints ({int(eng['hidden'].sum())} hidden, excluded managers); "
                 f"legacy {len(legacy)}")
    lb_l = legacy.groupby("manager_key").agg(tz=("total_z", "sum"), wk=("weeks_rostered", "sum"))
    lb_e = vis.groupby("manager_key").agg(tz=("total_z", "sum"), wk=("weeks_rostered", "sum"))
    j = lb_l.join(lb_e, lsuffix="_l", rsuffix="_e")
    j["z_l"], j["z_e"] = j["tz_l"] / j["wk_l"], j["tz_e"] / j["wk_e"]
    j["rank_l"] = j["z_l"].rank(ascending=False).astype(int)
    j["rank_e"] = j["z_e"].rank(ascending=False).astype(int)
    lines.append("INFO      career z per week (legacy -> engine, rank): " + ", ".join(
        f"{names.get(mk, mk)} {r.z_l:+.3f}->{r.z_e:+.3f} ({int(r.rank_l)}->{int(r.rank_e)})"
        for mk, r in j.sort_values("z_e", ascending=False).iterrows()))
    return lines
