"""Surplus value: surplus-value.html.

Outputs
    data/v1/surplus-value.json   page model (schema "surplus-value"): career and season grades,
                                 each manager's best and worst pick, the best and worst picks
                                 overall and by season, the color scale
    pages/surplus-value.html     the page with its inline data replaced

Inline blocks and their rules (recovered from the page; the builder was
`surplus_value_index.py` plus a lost page step):
    CAREER_GRADES      draft_career_grades: rank, avg_surplus, total_surplus (the
                       weighted total, 2 places), total_picks, seasons
    SEASON_GRADES      {season: {manager: draft grade}}
    SEASONS            the seasons graded
    HEATMAP_TIPS       {"season|manager": {best, worst}}: that draft's highest and lowest
                       weighted surplus, as "Player RdN (+x.xx)"
    MANAGER_BW         per manager, the career best and worst pick by weighted surplus
    ALL_BEST_PICKS     15 highest weighted surplus; ALL_WORST_PICKS 15 lowest
    SEASON_BEST        10 highest per season; SEASON_WORST 5 lowest per season
                       (rows: player, pos, round, overall pick, season, actual = PRV,
                       expected = expected PRV, surplus = weighted surplus, 2 places)
    POP_SURPLUS_MIN/MAX  the lowest and highest unweighted surplus of any pick, 2 places

Hidden managers are left out of the grades, tips, highs and lows and the
color scale (decision 7.3); their picks stay in the best and worst pick lists
(real picks). Coverage: finished seasons, as the page shows today (decision
7.8, Stage A).
"""

from __future__ import annotations

import pandas as pd

from engine.config import excluded_manager_keys
from engine.legacy import Comparison
from engine.publish.build import Output
from engine.publish.diff import compare_json
from engine.publish.legacy_view import Names, page_roundtrip, read_literal, replace_literal
from engine.publish.pages.draft_common import legacy_draft

SCHEMA, VERSION = "surplus-value", 1
PAGE = "pages/surplus-value.html"
VARS = ["CAREER_GRADES", "SEASON_GRADES", "SEASONS", "HEATMAP_TIPS", "MANAGER_BW", "ALL_BEST_PICKS", "SEASON_BEST",
        "ALL_WORST_PICKS", "SEASON_WORST", "POP_SURPLUS_MIN", "POP_SURPLUS_MAX"]
TOP_ALL, TOP_SEASON_BEST, TOP_SEASON_WORST = 15, 10, 5


def _r2(x) -> float:
    return round(float(x), 2)


def picks_frame(sur: pd.DataFrame, seasons: list[int]) -> pd.DataFrame:
    """Every pick of the graded seasons, in draft order."""
    s = sur[sur["season"].isin(seasons)]
    return s.sort_values(["season", "overall_pick"], kind="stable").reset_index(drop=True)


def _pick(r, rank: int, name) -> dict:
    return {"rank": rank, "player": r.player_name, "pos": r.position, "round": int(r.round),
            "pick": int(r.overall_pick), "season": int(r.season), "actual": _r2(r.actual_prv),
            "expected": _r2(r.expected_prv), "surplus": _r2(r.surplus_wtd), "manager": name(r.manager_key)}


def top_picks(p: pd.DataFrame, n: int, best: bool, name) -> list[dict]:
    d = p.sort_values("surplus_wtd", ascending=not best, kind="stable").head(n)
    return [_pick(r, i + 1, name) for i, r in enumerate(d.itertuples())]


def _extremes(g: pd.DataFrame):
    return g.loc[g["surplus_wtd"].idxmax()], g.loc[g["surplus_wtd"].idxmin()]


def surplus_view(p: pd.DataFrame, career: pd.DataFrame, season: pd.DataFrame, seasons: list[int], names,
                 hidden: set[str] = frozenset()) -> dict:
    """Every inline block of the page. p: picks_frame; career, season: the grade tables (visible rows)."""
    vis = p[~p["manager_key"].isin(hidden)]
    tip = lambda r: f"{r['player_name']} Rd{int(r['round'])} ({float(r['surplus_wtd']):+.2f})"
    tips = {}
    for (s, k), g in sorted(vis.groupby(["season", "manager_key"]), key=lambda kv: (kv[0][0], names(kv[0][1]))):
        b, w = _extremes(g)
        tips[f"{int(s)}|{names(k)}"] = {"best": tip(b), "worst": tip(w)}
    bw = []
    for k, g in sorted(vis.groupby("manager_key"), key=lambda kv: names(kv[0])):
        b, w = _extremes(g)
        bw.append({"manager": names(k), "best": b["player_name"], "bestPos": b["position"],
                   "bestSeason": int(b["season"]), "bestRd": int(b["round"]), "bestSurplus": _r2(b["surplus_wtd"]),
                   "worst": w["player_name"], "worstPos": w["position"], "worstSeason": int(w["season"]),
                   "worstRd": int(w["round"]), "worstSurplus": _r2(w["surplus_wtd"])})
    c = career.sort_values("rank", kind="stable")
    sg = {}
    for s in seasons:
        g = season[season["season"] == s]
        sg[str(s)] = {names(k): _r2(v) for k, v in sorted(zip(g["manager_key"], g["draft_grade"]),
                                                          key=lambda kv: names(kv[0]))}
    return {
        "CAREER_GRADES": [{"rank": int(r.rank), "manager": names(r.manager_key), "avg_surplus": float(r.avg_surplus),
                           "total_surplus": _r2(r.weighted_total), "total_picks": int(r.total_picks),
                           "seasons": int(r.seasons)} for r in c.itertuples()],
        "SEASON_GRADES": sg, "SEASONS": list(seasons), "HEATMAP_TIPS": tips, "MANAGER_BW": bw,
        "ALL_BEST_PICKS": top_picks(p, TOP_ALL, True, names),
        "SEASON_BEST": {str(int(s)): top_picks(g, TOP_SEASON_BEST, True, names) for s, g in p.groupby("season")},
        "ALL_WORST_PICKS": top_picks(p, TOP_ALL, False, names),
        "SEASON_WORST": {str(int(s)): top_picks(g, TOP_SEASON_WORST, False, names) for s, g in p.groupby("season")},
        "POP_SURPLUS_MIN": _r2(vis["surplus"].min()), "POP_SURPLUS_MAX": _r2(vis["surplus"].max()),
    }


def _grades(a: dict, seasons: list[int], hidden: set[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    c = a["draft_career_grades"]
    c = c[~c["manager_key"].isin(hidden) & c["rank"].notna()]
    s = a["draft_season_grades"]
    s = s[s["season"].isin(seasons) & ~s["manager_key"].isin(hidden)]
    return c, s


def surplus_model(a: dict, seasons: list[int], hidden: set[str]) -> dict:
    ident = lambda k: k
    p = picks_frame(a["draft_surplus"], seasons)
    c, s = _grades(a, seasons, hidden)
    v = surplus_view(p, c, s, seasons, ident, hidden)
    vis = p[~p["manager_key"].isin(hidden)]
    row = lambda x: {"rank": x["rank"], "player_name": x["player"], "position": x["pos"], "round": x["round"],
                     "overall_pick": x["pick"], "season": x["season"], "prv": x["actual"],
                     "expected_prv": x["expected"], "surplus_weighted": x["surplus"], "manager_key": x["manager"],
                     "hidden": x["manager"] in hidden}
    extremes = []
    for k, g in vis.groupby("manager_key"):
        for (s_, kk), gg in [((None, k), g)] + [((int(sv), k), gs) for sv, gs in g.groupby("season")]:
            b, w = _extremes(gg)
            extremes.append({"season": s_, "manager_key": kk,
                             "best": {"player_id": int(b["player_id"]), "player_name": b["player_name"],
                                      "position": b["position"], "season": int(b["season"]), "round": int(b["round"]),
                                      "surplus_weighted": float(b["surplus_wtd"])},
                             "worst": {"player_id": int(w["player_id"]), "player_name": w["player_name"],
                                       "position": w["position"], "season": int(w["season"]), "round": int(w["round"]),
                                       "surplus_weighted": float(w["surplus_wtd"])}})
    return {
        "seasons": list(seasons),
        "career_grades": [{"rank": int(r.rank), "manager_key": r.manager_key, "avg_surplus": float(r.avg_surplus),
                           "weighted_total": float(r.weighted_total), "total_picks": int(r.total_picks),
                           "seasons": int(r.seasons)} for r in c.sort_values("rank").itertuples()],
        "season_grades": [{"season": int(r.season), "manager_key": r.manager_key, "grade": float(r.draft_grade),
                           "rank": None if pd.isna(r.season_rank) else int(r.season_rank),
                           "total_picks": int(r.total_picks)} for r in s.sort_values(["season", "manager_key"]).itertuples()],
        "extremes": extremes,
        "best_picks": [row(x) for x in v["ALL_BEST_PICKS"]], "worst_picks": [row(x) for x in v["ALL_WORST_PICKS"]],
        "season_best": {k: [row(x) for x in xs] for k, xs in v["SEASON_BEST"].items()},
        "season_worst": {k: [row(x) for x in xs] for k, xs in v["SEASON_WORST"].items()},
        "scale": {"min": float(vis["surplus"].min()), "max": float(vis["surplus"].max())} if len(vis) else None,
    }


def _page_names(ctx, text: str | None) -> Names:
    spelled = []
    if text is not None:
        try:
            spelled = [r["manager"] for r in read_literal(text, "CAREER_GRADES")]
        except (KeyError, ValueError):
            pass
    return Names(ctx, spelled)


def _keyed(v: dict) -> dict:
    """Lists keyed by rank or manager so a check reports values, not positions."""
    by = lambda xs, k: {str(x[k]): x for x in xs}
    return {**v, "CAREER_GRADES": by(v["CAREER_GRADES"], "manager"), "MANAGER_BW": by(v["MANAGER_BW"], "manager")}


class SurplusPublisher:
    name = "surplus-value"
    NEEDS = ("draft_surplus", "draft_career_grades", "draft_season_grades")

    def _seasons(self, ctx) -> list[int]:
        done = set(ctx.config["finished_seasons"])
        return sorted(int(s) for s in ctx.analysis["draft_surplus"]["season"].unique() if int(s) in done)

    def outputs(self, ctx) -> list[Output]:
        a = ctx.analysis
        if not all(n in a and len(a[n]) for n in self.NEEDS):
            return []
        seasons, hidden = self._seasons(ctx), excluded_manager_keys(ctx.cfg)
        out = [Output(f"data/v1/{SCHEMA}.json", surplus_model(a, seasons, hidden), SCHEMA, VERSION)]
        path = ctx.site_root / PAGE
        if ctx.legacy_site and path.is_file():
            text = path.read_text(encoding="utf-8")
            c, s = _grades(a, seasons, hidden)
            view = surplus_view(picks_frame(a["draft_surplus"], seasons), c, s, seasons, _page_names(ctx, text),
                                hidden)
            for var in VARS:
                text = replace_literal(text, var, view[var])
            out.append(Output(PAGE, text))
        return out

    def verify(self, ctx) -> list:
        a = ctx.analysis
        if not all(n in a and len(a[n]) for n in self.NEEDS):
            return []
        gold = ctx.golden["surplus_value_page"]
        legacy = legacy_draft(ctx)
        seasons, hidden = [int(s) for s in gold["SEASONS"]], excluded_manager_keys(ctx.cfg)
        names = Names(ctx, [r["manager"] for r in gold["CAREER_GRADES"]])
        c, s = _grades(legacy, seasons, hidden)
        view = surplus_view(picks_frame(legacy["draft_surplus"], seasons), c, s, seasons, names, hidden)
        path = ctx.site_root / PAGE
        if path.is_file():
            view = page_roundtrip(path.read_text(encoding="utf-8"), view)
        checks: list = compare_view(view, gold)
        return checks + self.info(ctx)

    def info(self, ctx) -> list[str]:
        path = ctx.site_root / PAGE
        if not path.is_file():
            return []
        a = ctx.analysis
        text = path.read_text(encoding="utf-8")
        seasons, hidden = self._seasons(ctx), excluded_manager_keys(ctx.cfg)
        c, s = _grades(a, seasons, hidden)
        eng = surplus_view(picks_frame(a["draft_surplus"], seasons), c, s, seasons, _page_names(ctx, text), hidden)
        live = {v: read_literal(text, v) for v in VARS}
        rank = lambda v: {r["manager"]: r["rank"] for r in v["CAREER_GRADES"]}
        moved = sorted((m, r, rank(eng).get(m)) for m, r in rank(live).items() if rank(eng).get(m) != r)
        top = lambda v: [(x["player"], x["season"]) for x in v["ALL_BEST_PICKS"]]
        return [f"INFO  surplus-value, engine data vs the live page: career rank changes "
                + (", ".join(f"{m} {a_} -> {b}" for m, a_, b in moved) or "none")
                + f"; {len(set(top(eng)) - set(top(live)))} new pick(s) in the all-time best 15; "
                f"scale {live['POP_SURPLUS_MIN']}..{live['POP_SURPLUS_MAX']} -> "
                f"{eng['POP_SURPLUS_MIN']}..{eng['POP_SURPLUS_MAX']}"]


def compare_view(view: dict, gold: dict) -> list[Comparison]:
    return compare_json(f"legacy view {PAGE}", _keyed(view), _keyed(gold))
