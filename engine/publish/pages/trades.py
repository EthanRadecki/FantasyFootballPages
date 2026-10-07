"""Trades: trade-value.html.

Outputs
    data/v1/trade-value.json      page model (schema "trade-value"): every trade side keyed by
                                  manager key, with the page's aggregates
    data/page_data.js             legacy view: LEADERBOARD, QUAD/TG/RG/FIT/NEC scales,
                                  BEST_WORST, TRADES (visible managers)
    data/network_data.js          legacy view: NETWORK_DATA (visible managers)
    data/winpct_data.js           legacy view: WINPCT_DATA (visible managers)
    data/trade_explorer_data.js   legacy view: TRADE_NODES (every manager, decision 7.3)
    data/trade_week_data.js       legacy view: TRADE_WEEK_DATA (every manager)
    data/most_traded_data.js      legacy view: MOST_TRADED (every manager)
    pages/trade-value.html        the page with its inline LEADERBOARD_TOTALS replaced

The first five files come from regenerate_data_files.py (the shipped
page_data.js also carries each trade's week, `wk`, which a later version of
the script added). MOST_TRADED had no script: its rule, recovered from the
file, is one entry per player received in a trade (the trade stints), with
the receiving managers in trade order, sorted by count, at the player's
position as the network uses it. LEADERBOARD_TOTALS is
each manager's summed QUAD.

Coverage: every finished season and the live season's trades so far (M1b, decision 7.8);
PAGE_SEASONS lists them for the page's season pills.
"""

from __future__ import annotations

import json
from typing import Callable

import pandas as pd

from engine.config import excluded_manager_keys
from engine.legacy import Comparison, name_to_key
from engine.publish.build import Output
from engine.publish.diff import compare_json
from engine.publish.editorial import load_editorial
from engine.publish.legacy_view import (Names, js_globals, page_seasons, read_js_globals, replace_literal,
                                        with_page_seasons)
from engine.publish.writer import clean

SCHEMA, VERSION = "trade-value", 1
PAGE = "pages/trade-value.html"
METRICS = {"tg": "trade_grade", "rg": "realized_gains", "fit": "fit_score", "nec": "necessity_per_week", "quad": "QUAD"}


def _r(v, d):
    v = clean(v)
    return None if v is None else round(float(v), d)


# ---------------------------------------------------------------- inputs

def sides_frame(metrics: pd.DataFrame, name_of: Callable, pos_of: Callable, seasons: set[int]) -> pd.DataFrame:
    """Trade sides in the given seasons, with players named and positioned."""
    m = metrics[metrics["season"].isin(seasons)].copy()
    ids = lambda col: [json.loads(v) if isinstance(v, str) else list(v) for v in m[col]]
    m["got_ids"], m["gave_ids"] = ids("got_player_ids"), ids("gave_player_ids")
    m["got"] = [[name_of(p, s) for p in ps] for ps, s in zip(m["got_ids"], m["season"])]
    m["gave"] = [[name_of(p, s) for p in ps] for ps, s in zip(m["gave_ids"], m["season"])]
    m["got_pos"] = [[pos_of(p, s) for p in ps] for ps, s in zip(m["got_ids"], m["season"])]
    m["gave_pos"] = [[pos_of(p, s) for p in ps] for ps, s in zip(m["gave_ids"], m["season"])]
    m["multi"] = m["num_managers_in_group"] > 2
    return m.reset_index(drop=True)


# ---------------------------------------------------------------- legacy views

def _leaderboard(active: pd.DataFrame, names: Names) -> dict:
    def block(df):
        g = df.groupby("manager_key")["QUAD"].agg(["mean", "count"])
        return {names(k): {"quad": round(float(r["mean"]), 3), "n": int(r["count"])} for k, r in g.iterrows()}
    out = {"career": block(active)}
    for s in sorted(active["season"].unique()):
        out[str(int(s))] = block(active[active["season"] == s])
    return out


def _best_worst(active: pd.DataFrame, names: Names) -> dict:
    def block(df):
        out = {}
        for k, g in df.groupby("manager_key"):
            b, w = g.loc[g["QUAD"].idxmax()], g.loc[g["QUAD"].idxmin()]
            out[names(k)] = {"best": {"got": b["got"], "gave": b["gave"], "quad": round(float(b["QUAD"]), 2)},
                             "worst": {"got": w["got"], "gave": w["gave"], "quad": round(float(w["QUAD"]), 2)}}
        return out
    out = {"career": block(active)}
    for s in sorted(active["season"].unique()):
        out[str(int(s))] = block(active[active["season"] == s])
    return out


def page_data(sides: pd.DataFrame, active: pd.DataFrame, names: Names) -> dict:
    scale = lambda col: {"min": round(float(sides[col].min()), 3), "max": round(float(sides[col].max()), 3)}
    return {
        "LEADERBOARD": _leaderboard(active, names), "QUAD_SCALE": scale("QUAD"), "TG_SCALE": scale("trade_grade"),
        "RG_SCALE": scale("realized_gains"), "FIT_SCALE": scale("fit_score"), "NEC_SCALE": scale("necessity_per_week"),
        "BEST_WORST": _best_worst(active, names),
        "TRADES": [{"s": int(r.season), "m": names(r.manager_key), "got": r.got, "gave": r.gave,
                    "tg": round(float(r.trade_grade), 2), "rg": round(float(r.realized_gains), 2),
                    "fit": round(float(r.fit_score), 3), "nec": _r(r.necessity_per_week, 3),
                    "quad": round(float(r.QUAD), 2), "multi": bool(r.multi), "wk": int(r.scoring_period)}
                   for r in active.itertuples()],
    }


def network(active: pd.DataFrame, names: Names) -> dict:
    keys = sorted(active["manager_key"].unique(), key=names)
    nodes = [{"id": names(k), "trades": int((active["manager_key"] == k).sum())} for k in keys]
    groups = {k: set(active.loc[active["manager_key"] == k, "group_id"]) for k in keys}
    edges = []
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            shared = groups[a] & groups[b]
            if not shared:
                continue
            rows = active[active["group_id"].isin(shared)]
            net = float(rows.loc[rows["manager_key"] == a, "QUAD"].mean() - rows.loc[rows["manager_key"] == b, "QUAD"].mean())
            positions: dict[str, int] = {}
            for r in rows.itertuples():
                for p in r.got_pos + r.gave_pos:
                    positions[p] = positions.get(p, 0) + 1
            edges.append({"a": names(a), "b": names(b), "n": len(shared), "netDiff": round(net, 3),
                          "positions": positions, "seasons": sorted(int(s) for s in rows["season"].unique())})
    return {"nodes": nodes, "edges": edges}


def winpct(active: pd.DataFrame, results: pd.DataFrame, names: Names) -> list[dict]:
    """Win % over counted games (results: manager_key, result) for managers with a trade."""
    out = []
    for k, g in active.groupby("manager_key"):
        r = results[results["manager_key"] == k]["result"]
        if not len(r):
            continue
        out.append({"m": names(k), "winPct": round(float((r == "W").mean() * 100), 1), "games": int(len(r)),
                    "trades": int(len(g)), "avgQuad": round(float(g["QUAD"].mean()), 3)})
    return sorted(out, key=lambda x: -x["winPct"])


def explorer(sides: pd.DataFrame, names: Names) -> list[dict]:
    nodes = []
    for gid, g in sides.groupby("group_id", sort=True):
        first = g.iloc[0]
        nodes.append({
            "gid": int(gid), "season": int(first["season"]), "sp": int(first["scoring_period"]),
            "multi": bool(first["multi"]),
            "managers": [{"m": names(r.manager_key), "got": r.got, "gave": r.gave, "tg": round(float(r.trade_grade), 2),
                          "rg": round(float(r.realized_gains), 2), "fit": round(float(r.fit_score), 3),
                          "nec": _r(r.necessity_per_week, 3), "quad": round(float(r.QUAD), 2)} for r in g.itertuples()],
            "positions": sorted({p for ps in list(g["got_pos"]) + list(g["gave_pos"]) for p in ps}),
        })
    return nodes


def trade_week(sides: pd.DataFrame, names: Names) -> list[dict]:
    return [{"g": int(r.group_id), "s": int(r.season), "wk": int(r.scoring_period), "m": names(r.manager_key),
             "multi": bool(r.multi), "got": r.got, "gave": r.gave, "tg": round(float(r.trade_grade), 3),
             "rg": round(float(r.realized_gains), 3), "fit": round(float(r.fit_score), 3),
             "nec": _r(r.necessity_per_week, 3), "quad": round(float(r.QUAD), 3)} for r in sides.itertuples()]


def most_traded(stints: pd.DataFrame, name_of: Callable, pos_of: Callable, names: Names, seasons: set[int]) -> list[dict]:
    """One entry per player received in a trade, receiving managers in trade order, most traded first."""
    st = stints[stints["season"].isin(seasons)]
    out = []
    for pid, g in st.groupby("player_id", sort=False):
        pos = pos_of(pid, int(g["season"].iloc[0]))
        out.append({"player": name_of(pid, int(g["season"].iloc[-1])), "count": int(len(g)),
                    "seasons": sorted({int(s) for s in g["season"]}), "managers": [names(k) for k in g["manager_key"]],
                    "pos": pos})
    return sorted(out, key=lambda x: -x["count"])


def totals(active: pd.DataFrame, names: Names) -> dict:
    block = lambda df: {names(k): round(float(v), 3) for k, v in df.groupby("manager_key")["QUAD"].sum().items()}
    out = {"career": block(active)}
    for s in sorted(active["season"].unique()):
        out[str(int(s))] = block(active[active["season"] == s])
    return out


def legacy_views(sides, stints, results, hidden, names, name_of, pos_of, seasons) -> dict:
    active = sides[~sides["manager_key"].isin(hidden)]
    return {"page_data": page_data(sides, active, names), "network": network(active, names),
            "winpct": winpct(active, results, names), "explorer": explorer(sides, names),
            "trade_week": trade_week(sides, names), "most_traded": most_traded(stints, name_of, pos_of, names, seasons),
            "totals": totals(active, names)}


# ---------------------------------------------------------------- page model

def model(sides: pd.DataFrame, stints: pd.DataFrame, results: pd.DataFrame, hidden: set[str], name_of, pos_of,
          seasons: set[int], notes: dict | None = None) -> dict:
    ident = _Ident()                        # the model keys everything by manager key
    active = sides[~sides["manager_key"].isin(hidden)]
    return {
        "seasons": sorted(seasons),
        "sides": [{"group_id": int(r.group_id), "season": int(r.season), "week": int(r.scoring_period),
                   "manager_key": r.manager_key, "multi": bool(r.multi), "hidden": r.manager_key in hidden,
                   "got": [{"player_id": int(p), "name": n, "position": q} for p, n, q in zip(r.got_ids, r.got, r.got_pos)],
                   "gave": [{"player_id": int(p), "name": n, "position": q} for p, n, q in zip(r.gave_ids, r.gave, r.gave_pos)],
                   "trade_grade": float(r.trade_grade), "realized_gains": float(r.realized_gains),
                   "fit_score": float(r.fit_score), "necessity_per_week": clean(r.necessity_per_week),
                   "quad": float(r.QUAD)} for r in sides.itertuples()],
        "leaderboard": _leaderboard(active, ident), "totals": totals(active, ident),
        "network": network(active, ident), "win_pct": winpct(active, results, ident),
        "most_traded": most_traded(stints, name_of, pos_of, ident, seasons),
        "scales": {k: {"min": float(sides[c].min()), "max": float(sides[c].max())} for k, c in METRICS.items()},
        "notes": {k: str(v) for k, v in (notes or {}).items() if k in ("trade_week",) and v},
    }


class _Ident:
    """A Names stand-in that leaves manager keys as they are (page models key by manager)."""

    def __call__(self, key):
        return key

    def short(self, key):
        return key


# ---------------------------------------------------------------- engine-mode lookups

def engine_lookups(tables: dict) -> tuple[Callable, Callable]:
    """Player name and position as ESPN listed them that season."""
    ps = tables["player_seasons"].set_index(["season", "player_id"])
    name, pos = ps["player_name"].to_dict(), ps["position"].to_dict()
    latest = tables["player_seasons"].sort_values("season").drop_duplicates("player_id", keep="last").set_index("player_id")
    return (lambda p, s: name.get((s, p)) or latest["player_name"].get(p, str(p)),
            lambda p, s: pos.get((s, p)) or latest["position"].get(p, "UNK"))


# ---------------------------------------------------------------- Stage A checks

def legacy_trades(ctx) -> dict:
    """The trades analysis on legacy inputs, as `analyze --verify` runs it."""
    def run():
        from engine.analytics import trades as trades_mod
        from engine.legacy_trades import legacy_positions

        seasons = sorted(ctx.golden["metrics_final"]["season"].unique().tolist())
        adjusted, _ = legacy_positions(ctx.tables, ctx.golden["weekly_rosters_bracket_only"], ctx.cfg)
        return trades_mod.analyze_trades(adjusted, seasons=seasons, legacy_mode=True)
    return ctx.memo("legacy_trades", run)


def legacy_inputs(ctx):
    """Legacy-mode sides and stints renumbered with the legacy group ids, in
    the legacy file order, with the legacy inputs' player names (the trade
    universe), positions (first row in the legacy rosters file) and results
    (lineup_efficiency.csv)."""
    from engine.legacy_trades import _group_map

    g = ctx.golden
    run = legacy_trades(ctx)
    gmap = _group_map(run, g["trade_universe"]).set_index("group_id")["legacy_group_id"]
    lookup = name_to_key(ctx.cfg)
    order = {(int(r.group_id), lookup[r.manager.strip().lower()]): i for i, r in enumerate(g["metrics_final"].itertuples())}
    metrics = run["trade_metrics"].assign(group_id=lambda d: d["group_id"].map(gmap).astype(int))
    metrics = metrics.assign(_o=[order.get((gid, k), 10 ** 6) for gid, k in zip(metrics["group_id"], metrics["manager_key"])])
    metrics = metrics.sort_values("_o", kind="stable").drop(columns="_o")
    stints = run["trade_stints"].assign(group_id=lambda d: d["group_id"].map(gmap).astype(int))
    st_order = {(int(r.group_id), lookup[r.receiving_manager.strip().lower()], int(r.player_id)): i
                for i, r in enumerate(g["player_stints_fixed"].itertuples())}
    stints = stints.assign(_o=[st_order.get((a, b, c), 10 ** 6) for a, b, c in
                               zip(stints["group_id"], stints["manager_key"], stints["player_id"])])
    stints = stints.sort_values("_o", kind="stable").drop(columns="_o")

    names: dict[int, str] = {}
    for r in g["trade_universe"].itertuples():
        for ids, nm in ((r.got_player_ids, r.got_players), (r.gave_player_ids, r.gave_players)):
            names.update(dict(zip(json.loads(ids), json.loads(nm))))
    wr = g["weekly_rosters_bracket_only"]
    first_pos = wr.drop_duplicates("Player_ID").set_index("Player_ID")["Position"].to_dict()
    st_pos = g["player_stints_fixed"].dropna(subset=["position"]).drop_duplicates("player_id").set_index("player_id")["position"].to_dict()
    name_of = lambda p, s: names.get(p, str(p))
    pos_of = lambda p, s: first_pos.get(p) or st_pos.get(p) or "UNK"
    le = g["lineup_efficiency"]
    results = pd.DataFrame({"manager_key": [lookup[m.strip().lower()] for m in le["Manager"]],
                            "result": le["Outcome"].map({"Win": "W", "Loss": "L", "Tie": "T"})})
    return metrics, stints, results, name_of, pos_of


def _keyed(rows: list[dict], key: Callable) -> dict:
    return {key(r): r for r in rows}


def _sorted_players(x):
    """Player lists compared without their order (the legacy order came from the trade universe)."""
    if isinstance(x, dict):
        return {k: (sorted(v) if k in ("got", "gave") and isinstance(v, list) else _sorted_players(v)) for k, v in x.items()}
    if isinstance(x, list):
        return [_sorted_players(v) for v in x]
    return x


def compare_views(views: dict, golden: dict) -> list[Comparison]:
    pd_g, pd_v = golden["page_data"], views["page_data"]
    tkey = lambda r: f"{r['s']}|{r['wk']}|{r['m']}|{sorted(r['got'])}|{sorted(r['gave'])}"
    out = compare_json("legacy view data/page_data.js", _sorted_players({**pd_v, "TRADES": _keyed(pd_v["TRADES"], tkey)}),
                       _sorted_players({**pd_g, "TRADES": _keyed(pd_g["TRADES"], tkey)}))
    ekey = lambda r: f"{r['a']}|{r['b']}"
    out += compare_json("legacy view data/network_data.js", {"nodes": _keyed(views["network"]["nodes"], lambda r: r["id"]),
                                                             "edges": _keyed(views["network"]["edges"], ekey)},
                        {"nodes": _keyed(golden["network"]["nodes"], lambda r: r["id"]),
                         "edges": _keyed(golden["network"]["edges"], ekey)})
    out += compare_json("legacy view data/winpct_data.js", _keyed(views["winpct"], lambda r: r["m"]),
                        _keyed(golden["winpct"], lambda r: r["m"]), by_section=False)
    node = lambda n: {**n, "managers": _keyed(n["managers"], lambda m: m["m"])}
    out += compare_json("legacy view data/trade_explorer_data.js",
                        _sorted_players(_keyed([node(n) for n in views["explorer"]], lambda n: n["gid"])),
                        _sorted_players(_keyed([node(n) for n in golden["explorer"]], lambda n: n["gid"])), by_section=False)
    out += compare_json("legacy view data/trade_week_data.js",
                        _sorted_players(_keyed(views["trade_week"], lambda r: f"{r['g']}|{r['m']}")),
                        _sorted_players(_keyed(golden["trade_week"], lambda r: f"{r['g']}|{r['m']}")), by_section=False)
    out += compare_json("legacy view data/most_traded_data.js", _keyed(views["most_traded"], lambda r: r["player"]),
                        _keyed(golden["most_traded"], lambda r: r["player"]), by_section=False)
    out += compare_json("legacy view trade-value.html LEADERBOARD_TOTALS", views["totals"], golden["totals"],
                        by_section=False)
    return out


class TradesPublisher:
    name = "trades"
    NEEDS = ("trade_metrics", "trade_stints", "lineup_efficiency")

    def _engine(self, ctx):
        a = ctx.analysis
        seasons = set(page_seasons(ctx, a["trade_metrics"]["season"].unique()))
        name_of, pos_of = engine_lookups(ctx.tables)
        sides = sides_frame(a["trade_metrics"].sort_values(["group_id"], kind="stable"), name_of, pos_of, seasons)
        le = a["lineup_efficiency"]
        results = le[le["season"].isin(seasons)][["manager_key", "result"]]
        stints = a["trade_stints"].sort_values(["group_id"], kind="stable")
        return sides, stints, results, name_of, pos_of, seasons

    def outputs(self, ctx) -> list[Output]:
        if not all(n in ctx.analysis for n in self.NEEDS):
            return []
        sides, stints, results, name_of, pos_of, seasons = self._engine(ctx)
        hidden = excluded_manager_keys(ctx.cfg)
        page = (ctx.site_root / PAGE).read_text(encoding="utf-8")
        old = read_js_globals((ctx.site_root / "data/page_data.js").read_text(encoding="utf-8"))
        names = Names(ctx, list(old.get("LEADERBOARD", {}).get("career", {})))
        v = legacy_views(sides, stints, results, hidden, names, name_of, pos_of, seasons)
        return [
            Output("data/v1/trade-value.json", model(sides, stints, results, hidden, name_of, pos_of, seasons,
                                                    load_editorial(ctx, "trade_value")), SCHEMA, VERSION),
            Output("data/page_data.js", js_globals(v["page_data"])),
            Output("data/network_data.js", js_globals({"NETWORK_DATA": v["network"]})),
            Output("data/winpct_data.js", js_globals({"WINPCT_DATA": v["winpct"]})),
            Output("data/trade_explorer_data.js", js_globals({"TRADE_NODES": v["explorer"]})),
            Output("data/trade_week_data.js", js_globals({"TRADE_WEEK_DATA": v["trade_week"]})),
            Output("data/most_traded_data.js", js_globals({"MOST_TRADED": v["most_traded"]})),
            Output(PAGE, with_page_seasons(replace_literal(page, "LEADERBOARD_TOTALS", v["totals"]), sorted(seasons),
                                          ctx.config.get("live_season"))),
        ]

    def verify(self, ctx) -> list:
        if not all(n in ctx.analysis for n in self.NEEDS):
            return []
        g = ctx.golden
        metrics, stints, results, name_of, pos_of = legacy_inputs(ctx)
        seasons = set(int(s) for s in g["metrics_final"]["season"].unique())
        sides = sides_frame(metrics, name_of, pos_of, seasons)
        names = Names(ctx, list(g["page_data"]["LEADERBOARD"]["career"]) + [n["id"] for n in g["network_data"]["nodes"]]
                      + [m["m"] for n in g["trade_explorer_data"] for m in n["managers"]])
        views = legacy_views(sides, stints, results, excluded_manager_keys(ctx.cfg), names, name_of, pos_of, seasons)
        golden = {"page_data": g["page_data"], "network": g["network_data"], "winpct": g["winpct_data"],
                  "explorer": g["trade_explorer_data"], "trade_week": g["trade_week_data"],
                  "most_traded": g["most_traded_data"], "totals": g["trade_value_inline"]["LEADERBOARD_TOTALS"]}
        return compare_views(views, golden) + self.info(ctx)

    def info(self, ctx) -> list[str]:
        """What the live trade-value page changes to at M1 (engine data vs the live files)."""
        sides, stints, results, name_of, pos_of, seasons = self._engine(ctx)
        hidden = excluded_manager_keys(ctx.cfg)
        old = read_js_globals((ctx.site_root / "data/page_data.js").read_text(encoding="utf-8"))
        names = Names(ctx, list(old.get("LEADERBOARD", {}).get("career", {})))
        v = legacy_views(sides, stints, results, hidden, names, name_of, pos_of, seasons)
        live_trades = old.get("TRADES", [])
        live_q = {}
        for r in live_trades:
            live_q.setdefault(r["m"], []).append(r["quad"])
        lines = [f"INFO  trade-value, engine data vs the live files: {len(v['explorer'])} trades "
                 f"({len(v['page_data']['TRADES'])} visible sides, live {len(live_trades)}), "
                 f"{len(v['most_traded'])} players in most traded"]
        career = v["page_data"]["LEADERBOARD"]["career"]
        live_career = old.get("LEADERBOARD", {}).get("career", {})
        moved = sorted(((m, live_career[m]["quad"], career[m]["quad"]) for m in career if m in live_career),
                       key=lambda x: -abs(x[2] - x[1]))
        lines.append("INFO  average QUAD, live -> engine (largest moves): " + ", ".join(
            f"{m} {a:+.3f} -> {b:+.3f}" for m, a, b in moved[:5]))
        return lines
