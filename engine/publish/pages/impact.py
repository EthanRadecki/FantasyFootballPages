"""Position impact: position-impact.html and dst-impact.html (Life Without Defense).

Outputs
    data/v1/position-impact.json     page model (schema "position-impact")
    data/v1/dst-impact.json          page model (schema "dst-impact")
    data/position_impact_data.json   legacy view (position-impact.html)
    data/dst_removed_data.json       legacy view (dst-impact.html)

One shaper turns the position impact frames into both pages' JSON, so the
build (engine analysis tables) and the Stage A check (frames rebuilt from the
legacy inputs, engine/legacy_position_impact.py) share the same code. The
page models are the same payloads keyed by manager key instead of name.

Generic for any league: positions come from the league's lineup slots, the
Nth pick from how many of each position a lineup starts, the playoff field
from league.yaml (division winners, then the best records up to the cutoff).
A league whose lineups never start a position gets no rows for it, and a
league that never starts a D/ST gets no Life Without Defense page.
"""

from __future__ import annotations

import json

import pandas as pd

from engine.config import excluded_manager_keys
from engine.publish.build import Output
from engine.publish.legacy_view import Names, site_json

POS_SCHEMA, DST_SCHEMA, VERSION = "position-impact", "dst-impact", 1
DST = "D/ST"


def _list(v):
    """A list stored as JSON text in an analysis table, or already a list."""
    return json.loads(v) if isinstance(v, str) else (list(v) if v is not None else [])


def _round_value(v):
    """Draft capital: a round number, or a label such as 'not_in_league' / 'streamed'."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = str(v)
    return int(s) if s.lstrip("-").isdigit() else s


def frames_from_analysis(an: dict) -> dict:
    """The engine analysis tables as the shaper's frames. The D/ST page uses
    the position page's D/ST rows (one D/ST definition, the first pick)."""
    dvw, pts, stats = an["position_draft_vs_waiver"], an["position_correlation_points"], an["position_correlation"]
    return {
        "positions": sorted(an["position_flip_rates"]["position"].unique(), key=_pos_order),
        "total_games": int(len(an["dst_games"])), "flip_rates": an["position_flip_rates"],
        "season_flips": an["position_season_flips"], "net": an["position_net_impact"],
        "consistency": an["position_consistency"], "dvw": dvw, "order": an["position_draft_order"],
        "box": an["position_draft_order_box"], "cap": an["position_draft_capital"], "corr_pts": pts,
        "corr_stats": stats, "acq": an["position_acquisition"], "dst_games": an["dst_games"],
        "dst_managers": an["dst_managers"], "dst_flips": an["dst_flipped_games"],
        "dst_playoffs": an["dst_season_playoffs"], "dst_dvw": dvw[dvw["position"] == DST],
        "dst_corr_pts": pts[pts["position"] == DST], "dst_corr_stats": stats[stats["position"] == DST],
    }


POSITION_ORDER = ["QB", "RB", "WR", "TE", "K", "D/ST"]


def _pos_order(p: str) -> tuple:
    return (POSITION_ORDER.index(p) if p in POSITION_ORDER else len(POSITION_ORDER), p)


def nth_from(dvw: pd.DataFrame, positions: list[str]) -> dict:
    nth = dvw.groupby("position")["nth_pick"].first().to_dict()
    return {p: int(nth[p]) for p in positions if p in nth}


def _stats(s) -> tuple[dict, dict]:
    return ({"r": s.ppg_r, "r2": s.ppg_r2, "slope": s.ppg_slope, "intercept": s.ppg_intercept, "n": int(s.ppg_n)},
            {"r": s.round_r, "r2": s.round_r2, "slope": s.round_slope, "intercept": s.round_intercept,
             "n": int(s.round_n)})


def shape_payloads(f: dict, names, nth: dict, hidden: set[str]) -> tuple[dict, dict]:
    """position_impact_data.json and dst_removed_data.json, in the published shape.
    `names` maps a manager key to the label written (a legacy spelling, or the key itself)."""
    positions = f["positions"]
    visible = lambda mk: mk not in hidden
    pos_json = {"positions": positions, "nth_pick": nth, "total_games": int(f["total_games"])}
    pos_json["flip_rates"] = {r.position: {"flips": r.flips, "total": r.total, "pct": r.pct}
                              for r in f["flip_rates"].itertuples()}
    pos_json["net_impact"] = {p: {names(r.manager_key): r.net for r in g.itertuples()
                                  if r.gained + r.lost > 0 and visible(r.manager_key)}
                              for p, g in f["net"].groupby("position", sort=False)}
    pos_json["season_flip_rate"] = {p: {str(r.season): r.pct for r in g.itertuples()}
                                    for p, g in f["season_flips"].groupby("position", sort=False)}
    pos_json["consistency"] = {r.position: {"avg_cv": r.avg_cv, "sample": r.sample} for r in f["consistency"].itertuples()}
    dvw = f["dvw"]
    pos_json["draft_vs_waiver"] = {}
    for p in positions:
        g = dvw[dvw["position"] == p]
        pos_json["draft_vs_waiver"][p] = {
            "nth_pick": nth[p], "overall_drafted_ppg": g["overall_drafted_ppg"].iloc[0] if len(g) else 0,
            "waiver_ppg": g["waiver_ppg"].iloc[0] if len(g) else 0,
            "by_round_ppg": {str(r.round): r.ppg for r in g.itertuples()},
            "by_round_weeks": {str(r.round): r.weeks for r in g.itertuples()}}
    cap = f["cap"]
    pos_json["draft_capital"] = {p: {names(m): {"by_year": {str(r.season): _round_value(r.round) for r in mg.itertuples()},
                                                "career_avg_round": mg["career_avg_round"].iloc[0]}
                                     for m, mg in g.groupby("manager_key", sort=False)}
                                 for p, g in cap.groupby("position", sort=False)}
    pos_json["performance_correlation"] = {}
    for p in positions:
        sel = f["corr_stats"][f["corr_stats"]["position"] == p]
        if not len(sel):
            continue
        ppg_stats, round_stats = _stats(sel.iloc[0])
        pts = f["corr_pts"][f["corr_pts"]["position"] == p]
        pos_json["performance_correlation"][p] = {
            "points": [{"season": r.season, "manager": names(r.manager_key), "win_pct": round(r.win_pct, 4),
                        "ppg": round(r.ppg, 2), "drafted_round": r.drafted_round} for r in pts.itertuples()],
            "ppg_vs_winpct": ppg_stats, "round_vs_winpct": round_stats}
    acq = f["acq"]
    pos_json["acquisition_source"] = {}
    for p in positions:
        g = acq[acq["position"] == p]
        per = g[g["manager_key"].notna() & ~g["hidden"].astype(bool)]
        lt = g[g["manager_key"].isna()]
        pos_json["acquisition_source"][p] = {
            "per_manager": {names(r.manager_key): {"drafted": round(r.drafted, 1), "waiver": round(r.waiver, 1),
                                                   "traded": round(r.traded, 1)} for r in per.itertuples()},
            "league_total": {k: round(float(lt[k].iloc[0]), 1) if len(lt) else 0.0 for k in ("drafted", "waiver", "traded")}}
    pos_json["draft_order"] = {}
    for p in positions:
        g, b = f["order"][f["order"]["position"] == p], f["box"][f["box"]["position"] == p]
        pos_json["draft_order"][p] = {
            "by_order_ppg": {str(r.order): r.ppg for r in g.itertuples()},
            "by_order_weeks": {str(r.order): r.weeks for r in g.itertuples()},
            "by_order_boxplot": {str(r.order): {"min": r.min, "q1": r.q1, "median": r.median, "q3": r.q3, "max": r.max,
                                                "n": r.n} for r in b.itertuples()}}

    # ---- D/ST page
    dg = f["dst_games"]
    winner = lambda w: "TIE" if w == "TIE" else names(w)
    dst = {"league": {"total_games": int(len(dg)), "total_flips": int(dg["flipped"].sum()), "all_games": [
        {"season": int(r.season), "label": r.label, "week_num": int(r.week), "team_a": names(r.manager_a),
         "team_b": names(r.manager_b), "score_a": round(r.score_a, 2), "score_b": round(r.score_b, 2),
         "dst_a": round(r.pos_a, 2), "dst_b": round(r.pos_b, 2), "adj_a": r.adj_a, "adj_b": r.adj_b,
         "actual_winner": names(r.actual_winner), "adj_winner": winner(r.adj_winner), "flipped": bool(r.flipped)}
        for r in dg.itertuples()]}}
    dst["managers"] = {}
    mflips = f["dst_flips"]
    for r in f["dst_managers"].itertuples():
        if not visible(r.manager_key):
            continue
        fl = mflips[mflips["manager_key"] == r.manager_key] if len(mflips) else mflips
        a = acq[(acq["position"] == DST) & (acq["manager_key"] == r.manager_key)]
        dst["managers"][names(r.manager_key)] = {
            "games": r.games, "actual_record": [r.actual_w, r.actual_l], "adj_record": [r.adj_w, r.adj_l],
            "flipped_count": r.flipped,
            "flipped_games": [{"season": int(x.season), "label": x.label, "opponent": names(x.opponent),
                               "my_score": x.my_score, "opp_score": x.opp_score, "my_adj": x.my_adj, "opp_adj": x.opp_adj,
                               "direction": x.direction} for x in fl.itertuples()],
            "acquisition": ({k: round(float(a[k].iloc[0]), 1) for k in ("drafted", "waiver", "traded")} if len(a)
                            else {"drafted": 0, "waiver": 0, "traded": 0}),
            "dst_ppg": r.dst_ppg}
    dst["season_playoffs"] = {}
    for r in f["dst_playoffs"].itertuples():
        flips = _list(r.playoff_flips)
        dst["season_playoffs"][str(r.season)] = {
            "actual_top8": [names(m) for m in _list(r.actual_field)], "adj_top8": [names(m) for m in _list(r.adj_field)],
            "gained": [names(m) for m in _list(r.gained)], "lost": [names(m) for m in _list(r.lost)],
            "playoff_flips": [{"label": x["label"], "team_a": names(x["manager_a"]), "team_b": names(x["manager_b"]),
                               "score_a": round(x["score_a"], 2), "score_b": round(x["score_b"], 2), "adj_a": x["adj_a"],
                               "adj_b": x["adj_b"], "actual_winner": names(x["actual_winner"]),
                               "adj_winner": winner(x["adj_winner"])} for x in flips],
            "champion_changed": r.champion_changed,
            "actual_champion": names(r.actual_champion) if r.actual_champion else None,
            "champion_eliminated_round": r.champion_eliminated_round}
    dst["position_flip_rates"] = pos_json["flip_rates"]
    d = f["dst_dvw"]
    dst["draft_vs_waiver"] = {
        "overall_drafted_ppg": d["overall_drafted_ppg"].iloc[0], "overall_drafted_weeks": int(d["overall_drafted_weeks"].iloc[0]),
        "waiver_ppg": d["waiver_ppg"].iloc[0], "waiver_weeks": int(d["waiver_weeks"].iloc[0]),
        "by_round_ppg": {str(r.round): r.ppg for r in d.itertuples()},
        "by_round_weeks": {str(r.round): r.weeks for r in d.itertuples()}} if len(d) else {}
    dst["position_consistency"] = pos_json["consistency"]
    if len(f["dst_corr_stats"]):
        ppg_stats, round_stats = _stats(f["dst_corr_stats"].iloc[0])
        dst["dst_performance"] = {
            "points": [{"season": r.season, "manager": names(r.manager_key), "win_pct": round(r.win_pct, 4),
                        "ppg": round(r.ppg, 2), "drafted_round": r.drafted_round} for r in f["dst_corr_pts"].itertuples()],
            "ppg_vs_winpct": ppg_stats, "round_vs_winpct": round_stats}
    dcap = cap[cap["position"] == DST]
    dst["draft_capital"] = {names(m): {"by_year": {str(r.season): _round_value(r.round) for r in g.itertuples()},
                                       "career_avg_round": g["career_avg_round"].iloc[0],
                                       "years_drafted": int(g["years_drafted"].iloc[0]),
                                       "years_streamed": int(g["years_streamed"].iloc[0])}
                            for m, g in dcap.groupby("manager_key", sort=False)}
    return pos_json, dst


class _Keys:
    def __call__(self, key):
        return key


class ImpactPublisher:
    name = "impact"
    pages = {"position-impact": "data/v1/position-impact.json", "dst-impact": "data/v1/dst-impact.json"}
    NEEDS = ("position_flip_rates", "position_draft_vs_waiver", "dst_games", "dst_season_playoffs")

    def outputs(self, ctx) -> list[Output]:
        an = ctx.analysis
        if not all(n in an for n in self.NEEDS):
            return []
        f = frames_from_analysis(an)
        nth = nth_from(f["dvw"], f["positions"])
        hidden = excluded_manager_keys(ctx.cfg)
        pos_model, dst_model = shape_payloads(f, _Keys(), nth, hidden)
        live_pos = site_json(ctx, "data/position_impact_data.json") or {}
        live_dst = site_json(ctx, "data/dst_removed_data.json") or {}
        names = Names(ctx, _legacy_names(live_pos, live_dst))
        pos_view, dst_view = shape_payloads(f, names, nth, hidden)
        outs = [Output("data/v1/position-impact.json", pos_model, POS_SCHEMA, VERSION),
                Output("data/position_impact_data.json", pos_view)]
        if DST in f["positions"] and len(f["dst_games"]):
            outs += [Output("data/v1/dst-impact.json", dst_model, DST_SCHEMA, VERSION),
                     Output("data/dst_removed_data.json", dst_view)]
        return outs

    def verify(self, ctx) -> list:
        an = ctx.analysis
        if not all(n in an for n in self.NEEDS):
            return []
        from engine.legacy_position_impact import verify_position_impact

        checks, _ = verify_position_impact(ctx.tables, ctx.golden, ctx.cfg)
        for c in checks:
            c.name = "legacy view " + c.name.replace(" vs published", " vs published file")
        return checks + self.info(ctx)

    def info(self, ctx) -> list[str]:
        f = frames_from_analysis(ctx.analysis)
        fr = f["flip_rates"].set_index("position")
        live = site_json(ctx, "data/position_impact_data.json") or {}
        lf = live.get("flip_rates", {})
        return [f"INFO  position impact, engine data vs the live file: games {live.get('total_games')} -> "
                f"{f['total_games']}; flip rate " + ", ".join(
                    f"{p} {lf.get(p, {}).get('pct')}% -> {fr.loc[p, 'pct']}%" for p in f["positions"] if p in fr.index)]


def _legacy_names(*payloads) -> list[str]:
    out = []
    for p in payloads:
        for m in (p.get("managers") or {}):
            out.append(m)
        for section in ("net_impact", "draft_capital"):
            for v in (p.get(section) or {}).values():
                if isinstance(v, dict):
                    out += list(v)
    return out
