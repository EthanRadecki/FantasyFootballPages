"""Lineup efficiency: lineup-efficiency.html.

Outputs
    data/v1/lineup-efficiency.json   page model (schema "lineup-efficiency"): every counted game's
                                     actual and optimal points, gap, flags and bench depth, keyed
                                     by manager key, with the page's aggregates
    pages/lineup-efficiency.html     the page with its inline data replaced

Inline blocks and their rules (the builders were generate_lineup_efficiency.py,
generate_blunder_rosters.py and lost page steps; recovered from the page and
documented in METRICS_REFERENCE, Lineup Efficiency). A filter is "career" or
one season. "Averaged games" leave out forfeits and neglected lineups
(`lineups.efficiency` column `excluded`):
    EFFICIENCY_BY_FILTER       per manager, mean gap over averaged games (g) and their
                               count (w), gap descending
    EFFICIENCY_GLOBAL_MIN/MAX  the range of g over every filter
    MISSED_WINS_BY_FILTER      per manager: averaged games, losses, missed wins (n), n / losses
                               as a %, regular season and playoff split, rate descending
    BLUNDERS_BY_FILTER         the 10 largest gaps among averaged games
    ROSTERS_BY_FILTER          each blunder's roster in ESPN's order: starters, then bench and IR
    DEPTH_BY_FILTER            per manager, mean bench depth over every counted game
    DEPTH_ADJUSTED_BY_FILTER   raw gap, depth, and gap minus the line through (depth, gap)
                               fitted on that filter's managers (unrounded), adjusted ascending
    SEASON_TREND_DATA          the league's mean gap per season (averaged games)
    DEPTH_VS_WINS_DATA         per manager and season: depth and win % over every counted game
    HEATMAP_MANAGERS/DATA      every counted game as [season, week, manager index, gap, excluded]
    CAREER_AVG_DATA            [manager index, column, mean gap, games] over averaged games
    HEATMAP_GAP_MIN/MAX        0 and the largest gap among averaged games
    HEATMAP_SEASONS            the seasons shown

CAREER_AVG_DATA columns: the page labels columns 15-18 as playoff roles
(round 1, quarterfinal, semifinal, championship), but its data used the raw
week number, so 2020-2021 playoff round 1 (week 14) shares column 14 with
2022-2025 regular-season week 14. Legacy mode reproduces that; the engine
places playoff weeks by role, counted back from the final (pending Ethan's
decision, PR A6b).

Hidden managers are left out of every block (decision 7.3); in the engine
their benches count in the bench average. Coverage: every finished season and the
live season's finished weeks (M1b, decision 7.8); PAGE_SEASONS lists them for the
page's season pills.
"""

from __future__ import annotations

import pandas as pd

from engine.analytics import lineups as lineups_mod
from engine.config import excluded_manager_keys
from engine.legacy import Comparison
from engine.publish.build import Output
from engine.publish.diff import compare_json
from engine.publish.editorial import load_editorial
from engine.publish.legacy_view import (Names, page_roundtrip, page_seasons, read_literal, replace_literal,
                                        with_page_seasons)

SCHEMA, VERSION = "lineup-efficiency", 1
PAGE = "pages/lineup-efficiency.html"
VARS = ["EFFICIENCY_BY_FILTER", "EFFICIENCY_GLOBAL_MIN", "EFFICIENCY_GLOBAL_MAX", "MISSED_WINS_BY_FILTER",
        "BLUNDERS_BY_FILTER", "ROSTERS_BY_FILTER", "DEPTH_BY_FILTER", "DEPTH_ADJUSTED_BY_FILTER", "SEASON_TREND_DATA",
        "DEPTH_VS_WINS_DATA", "HEATMAP_MANAGERS", "HEATMAP_DATA", "HEATMAP_SEASONS", "CAREER_AVG_DATA",
        "HEATMAP_GAP_MIN", "HEATMAP_GAP_MAX"]
OUTCOME = {"W": "Win", "L": "Loss", "T": "Tie"}
BLUNDERS_LISTED = 10


def _r(x, n: int = 2) -> float:
    return round(float(x), n)


def _filters(eff: pd.DataFrame) -> list[tuple[str, pd.DataFrame]]:
    return [("career", eff)] + [(str(int(s)), g) for s, g in eff.groupby("season", sort=True)]


def playoff_columns(eff: pd.DataFrame, by_role: bool) -> pd.Series:
    """CAREER_AVG_DATA column per game: the week number; by_role puts playoff weeks
    after the longest regular season, counted back from the final."""
    if not by_role:
        return eff["week"].astype(int)
    reg_max = int(eff.loc[~eff["is_playoff_week"], "week"].max())
    final = eff.groupby("season")["week"].transform("max")
    rounds = (eff[eff["is_playoff_week"]].groupby("season")["week"].nunique().max())
    rounds = int(rounds) if rounds == rounds else 0
    col = reg_max + rounds - (final - eff["week"])
    return col.where(eff["is_playoff_week"], eff["week"]).astype(int)


def lineup_view(eff: pd.DataFrame, rosters: pd.DataFrame, names, by_role: bool = False, nudge: float = 0.0) -> dict:
    """Every inline block. eff: visible counted games (lineups.efficiency rows);
    rosters: lineup rows (season, week, manager_key, player_name, position, slot,
    started, points) in ESPN's roster order. nudge: added to every gap (the
    Stage A check uses +-1e-9 to tell a rounding tie from a real difference)."""
    # the legacy file's order (season, week, manager name): it fixes the order of float sums and ties
    eff = (eff.assign(_n=eff["manager_key"].map(names)).sort_values(["season", "week", "_n"], kind="stable")
           .drop(columns="_n").reset_index(drop=True))
    eff["efficiency_gap"] = eff["optimal_points"].round(2) - eff["actual_points"].round(2) + nudge
    avg = eff[~eff["excluded"]]
    by_name = lambda keys: sorted(keys, key=names)

    efficiency, missed, blunders, rosters_by, depth, adjusted = {}, {}, {}, {}, {}, {}
    roster_of = {k: g for k, g in rosters.groupby(["season", "week", "manager_key"], sort=False)}
    for label, f in _filters(eff):
        a = f[~f["excluded"]]
        gaps = a.groupby("manager_key")["efficiency_gap"]
        efficiency[label] = sorted(({"m": names(k), "g": _r(v.mean()), "w": int(len(v))} for k, v in gaps),
                                   key=lambda r: -r["g"])
        rows = []
        for k in by_name(f["manager_key"].unique()):
            mine, every = a[a["manager_key"] == k], f[f["manager_key"] == k]
            losses = int((every["result"] == "L").sum())
            n = int(every["missed_win"].sum())
            rows.append({"manager": names(k), "weeks": int(len(mine)), "losses": losses, "n": n,
                         "rate": _r(n / losses * 100, 1) if losses else 0.0,
                         "reg": int(every.loc[~every["is_playoff_week"], "missed_win"].sum()),
                         "po": int(every.loc[every["is_playoff_week"], "missed_win"].sum())})
        missed[label] = sorted(rows, key=lambda r: (-r["rate"], -r["n"], r["manager"]))
        top = a.sort_values("efficiency_gap", ascending=False, kind="stable")
        top = top.head(BLUNDERS_LISTED)
        blunders[label] = [{"season": int(r.season), "week": int(r.week), "manager": names(r.manager_key),
                            "actual": _r(r.actual_points), "optimal": _r(r.optimal_points),
                            "gap": _r(r.efficiency_gap), "outcome": OUTCOME.get(r.result, r.result),
                            "missed": bool(r.missed_win)} for r in top.itertuples()]
        rosters_by[label] = []
        for r in top.itertuples():
            ro = roster_of.get((r.season, r.week, r.manager_key), rosters.iloc[0:0])
            player = lambda p: {"player": p.player_name, "position": p.position, "slot": p.slot,
                                "points": _r(p.points, 1)}
            rosters_by[label].append({"season": int(r.season), "week": int(r.week), "manager": names(r.manager_key),
                                      "starters": [player(p) for p in ro[ro["started"]].itertuples()],
                                      "bench": [player(p) for p in ro[~ro["started"]].itertuples()]})
        dep = f.groupby("manager_key")["bench_depth"].mean()
        depth[label] = sorted(({"m": names(k), "d": _r(v)} for k, v in dep.items()), key=lambda r: -r["d"])
        raw = gaps.mean()
        both = pd.DataFrame({"raw": raw, "depth": dep.reindex(raw.index)})
        both["adj"] = lineups_mod.depth_adjusted(both["raw"], both["depth"])
        adjusted[label] = sorted(({"m": names(k), "raw": _r(r.raw), "depth": _r(r.depth), "adj": _r(r.adj)}
                                  for k, r in both.iterrows()), key=lambda r: r["adj"])

    every_g = [r["g"] for rows in efficiency.values() for r in rows]
    managers = by_name(eff["manager_key"].unique())
    index = {k: i for i, k in enumerate(managers)}
    cols = playoff_columns(avg, by_role)
    career = (avg.assign(col=cols).groupby(["manager_key", "col"])["efficiency_gap"].agg(["mean", "size"])
              .reset_index())
    career = career.assign(idx=career["manager_key"].map(index)).sort_values(["idx", "col"])
    dvw = []
    for (season, k), g in sorted(eff.groupby(["season", "manager_key"]), key=lambda kv: (kv[0][0], names(kv[0][1]))):
        dvw.append({"m": names(k), "s": int(season), "d": _r(g["bench_depth"].mean()),
                    "wr": _r((g["result"] == "W").mean() * 100, 1)})
    return {
        "EFFICIENCY_BY_FILTER": efficiency, "EFFICIENCY_GLOBAL_MIN": min(every_g), "EFFICIENCY_GLOBAL_MAX": max(every_g),
        "MISSED_WINS_BY_FILTER": missed, "BLUNDERS_BY_FILTER": blunders, "ROSTERS_BY_FILTER": rosters_by,
        "DEPTH_BY_FILTER": depth, "DEPTH_ADJUSTED_BY_FILTER": adjusted,
        "SEASON_TREND_DATA": [{"s": int(s), "g": _r(g["efficiency_gap"].mean())} for s, g in avg.groupby("season")],
        "DEPTH_VS_WINS_DATA": dvw,
        "HEATMAP_MANAGERS": [names(k) for k in managers],
        "HEATMAP_DATA": [[int(r.season), int(r.week), index[r.manager_key], _r(r.efficiency_gap, 1), int(r.excluded)]
                         for r in eff.itertuples()],
        "HEATMAP_SEASONS": sorted(int(s) for s in eff["season"].unique()),
        "CAREER_AVG_DATA": [[int(i), int(c), _r(m, 1), int(n)] for i, c, m, n in
                            zip(career["idx"], career["col"], career["mean"], career["size"])],
        "HEATMAP_GAP_MIN": 0, "HEATMAP_GAP_MAX": _r(avg["efficiency_gap"].max()),
    }


# ---------------------------------------------------------------- page model

def lineup_model(eff: pd.DataFrame, rosters: pd.DataFrame, hidden: set[str], seasons: list[int],
                 notes: dict | None = None) -> dict:
    ident = lambda k: k
    vis = eff[~eff["manager_key"].isin(hidden)]
    v = lineup_view(vis, rosters, ident, by_role=True)
    return {
        "seasons": list(seasons),
        "games": [{"season": int(r.season), "week": int(r.week), "manager_key": r.manager_key,
                   "hidden": r.manager_key in hidden, "playoff": bool(r.is_playoff_week), "result": r.result,
                   "points": float(r.points), "opponent_points": float(r.opponent_points),
                   "actual_points": float(r.actual_points), "optimal_points": float(r.optimal_points),
                   "gap": float(r.efficiency_gap), "would_have_won": bool(r.would_have_won),
                   "missed_win": bool(r.missed_win), "forfeited": bool(r.forfeited), "neglected": bool(r.neglected),
                   "bench_depth": float(r.bench_depth)}
                  for r in eff.sort_values(["season", "week", "manager_key"]).itertuples()],
        "efficiency": v["EFFICIENCY_BY_FILTER"], "missed_wins": v["MISSED_WINS_BY_FILTER"],
        "blunders": {k: [dict(b, roster=r) for b, r in zip(v["BLUNDERS_BY_FILTER"][k], v["ROSTERS_BY_FILTER"][k])]
                     for k in v["BLUNDERS_BY_FILTER"]},
        "depth": v["DEPTH_BY_FILTER"], "depth_adjusted": v["DEPTH_ADJUSTED_BY_FILTER"],
        "season_trend": v["SEASON_TREND_DATA"], "depth_vs_wins": v["DEPTH_VS_WINS_DATA"],
        "career_grid": {"managers": v["HEATMAP_MANAGERS"], "cells": v["CAREER_AVG_DATA"]},
        "weekly_grid": {"seasons": v["HEATMAP_SEASONS"], "cells": v["HEATMAP_DATA"]},
        "slots": {str(s): sl for s, sl in sorted(lineups_mod.lineup_slots(rosters).items()) if int(s) in set(seasons)},
        "notes": {k: str(v_) for k, v_ in (notes or {}).items() if k in ("first_round",) and v_},
        "scales": {"gap": [v["EFFICIENCY_GLOBAL_MIN"], v["EFFICIENCY_GLOBAL_MAX"]],
                   "heatmap_gap": [v["HEATMAP_GAP_MIN"], v["HEATMAP_GAP_MAX"]]},
    }


# ---------------------------------------------------------------- Stage A check

def _keyed(v: dict) -> dict:
    """Manager lists keyed by manager (their order is checked by the sort rule;
    the legacy list broke ties in rate in an order no field reproduces)."""
    out = dict(v)
    for var, key in (("EFFICIENCY_BY_FILTER", "m"), ("MISSED_WINS_BY_FILTER", "manager"), ("DEPTH_BY_FILTER", "m"),
                     ("DEPTH_ADJUSTED_BY_FILTER", "m")):
        out[var] = {f: {r[key]: r for r in rows} for f, rows in v[var].items()}
    out["DEPTH_VS_WINS_DATA"] = {f"{r['s']}|{r['m']}": r for r in v["DEPTH_VS_WINS_DATA"]}
    return out


TIE_REASON = "mean at a rounding tie (float noise in the sum; nudging each gap by 1e-9 gives the page's value)"


def _at(doc, path: str):
    for part in [p for p in path.replace("[", "/[").split("/") if p]:
        doc = doc[int(part[1:-1])] if part.startswith("[") else doc[part]
    return doc


def tie_fn(nudged: list[dict]):
    """Excuse a value where a view built from gaps nudged by +-1e-9 has the page's value."""
    def known(path, eng, leg):
        if not isinstance(eng, float) or not isinstance(leg, (int, float)) or abs(eng - leg) > 0.1000001:
            return None
        for v in nudged:
            try:
                if abs(_at(v, path) - leg) < 1e-9:
                    return TIE_REASON
            except (KeyError, IndexError, TypeError):
                continue
        return None
    return known


def compare_view(view: dict, gold: dict, nudged: list[dict] | None = None) -> list[Comparison]:
    return compare_json(f"legacy view {PAGE}", _keyed(view), _keyed({k: gold[k] for k in VARS}),
                        known=tie_fn([_keyed(v) for v in nudged or []]))


def legacy_lineups(ctx) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Lineup efficiency on legacy inputs (legacy positions, weeks cut where the site
    files stop), legacy mode, finished seasons, visible managers; and the rosters."""
    def run():
        from engine.publish.pages.games import legacy_records

        adjusted, _ = legacy_records(ctx)
        eff = lineups_mod.efficiency(adjusted, excluded_manager_keys(ctx.cfg), legacy_mode=True)
        return eff, adjusted["lineups"]
    return ctx.memo("legacy_lineups", run)


def _page_names(ctx, text: str | None) -> Names:
    spelled = []
    if text is not None:
        try:
            spelled = read_literal(text, "HEATMAP_MANAGERS")
        except (KeyError, ValueError):
            pass
    return Names(ctx, spelled)


class LineupEfficiencyPublisher:
    name = "lineup-efficiency"

    def _engine(self, ctx):
        eff = ctx.analysis["lineup_efficiency"]
        seasons = page_seasons(ctx, eff["season"].unique())
        return eff[eff["season"].isin(seasons)], seasons

    def outputs(self, ctx) -> list[Output]:
        eff = ctx.analysis.get("lineup_efficiency")
        if eff is None or not len(eff) or "bench_depth" not in eff:
            return []
        eff, seasons = self._engine(ctx)
        hidden = excluded_manager_keys(ctx.cfg)
        lu = ctx.tables["lineups"]
        out = [Output(f"data/v1/{SCHEMA}.json", lineup_model(eff, lu, hidden, seasons, load_editorial(ctx, "lineup_efficiency")), SCHEMA, VERSION)]
        path = ctx.site_root / PAGE
        if ctx.legacy_site and path.is_file():
            text = path.read_text(encoding="utf-8")
            view = lineup_view(eff[~eff["manager_key"].isin(hidden)], lu, _page_names(ctx, text), by_role=True)
            for var in VARS:
                text = replace_literal(text, var, view[var])
            out.append(Output(PAGE, with_page_seasons(text, seasons, ctx.config.get("live_season"))))
        return out

    def verify(self, ctx) -> list:
        eff = ctx.analysis.get("lineup_efficiency")
        if eff is None or not len(eff) or "bench_depth" not in eff:
            return []
        gold = ctx.golden["lineup_efficiency_page"]
        leg, lu = legacy_lineups(ctx)
        seasons = [int(s) for s in gold["HEATMAP_SEASONS"]]
        leg = leg[leg["season"].isin(seasons) & ~leg["manager_key"].isin(excluded_manager_keys(ctx.cfg))]
        names = Names(ctx, gold["HEATMAP_MANAGERS"])
        view = lineup_view(leg, lu, names, by_role=False)
        path = ctx.site_root / PAGE
        if path.is_file():
            view = page_roundtrip(path.read_text(encoding="utf-8"), {k: view[k] for k in VARS})
        nudged = [lineup_view(leg, lu, names, by_role=False, nudge=e) for e in (1e-9, -1e-9)]
        return compare_view(view, gold, nudged) + self.info(ctx)

    def info(self, ctx) -> list[str]:
        path = ctx.site_root / PAGE
        if not path.is_file():
            return []
        text = path.read_text(encoding="utf-8")
        live = {v: read_literal(text, v) for v in ("EFFICIENCY_BY_FILTER", "DEPTH_BY_FILTER")}
        eff, _ = self._engine(ctx)
        eng = lineup_view(eff[~eff["manager_key"].isin(excluded_manager_keys(ctx.cfg))], ctx.tables["lineups"],
                          _page_names(ctx, text), by_role=True)
        g = lambda v: {r["m"]: r["g"] for r in v["EFFICIENCY_BY_FILTER"]["career"]}
        d = lambda v: {r["m"]: r["d"] for r in v["DEPTH_BY_FILTER"]["career"]}
        moved_g = sum(1 for m, x in g(live).items() if abs(g(eng).get(m, x) - x) > 0.005)
        moved_d = sum(1 for m, x in d(live).items() if abs(d(eng).get(m, x) - x) > 0.005)
        return [f"INFO  lineup-efficiency, engine data vs the live page: career gap changes for {moved_g} manager(s), "
                f"career bench depth for {moved_d} (excluded managers' benches now count in the bench average); "
                "the career grid places playoff weeks by role (columns 15-18)"]
