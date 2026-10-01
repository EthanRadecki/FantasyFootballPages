"""Playoff odds: the odds chart on weekly-rankings.html.

Outputs
    data/v1/playoff-odds.json        page model (schema "playoff-odds"), visible managers
    data/rankings/playoff_odds.json  legacy view (weekly-rankings.html today)

The odds themselves are checked by `engine analyze --verify` (the seeded
simulation reproduces every legacy week). The Stage A check here rebuilds
the site file from its golden through the view builder, which proves the
reshaping without running the simulation a second time.
"""

from __future__ import annotations

import pandas as pd

from engine.config import excluded_manager_keys
from engine.legacy import name_to_key
from engine.publish.build import Output
from engine.publish.diff import compare_json
from engine.publish.legacy_view import Names, site_json

SCHEMA, VERSION = "playoff-odds", 1
LIVE = "data/rankings/playoff_odds.json"


def odds_view(odds: pd.DataFrame, regular_weeks: dict[int, int], names) -> dict:
    """{season: {cutoff, max_week (regular-season length), weeks: {week: {manager: odds}}}}."""
    out = {}
    for season, g in odds.sort_values(["season", "week"]).groupby("season", sort=True):
        out[str(int(season))] = {
            "cutoff": int(g["cutoff"].iloc[0]), "max_week": int(regular_weeks[int(season)]),
            "weeks": {str(int(w)): {names(r.manager_key): float(r.odds) for r in wg.itertuples()}
                      for w, wg in g.groupby("week", sort=True)}}
    return out


def odds_model(odds: pd.DataFrame, regular_weeks: dict[int, int], hidden: set[str]) -> dict:
    vis = odds[~odds["manager_key"].isin(hidden)]
    seasons = []
    for season, g in vis.sort_values(["season", "week"]).groupby("season", sort=True):
        seasons.append({
            "season": int(season), "cutoff": int(g["cutoff"].iloc[0]), "regular_season_weeks": int(regular_weeks[int(season)]),
            "weeks": [{"week": int(w), "method": str(wg["method"].iloc[0]),
                       "odds": {r.manager_key: float(r.odds) for r in wg.itertuples()}}
                      for w, wg in g.groupby("week", sort=True)]})
    return {"seasons": seasons}


def frame_from_file(data: dict, cfg: dict) -> pd.DataFrame:
    lk = name_to_key(cfg)
    return pd.DataFrame([{"season": int(s), "week": int(w), "manager_key": lk[n.strip().lower()], "odds": v,
                          "cutoff": d["cutoff"]} for s, d in data.items() for w, o in d["weeks"].items()
                         for n, v in o.items()])


class OddsPublisher:
    name = "odds"
    pages = {"weekly-rankings": None}

    def _regular(self, ctx) -> dict[int, int]:
        return {s["season"]: s["regular_season_weeks"] for s in ctx.config["seasons"]}

    def outputs(self, ctx) -> list[Output]:
        odds = ctx.analysis.get("playoff_odds")
        if odds is None or not len(odds):
            return []
        live = site_json(ctx, LIVE) or {}
        names = Names(ctx, [n for d in live.values() for o in d.get("weeks", {}).values() for n in o])
        reg = self._regular(ctx)
        return [Output("data/v1/playoff-odds.json", odds_model(odds, reg, excluded_manager_keys(ctx.cfg)), SCHEMA, VERSION),
                Output(LIVE, odds_view(odds, reg, names))]

    def verify(self, ctx) -> list:
        odds = ctx.analysis.get("playoff_odds")
        if odds is None or not len(odds):
            return []
        gold = ctx.golden["playoff_odds"]
        names = Names(ctx, [n for d in gold.values() for o in d["weeks"].values() for n in o])
        reg = {**self._regular(ctx), **{int(s): d["max_week"] for s, d in gold.items()}}
        view = odds_view(frame_from_file(gold, ctx.cfg), reg, names)
        checks: list = compare_json("legacy view data/rankings/playoff_odds.json (rebuilt from its golden)", view, gold,
                                    by_section=False)
        live = site_json(ctx, LIVE)
        if live is not None:
            eng = odds_view(odds, self._regular(ctx), Names(ctx, [n for d in live.values() for o in d["weeks"].values()
                                                                   for n in o]))
            both = [(s, w) for s in live for w in live[s]["weeks"] if s in eng and w in eng[s]["weeks"]]
            moved = sum(1 for s, w in both for n, v in live[s]["weeks"][w].items()
                        if abs(eng[s]["weeks"][w].get(n, v) - v) > 0.05)
            n_vals = sum(len(live[s]["weeks"][w]) for s, w in both)
            checks.append(f"INFO  playoff odds, engine data vs the live file: {len(both)} season-weeks in both, "
                          f"{moved} of {n_vals} odds differ by more than 0.05 (engine fixes: flat week 1, division "
                          f"winners, one seed per week, live week blended with projections)")
        return checks
