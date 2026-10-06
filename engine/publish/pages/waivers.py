"""Waiver value: waiver-value.html.

Outputs
    data/v1/waiver-value.json    page model (schema "waiver-value"): every pickup (waiver stint)
                                 keyed by manager key, the leaderboard per season and position,
                                 best pickups, the free agent vs claim split, the color scales
    pages/waiver-value.html      the page with its inline data replaced

Inline blocks and their rules (the builder was lost; recovered from the page,
which equals the analyze goldens `waivers/waiver_page.json` and
`waiver_stints_full.csv`):
    WAIVER_STINTS          every pickup in file order (season, manager name, player id):
                           s, m, t (F or W), sw (start week), wk (weeks), z (total z, 3 places),
                           ppw (2 places), p, pos
    LEADERBOARD_FULL       {scope: {position: [{m, ppw, z, n}]}} per manager, z per week
                           descending; scope is "career" or a season, position "ALL" or one
    POSITION_SCALE         per position, the lowest and highest ppw and z on any leaderboard
                           list of that position (every scope)
    BEST_BY_MANAGER        {scope: {position: {manager: {p, tz, wk}}}}: the manager's best
                           pickup by total z
    BEST_PICKUPS_BY_FILTER {scope: {position: [...]}}: the 12 best pickups by total z (positive,
                           held 3+ weeks), `waivers.best_pickups`
    CONTESTED_SPLIT        per manager, free agent adds vs waiver claims vs career, career z
                           descending
    WAIVER_Z_GLOBAL_MIN/MAX  lowest and highest pickup total z
    UPSIDE_MIN/MAX         0, and the highest sum of positive pickup z of any manager in any
                           scope and position (2 places)
    BEST_TOTALZ_MIN/MAX, BEST_AVGZ_MIN/MAX  the range of total and average z on the best lists

The page's aggregates were computed from the file's rounded values in file
order (which also breaks ties); the legacy check does the same. The engine
view aggregates unrounded values. Hidden managers are left out of every block
(decision 7.3: leaderboards, the per-manager charts WAIVER_STINTS feeds);
their pickups still count in the position baselines. POSITION_KEYS is
template and stays. Coverage: finished seasons, as the page shows today
(decision 7.8, Stage A).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from engine.analytics import waivers as waivers_mod
from engine.config import excluded_manager_keys
from engine.legacy import Comparison
from engine.publish.build import Output
from engine.publish.diff import compare_json
from engine.publish.legacy_view import Names, page_roundtrip, read_literal, replace_literal

SCHEMA, VERSION = "waiver-value", 1
PAGE = "pages/waiver-value.html"
VARS = ["LEADERBOARD_FULL", "POSITION_SCALE", "BEST_BY_MANAGER", "WAIVER_Z_GLOBAL_MIN", "WAIVER_Z_GLOBAL_MAX",
        "WAIVER_STINTS", "CONTESTED_SPLIT", "UPSIDE_MIN", "UPSIDE_MAX", "BEST_PICKUPS_BY_FILTER", "BEST_TOTALZ_MIN",
        "BEST_TOTALZ_MAX", "BEST_AVGZ_MIN", "BEST_AVGZ_MAX"]
TYPE_CODE = {"FREEAGENT": "F", "WAIVER": "W"}


def _r(x, n: int) -> float:
    return round(float(x), n)


def season_names(stints: pd.DataFrame, player_seasons: pd.DataFrame) -> pd.DataFrame:
    """Each pickup's player named as ESPN listed him that season (the stint table
    carries his current name: "Commanders D/ST" for a 2020 "Washington D/ST")."""
    ps = player_seasons.drop_duplicates(["season", "player_id"]).set_index(["season", "player_id"])["player_name"]
    idx = pd.MultiIndex.from_arrays([stints["season"].astype(int), stints["player_id"].astype(int)])
    named = pd.Series(ps.reindex(idx).to_numpy(), index=stints.index)
    return stints.assign(player_name=named.fillna(stints["player_name"]))


def file_order(stints: pd.DataFrame, names) -> pd.DataFrame:
    """Pickups in the legacy file's order: season, manager name, player id."""
    return (stints.assign(_n=stints["manager_key"].map(names))
            .sort_values(["season", "_n", "player_id"], kind="stable").drop(columns="_n").reset_index(drop=True))


def _scopes(stints: pd.DataFrame) -> list[str]:
    return ["career"] + [str(int(s)) for s in sorted(stints["season"].unique())]


def waiver_view(stints: pd.DataFrame, names) -> dict:
    """Every inline block from visible pickups in file order (file_order)."""
    board = waivers_mod.waiver_leaderboard(stints)
    lb: dict = {}
    for scope in _scopes(stints):
        b = board[(board["scope"] == scope) & (board["type"] == "ALL")]
        lb[scope] = {}
        for pos in ["ALL"] + sorted(p for p in b["position"].unique() if p != "ALL"):
            g = b[b["position"] == pos].sort_values("z_per_week", ascending=False, kind="stable")
            lb[scope][pos] = [{"m": names(r.manager_key), "ppw": float(np.round(r.ppw, 2)),
                               "z": float(np.round(r.z_per_week, 3)), "n": int(r.pickups)} for r in g.itertuples()]
    scale = {}
    for pos in sorted({p for sc in lb.values() for p in sc}):
        rows = [r for sc in lb.values() for r in sc.get(pos, [])]
        scale[pos] = {"ppwMin": min(r["ppw"] for r in rows), "ppwMax": max(r["ppw"] for r in rows),
                      "zMin": min(r["z"] for r in rows), "zMax": max(r["z"] for r in rows)}

    best_by: dict = {}
    for scope in _scopes(stints):
        s = stints if scope == "career" else stints[stints["season"].astype(str) == scope]
        best_by[scope] = {}
        for pos in ["ALL"] + sorted(s["position"].unique()):
            d = s if pos == "ALL" else s[s["position"] == pos]
            top = d.sort_values("total_z", ascending=False, kind="stable").drop_duplicates("manager_key")
            best_by[scope][pos] = {names(r.manager_key): {"p": r.player_name, "tz": _r(r.total_z, 2),
                                                          "wk": int(r.weeks_rostered)}
                                   for r in sorted(top.itertuples(), key=lambda r: names(r.manager_key))}

    best = waivers_mod.best_pickups(stints)
    best_lists: dict = {}
    for r in best.itertuples():
        best_lists.setdefault(r.scope, {}).setdefault(r.list_position, []).append(
            {"s": int(r.season), "m": names(r.manager_key), "p": r.player_name, "pos": r.position,
             "wk": int(r.weeks_rostered), "ppw": _r(r.ppw, 2), "totalz": _r(r.total_z, 3), "avgz": _r(r.avg_z, 3),
             "type": r.type})

    career = board[(board["scope"] == "career") & (board["position"] == "ALL")].set_index(["manager_key", "type"])
    split = []
    for k in career.xs("ALL", level="type").index:
        get = lambda t, col, d: (float(np.round(career.loc[(k, t), col], d)) if d else int(career.loc[(k, t), col])) \
            if (k, t) in career.index else None
        split.append({"m": names(k), "faPpw": get("FREEAGENT", "ppw", 2), "faZ": get("FREEAGENT", "z_per_week", 3),
                      "faN": get("FREEAGENT", "pickups", 0), "wvPpw": get("WAIVER", "ppw", 2),
                      "wvZ": get("WAIVER", "z_per_week", 3), "wvN": get("WAIVER", "pickups", 0),
                      "careerPpw": get("ALL", "ppw", 2), "careerZ": get("ALL", "z_per_week", 3)})
    split.sort(key=lambda r: -r["careerZ"])

    rows = [{"s": int(r.season), "m": names(r.manager_key), "t": TYPE_CODE.get(r.type, r.type[:1]),
             "sw": int(r.start_week), "wk": int(r.weeks_rostered), "z": _r(r.total_z, 3), "ppw": _r(r.ppw, 2),
             "p": r.player_name, "pos": r.position} for r in stints.itertuples()]
    upside = 0.0
    st = pd.DataFrame(rows)
    for scope in _scopes(stints):
        s = st if scope == "career" else st[st["s"].astype(str) == scope]
        for pos in ["ALL"] + sorted(s["pos"].unique()):
            p = s if pos == "ALL" else s[s["pos"] == pos]
            v = p[p["z"] > 0].groupby("m")["z"].sum()
            if len(v):
                upside = max(upside, float(v.max()))
    flat = [x for sc in best_lists.values() for xs in sc.values() for x in xs]
    return {
        "LEADERBOARD_FULL": lb, "POSITION_SCALE": scale, "BEST_BY_MANAGER": best_by,
        "WAIVER_Z_GLOBAL_MIN": float(st["z"].min()), "WAIVER_Z_GLOBAL_MAX": float(st["z"].max()),
        "WAIVER_STINTS": rows, "CONTESTED_SPLIT": split, "UPSIDE_MIN": 0.0, "UPSIDE_MAX": _r(upside, 2),
        "BEST_PICKUPS_BY_FILTER": best_lists,
        "BEST_TOTALZ_MIN": min(x["totalz"] for x in flat), "BEST_TOTALZ_MAX": max(x["totalz"] for x in flat),
        "BEST_AVGZ_MIN": min(x["avgz"] for x in flat), "BEST_AVGZ_MAX": max(x["avgz"] for x in flat),
    }


# ---------------------------------------------------------------- page model

def waiver_model(stints: pd.DataFrame, seasons: list[int], hidden: set[str]) -> dict:
    ident = lambda k: k
    vis = stints[~stints["manager_key"].isin(hidden)]
    v = waiver_view(file_order(vis, ident), ident)
    return {
        "seasons": list(seasons),
        "pickups": [{"season": int(r.season), "manager_key": r.manager_key, "hidden": bool(r.manager_key in hidden),
                     "player_id": int(r.player_id), "player_name": r.player_name, "position": r.position,
                     "type": r.type, "start_week": int(r.start_week), "end_week": None if pd.isna(r.end_week)
                     else int(r.end_week), "weeks": int(r.weeks_rostered), "points": float(r.total_points),
                     "ppw": float(r.ppw), "avg_z": float(r.avg_z), "total_z": float(r.total_z)}
                    for r in stints.sort_values(["season", "manager_key", "start_week", "player_id"]).itertuples()],
        "leaderboard": {sc: {pos: [{"manager_key": r["m"], "ppw": r["ppw"], "z_per_week": r["z"], "pickups": r["n"]}
                                   for r in rows] for pos, rows in d.items()} for sc, d in v["LEADERBOARD_FULL"].items()},
        "best_by_manager": {sc: {pos: {k: {"player_name": r["p"], "total_z": r["tz"], "weeks": r["wk"]}
                                       for k, r in d2.items()} for pos, d2 in d.items()}
                            for sc, d in v["BEST_BY_MANAGER"].items()},
        "best_pickups": {sc: {pos: [{"season": r["s"], "manager_key": r["m"], "player_name": r["p"],
                                     "position": r["pos"], "weeks": r["wk"], "ppw": r["ppw"], "total_z": r["totalz"],
                                     "avg_z": r["avgz"], "type": r["type"]} for r in rows] for pos, rows in d.items()}
                         for sc, d in v["BEST_PICKUPS_BY_FILTER"].items()},
        "free_agent_vs_claim": [{"manager_key": r["m"], "free_agent": {"ppw": r["faPpw"], "z_per_week": r["faZ"],
                                                                       "pickups": r["faN"]},
                                 "waiver": {"ppw": r["wvPpw"], "z_per_week": r["wvZ"], "pickups": r["wvN"]},
                                 "career": {"ppw": r["careerPpw"], "z_per_week": r["careerZ"]}}
                                for r in v["CONTESTED_SPLIT"]],
        "scales": {"position": v["POSITION_SCALE"],
                   "pickup_z": [v["WAIVER_Z_GLOBAL_MIN"], v["WAIVER_Z_GLOBAL_MAX"]],
                   "upside": [v["UPSIDE_MIN"], v["UPSIDE_MAX"]],
                   "best_total_z": [v["BEST_TOTALZ_MIN"], v["BEST_TOTALZ_MAX"]],
                   "best_avg_z": [v["BEST_AVGZ_MIN"], v["BEST_AVGZ_MAX"]]},
    }


# ---------------------------------------------------------------- Stage A check

def _stint_key(r: dict) -> str:
    return f"{r['s']}|{r['m']}|{r['sw']}|{r['wk']}|{r['pos']}|{r['t']}"


def _keyed(v: dict) -> dict:
    """Lists keyed so a check reports values, not positions (pickups by season, manager,
    start week, length, position and type; leaderboards and the split by manager)."""
    out = dict(v)
    stints: dict = {}
    for r in v["WAIVER_STINTS"]:
        k = _stint_key(r)
        while k in stints:            # two pickups alike in every key field: keep both
            k += "+"
        stints[k] = r
    out["WAIVER_STINTS"] = stints
    out["LEADERBOARD_FULL"] = {sc: {p: {r["m"]: r for r in rows} for p, rows in d.items()}
                               for sc, d in v["LEADERBOARD_FULL"].items()}
    out["CONTESTED_SPLIT"] = {r["m"]: r for r in v["CONTESTED_SPLIT"]}
    return out


TIE_REASON = "pickups tied on total z; legacy's unstable sort kept the other order"
NAME_REASON = ("player named differently: the legacy file's name source (e.g. Gabriel Davis, Gardner Minshew II); "
               "the same pickup by every other field, the view uses ESPN's name that season")


def known_fn(view: dict, gold: dict):
    """Excuse a best-pickup place where two pickups tie on total z (as analyze --verify),
    and a player name where the row is the same pickup by every other field."""
    import re

    def same_but_name(a: dict, b: dict) -> bool:
        return isinstance(a, dict) and isinstance(b, dict) and a.get("p") != b.get("p") \
            and {k: x for k, x in a.items() if k != "p"} == {k: x for k, x in b.items() if k != "p"}

    def known(path, eng, leg):
        m = re.match(r"/BEST_PICKUPS_BY_FILTER/([^/]+)/(.+)\[(\d+)\]/(\w+)$", path)
        if m:
            sc, pos, i = m.group(1), m.group(2), int(m.group(3))
            v, g = view["BEST_PICKUPS_BY_FILTER"][sc][pos][i], gold["BEST_PICKUPS_BY_FILTER"][sc][pos][i]
            if m.group(4) == "p" and same_but_name(v, g):
                return NAME_REASON
            return TIE_REASON if v["totalz"] == g["totalz"] and v != g else None
        m = re.match(r"/BEST_BY_MANAGER/([^/]+)/(.+)/([^/]+)/p$", path)
        if m:
            v = view["BEST_BY_MANAGER"][m.group(1)][m.group(2)].get(m.group(3))
            g = gold["BEST_BY_MANAGER"][m.group(1)][m.group(2)].get(m.group(3))
            return NAME_REASON if same_but_name(v, g) else None
        if path.startswith("/WAIVER_STINTS/") and path.endswith("/p"):
            return NAME_REASON          # keyed by every other field, so a name is all that can differ
        return None
    return known


def compare_view(view: dict, gold: dict) -> list[Comparison]:
    return compare_json(f"legacy view {PAGE}", _keyed(view), _keyed({k: gold[k] for k in VARS}),
                        known=known_fn(view, gold))


def legacy_stints(ctx) -> pd.DataFrame:
    """Waiver stints on legacy inputs, as `analyze --verify` builds them, with the
    file's rounding (the page's aggregates were computed from those values)."""
    from engine.legacy_waivers import _legacy_tables

    def run():
        lt = _legacy_tables(ctx.tables, ctx.golden, ctx.cfg)
        st = waivers_mod.waiver_stints(lt, excluded_manager_keys(ctx.cfg), legacy_mode=True)
        st = season_names(st, ctx.tables["player_seasons"])
        return st.assign(total_z=np.round(st["total_z"], 3), avg_z=np.round(st["avg_z"], 3))
    return ctx.memo("legacy_waiver_stints", run)


def _page_names(ctx, text: str | None) -> Names:
    spelled = []
    if text is not None:
        try:
            spelled = [r["m"] for r in read_literal(text, "CONTESTED_SPLIT")]
        except (KeyError, ValueError):
            pass
    return Names(ctx, spelled)


class WaiversPublisher:
    name = "waiver-value"

    def _engine(self, ctx):
        st = season_names(ctx.analysis["waiver_stints"], ctx.tables["player_seasons"])
        seasons = sorted(int(s) for s in st["season"].unique() if int(s) in set(ctx.config["finished_seasons"]))
        return st[st["season"].isin(seasons)], seasons

    def outputs(self, ctx) -> list[Output]:
        st = ctx.analysis.get("waiver_stints")
        if st is None or not len(st):
            return []
        st, seasons = self._engine(ctx)
        hidden = excluded_manager_keys(ctx.cfg)
        out = [Output(f"data/v1/{SCHEMA}.json", waiver_model(st, seasons, hidden), SCHEMA, VERSION)]
        path = ctx.site_root / PAGE
        if ctx.legacy_site and path.is_file():
            text = path.read_text(encoding="utf-8")
            names = _page_names(ctx, text)
            view = waiver_view(file_order(st[~st["manager_key"].isin(hidden)], names), names)
            for var in VARS:
                text = replace_literal(text, var, view[var])
            out.append(Output(PAGE, text))
        return out

    def verify(self, ctx) -> list:
        st = ctx.analysis.get("waiver_stints")
        if st is None or not len(st):
            return []
        gold = ctx.golden["waiver_value_page"]
        names = Names(ctx, [r["m"] for r in gold["CONTESTED_SPLIT"]] + [r["m"] for r in gold["WAIVER_STINTS"]])
        view = waiver_view(file_order(legacy_stints(ctx), names), names)
        path = ctx.site_root / PAGE
        if path.is_file():
            view = page_roundtrip(path.read_text(encoding="utf-8"), {k: view[k] for k in VARS})
        return compare_view(view, gold) + self.info(ctx)

    def info(self, ctx) -> list[str]:
        path = ctx.site_root / PAGE
        if not path.is_file():
            return []
        text = path.read_text(encoding="utf-8")
        live = {v: read_literal(text, v) for v in ("CONTESTED_SPLIT", "WAIVER_STINTS")}
        st, _ = self._engine(ctx)
        names = _page_names(ctx, text)
        eng = waiver_view(file_order(st[~st["manager_key"].isin(excluded_manager_keys(ctx.cfg))], names), names)
        rank = lambda rows: {r["m"]: i + 1 for i, r in enumerate(rows)}
        lr, er = rank(live["CONTESTED_SPLIT"]), rank(eng["CONTESTED_SPLIT"])
        moved = [f"{m} {lr[m]} -> {er[m]}" for m in sorted(lr, key=lr.get) if m in er and er[m] != lr[m]]
        return [f"INFO  waiver-value, engine data vs the live page: {len(eng['WAIVER_STINTS'])} pickups "
                f"(live {len(live['WAIVER_STINTS'])}); career z per week rank changes: "
                + (", ".join(moved[:8]) or "none") + " (engine fixes: IR weeks, double-counted weeks, re-add type)"]
