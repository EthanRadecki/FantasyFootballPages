"""Check position impact against the legacy files.

Golden files:
    data/position_impact_data.json and data/dst_removed_data.json, as
        position_impact/position_impact_data.json.gz and dst_removed_data.json.gz
    position_impact/player_stints.csv.gz   the trade stints both scripts read
        (a different version from trades/player_stints_fixed.csv.gz)
    matchup_data.csv.gz, draft_history_all_positions.csv.gz, waivers/waiver_stints_full.csv.gz
    and the lineups (weekly_rosters_clean.csv is the canonical lineups
    through 2025 with the legacy positions put back, verified row for row)

Layered check: the four inputs are rebuilt from the legacy files (games in
file order, players keyed by name as the scripts did) and run through the
engine's sections with the legacy settings, then compared field by field
with both published files.

Known legacy differences, excused by pattern:
- dst_removed_data.json was built from an older matchup_data.csv whose 2025
  week 14 Kelly row carried McQuaid at 84.46 (86.46 is right)
"""

from __future__ import annotations

import json

import pandas as pd

from engine.analytics import position_impact as pi
from engine.config import excluded_manager_keys
from engine.legacy import Comparison, name_to_key, resolve_names
from engine.publish.diff import compare_json, diff, leaves

LEGACY_NTH = {"QB": 1, "TE": 1, "K": 1, "D/ST": 1, "RB": 2, "WR": 2}
LEGACY_SEASONS = [2020, 2021, 2022, 2023, 2024, 2025]
LEGACY_CUTOFF = 8


# ---------------------------------------------------------------- inputs

def legacy_games(md: pd.DataFrame, cfg: dict, include_excluded: bool = False) -> pd.DataFrame:
    """matchup_data.csv -> games: valid rows (regular season or winners
    bracket), excluded managers' games dropped, score/outcome transpositions
    fixed, one row per game in file order (first row's team is team A)."""
    lk = name_to_key(cfg)
    ex = excluded_manager_keys(cfg)
    d = md[md["Week"].str.startswith("Week") | (md["Is_Playoff"] == "Yes")].copy()
    d["a"] = resolve_names(d["Team_Name"], lk)
    d["b"] = resolve_names(d["Opponent_Name"], lk)
    if not include_excluded:
        d = d[~d["a"].isin(ex) & ~d["b"].isin(ex)]
    ts, os_ = d["Team_Score"].astype(float), d["Opponent_Score"].astype(float)
    swap = ((d["Outcome"] == "Win") & (ts <= os_)) | ((d["Outcome"] == "Loss") & (ts >= os_))
    d["sa"], d["sb"] = ts.where(~swap, os_), os_.where(~swap, ts)
    num = d["Week"].str.extract(r"(\d+)$")[0].astype(int)
    playoff = d["Week"].str.startswith("Playoff")
    reg = num[~playoff].groupby(d["Season_Year"][~playoff]).max()
    d["week"] = num.where(~playoff, d["Season_Year"].map(reg) + num)
    d["pair"] = [tuple(sorted(p)) for p in zip(d["a"], d["b"])]
    d = d.drop_duplicates(["Season_Year", "week", "pair"])
    return pd.DataFrame({"season": d["Season_Year"].astype(int).to_numpy(), "week": d["week"].astype(int).to_numpy(),
                         "is_regular": (~playoff.loc[d.index]).to_numpy(), "manager_a": d["a"].to_numpy(),
                         "manager_b": d["b"].to_numpy(), "score_a": d["sa"].to_numpy(), "score_b": d["sb"].to_numpy()})


def legacy_lineups(tables: dict, golden: dict, cfg: dict) -> pd.DataFrame:
    from engine.legacy_trades import legacy_positions

    t = dict(tables)
    t["lineups"] = tables["lineups"][tables["lineups"]["season"] <= 2025]
    t2, _ = legacy_positions(t, golden["weekly_rosters_bracket_only"], cfg)
    lu = t2["lineups"]
    # the legacy position applies to the whole player-season (consolation weeks too)
    changed = lu.merge(t["lineups"][["season", "week", "manager_key", "player_id", "position"]],
                       on=["season", "week", "manager_key", "player_id"], suffixes=("", "_orig"))
    fix = changed[changed["position"] != changed["position_orig"]][["season", "player_id", "position"]].drop_duplicates()
    lu = t["lineups"].merge(fix.rename(columns={"position": "legacy_pos"}), on=["season", "player_id"], how="left")
    lu["position"] = lu["legacy_pos"].fillna(lu["position"])
    return lu.drop(columns="legacy_pos").assign(player_key=lambda d: d["player_name"])


def legacy_picks(draft: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    d = draft[draft["season"] <= 2025]
    return pd.DataFrame({"season": d["season"].astype(int), "manager_key": resolve_names(d["manager"], name_to_key(cfg)),
                         "round": d["round"].astype(int), "overall_pick": d["overall_pick"].astype(int),
                         "player_key": d["player_name"], "player_name": d["player_name"], "position": d["position"]})


def legacy_acquisition(lineups: pd.DataFrame, waiver: pd.DataFrame, trade_stints: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Drafted is the residual: all points at the position (every week, bench
    and IR too) minus waiver-stint points (by the stint file's position label)
    minus traded points (each trade stint's consecutive weeks from its start)."""
    lk = name_to_key(cfg)
    tot = lineups.groupby(["manager_key", "position"])["points"].sum()
    w = waiver.assign(mk=resolve_names(waiver["Manager"], lk)).groupby(["mk", "Position"])["Total_Points"].sum()
    by_pid = lineups.set_index(["season", "manager_key", "player_id", "week"])["points"]
    tr = trade_stints.assign(mk=resolve_names(trade_stints["receiving_manager"], lk))
    traded = {}
    for r in tr.itertuples(index=False):
        pts = sum(by_pid.get((r.season, r.mk, r.player_id, wk), 0.0)
                  for wk in range(int(r.scoring_period), int(r.scoring_period) + int(r.weeks_rostered)))
        traded[(r.mk, r.position)] = traded.get((r.mk, r.position), 0.0) + pts
    rows = []
    for (mk, pos), total in tot.items():
        wv = w.get((mk, pos), 0.0)
        t_ = traded.get((mk, pos), 0.0)
        rows.append({"season": 0, "manager_key": mk, "position": pos, "drafted": total - wv - t_, "waiver": wv, "traded": t_})
    return pd.DataFrame(rows)


def legacy_dst_standings(md: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """generate_dst_impact.py's standings: every regular-season row whose own
    manager is not excluded (games against excluded managers kept), by Outcome."""
    lk = name_to_key(cfg)
    ex = excluded_manager_keys(cfg)
    d = md[md["Week"].str.startswith("Week")].assign(mk=lambda x: resolve_names(x["Team_Name"], lk))
    d = d[~d["mk"].isin(ex)]
    g = d.groupby(["Season_Year", "mk"], sort=False).agg(wins=("Outcome", lambda o: float((o == "Win").sum())), games=("Outcome", "size"))
    return g.reset_index().rename(columns={"Season_Year": "season", "mk": "manager_key"})


# ---------------------------------------------------------------- payloads

def _name(names: dict, mk: str) -> str:
    return names.get(mk, mk)


def build_payloads(games, lineups, picks, active, acquisition, names, nth, seasons, hidden, qualify,
                   dst_standings, dst_all_drafted: bool) -> tuple[dict, dict]:
    """position_impact_data.json and dst_removed_data.json, in the published shape."""
    started = pi.pos_started(lineups)
    rates, season_rates, net = pi.flip_summary(games, started)
    cons = pi.consistency(lineups)
    dvw = pi.draft_vs_waiver(lineups, picks, nth, hidden)
    order, box = pi.draft_order(lineups, picks, nth, hidden)
    cap = pi.draft_capital(picks, active[~active["manager_key"].isin(hidden)], nth, seasons, hidden)
    stand = pi.standings_from_games(games)
    corr_pts, corr_stats = pi.correlation(stand, started, picks, nth)
    acq = pi.acquisition_summary(acquisition, hidden=hidden)
    visible = lambda mk: mk not in hidden

    pos_json = {"positions": pi.POSITIONS, "nth_pick": nth, "total_games": int(len(games))}
    pos_json["flip_rates"] = {r.position: {"flips": r.flips, "total": r.total, "pct": r.pct} for r in rates.itertuples()}
    pos_json["net_impact"] = {p: {_name(names, r.manager_key): r.net for r in g.itertuples() if r.gained + r.lost > 0
                                  and visible(r.manager_key)} for p, g in net.groupby("position", sort=False)}
    pos_json["season_flip_rate"] = {p: {str(r.season): r.pct for r in g.itertuples()} for p, g in season_rates.groupby("position", sort=False)}
    pos_json["consistency"] = {r.position: {"avg_cv": r.avg_cv, "sample": r.sample} for r in cons.itertuples()}
    pos_json["draft_vs_waiver"] = {}
    for p in pi.POSITIONS:
        g = dvw[dvw["position"] == p]
        pos_json["draft_vs_waiver"][p] = {
            "nth_pick": nth[p], "overall_drafted_ppg": g["overall_drafted_ppg"].iloc[0] if len(g) else 0,
            "waiver_ppg": g["waiver_ppg"].iloc[0] if len(g) else 0,
            "by_round_ppg": {str(r.round): r.ppg for r in g.itertuples()},
            "by_round_weeks": {str(r.round): r.weeks for r in g.itertuples()}}
    pos_json["draft_capital"] = {p: {_name(names, m): {"by_year": {str(r.season): r.round for r in mg.itertuples()},
                                                       "career_avg_round": mg["career_avg_round"].iloc[0]}
                                     for m, mg in g.groupby("manager_key", sort=False)}
                                 for p, g in cap.groupby("position", sort=False)}
    pos_json["performance_correlation"] = {}
    for p in pi.POSITIONS:
        s = corr_stats[corr_stats["position"] == p].iloc[0]
        pts = corr_pts[corr_pts["position"] == p]
        pos_json["performance_correlation"][p] = {
            "points": [{"season": r.season, "manager": _name(names, r.manager_key), "win_pct": round(r.win_pct, 4),
                        "ppg": round(r.ppg, 2), "drafted_round": r.drafted_round} for r in pts.itertuples()],
            "ppg_vs_winpct": {"r": s.ppg_r, "r2": s.ppg_r2, "slope": s.ppg_slope, "intercept": s.ppg_intercept, "n": int(s.ppg_n)},
            "round_vs_winpct": {"r": s.round_r, "r2": s.round_r2, "slope": s.round_slope, "intercept": s.round_intercept,
                                "n": int(s.round_n)}}
    pos_json["acquisition_source"] = {}
    for p in pi.POSITIONS:
        g = acq[acq["position"] == p]
        per = g[g["manager_key"].notna() & ~g["hidden"]]
        lt = g[g["manager_key"].isna()]
        pos_json["acquisition_source"][p] = {
            "per_manager": {_name(names, r.manager_key): {"drafted": round(r.drafted, 1), "waiver": round(r.waiver, 1),
                                                          "traded": round(r.traded, 1)} for r in per.itertuples()},
            "league_total": {k: round(float(lt[k].iloc[0]), 1) if len(lt) else 0.0 for k in ("drafted", "waiver", "traded")}}
    pos_json["draft_order"] = {}
    for p in pi.POSITIONS:
        g, b = order[order["position"] == p], box[box["position"] == p]
        pos_json["draft_order"][p] = {
            "by_order_ppg": {str(r.order): r.ppg for r in g.itertuples()},
            "by_order_weeks": {str(r.order): r.weeks for r in g.itertuples()},
            "by_order_boxplot": {str(r.order): {"min": r.min, "q1": r.q1, "median": r.median, "q3": r.q3, "max": r.max,
                                                "n": r.n} for r in b.itertuples()}}

    # ---- D/ST page
    labels = pi.playoff_labels(games)
    dg = pi.dst_games(games, started, labels)
    mstats, mflips = pi.dst_managers(dg, lineups)
    playoffs = pi.season_playoffs(dg, qualify)
    dst = {"league": {"total_games": int(len(dg)), "total_flips": int(dg["flipped"].sum()), "all_games": [
        {"season": int(r.season), "label": r.label, "week_num": int(r.week), "team_a": _name(names, r.manager_a),
         "team_b": _name(names, r.manager_b), "score_a": round(r.score_a, 2), "score_b": round(r.score_b, 2),
         "dst_a": round(r.pos_a, 2), "dst_b": round(r.pos_b, 2), "adj_a": r.adj_a, "adj_b": r.adj_b,
         "actual_winner": _name(names, r.actual_winner),
         "adj_winner": "TIE" if r.adj_winner == "TIE" else _name(names, r.adj_winner), "flipped": bool(r.flipped)}
        for r in dg.itertuples()]}}
    dst["managers"] = {}
    for r in mstats.itertuples():
        if not visible(r.manager_key):
            continue
        fl = mflips[mflips["manager_key"] == r.manager_key] if len(mflips) else mflips
        a = acq[(acq["position"] == "D/ST") & (acq["manager_key"] == r.manager_key)]
        dst["managers"][_name(names, r.manager_key)] = {
            "games": r.games, "actual_record": [r.actual_w, r.actual_l], "adj_record": [r.adj_w, r.adj_l],
            "flipped_count": r.flipped,
            "flipped_games": [{"season": int(f.season), "label": f.label, "opponent": _name(names, f.opponent),
                               "my_score": f.my_score, "opp_score": f.opp_score, "my_adj": f.my_adj, "opp_adj": f.opp_adj,
                               "direction": f.direction} for f in fl.itertuples()],
            "acquisition": ({k: round(float(a[k].iloc[0]), 1) for k in ("drafted", "waiver", "traded")} if len(a)
                            else {"drafted": 0, "waiver": 0, "traded": 0}),
            "dst_ppg": r.dst_ppg}
    dst["season_playoffs"] = {str(r.season): {
        "actual_top8": [_name(names, m) for m in r.actual_field], "adj_top8": [_name(names, m) for m in r.adj_field],
        "gained": [_name(names, m) for m in r.gained], "lost": [_name(names, m) for m in r.lost],
        "playoff_flips": [{"label": f["label"], "team_a": _name(names, f["manager_a"]), "team_b": _name(names, f["manager_b"]),
                           "score_a": round(f["score_a"], 2), "score_b": round(f["score_b"], 2), "adj_a": f["adj_a"],
                           "adj_b": f["adj_b"], "actual_winner": _name(names, f["actual_winner"]),
                           "adj_winner": "TIE" if f["adj_winner"] == "TIE" else _name(names, f["adj_winner"])}
                          for f in r.playoff_flips],
        "champion_changed": r.champion_changed, "actual_champion": _name(names, r.actual_champion) if r.actual_champion else None,
        "champion_eliminated_round": r.champion_eliminated_round} for r in playoffs.itertuples()}
    dst["position_flip_rates"] = pos_json["flip_rates"]
    dvw_d = pi.draft_vs_waiver(lineups, picks, {"D/ST": 1}, frozenset() if dst_all_drafted else hidden,
                               all_drafted=dst_all_drafted)
    dst["draft_vs_waiver"] = {
        "overall_drafted_ppg": dvw_d["overall_drafted_ppg"].iloc[0], "overall_drafted_weeks": int(dvw_d["overall_drafted_weeks"].iloc[0]),
        "waiver_ppg": dvw_d["waiver_ppg"].iloc[0], "waiver_weeks": int(dvw_d["waiver_weeks"].iloc[0]),
        "by_round_ppg": {str(r.round): r.ppg for r in dvw_d.itertuples()},
        "by_round_weeks": {str(r.round): r.weeks for r in dvw_d.itertuples()}}
    dst["position_consistency"] = pos_json["consistency"]
    real = lineups[lineups["started"] & (lineups["slot"] != "IR")]
    dst_started = pi.pos_started(real)
    dpts, dstat = pi.correlation(dst_standings, dst_started, picks, {"D/ST": 1}, from_rounded=dst_all_drafted)
    s = dstat.iloc[0]
    dst["dst_performance"] = {
        "points": [{"season": r.season, "manager": _name(names, r.manager_key), "win_pct": round(r.win_pct, 4),
                    "ppg": round(r.ppg, 2), "drafted_round": r.drafted_round} for r in dpts.itertuples()],
        "ppg_vs_winpct": {"r": s.ppg_r, "r2": s.ppg_r2, "slope": s.ppg_slope, "intercept": s.ppg_intercept, "n": int(s.ppg_n)},
        "round_vs_winpct": {"r": s.round_r, "r2": s.round_r2, "slope": s.round_slope, "intercept": s.round_intercept,
                            "n": int(s.round_n)}}
    dcap = cap[cap["position"] == "D/ST"]
    dst["draft_capital"] = {_name(names, m): {"by_year": {str(r.season): r.round for r in g.itertuples()},
                                              "career_avg_round": g["career_avg_round"].iloc[0],
                                              "years_drafted": int(g["years_drafted"].iloc[0]),
                                              "years_streamed": int(g["years_streamed"].iloc[0])}
                            for m, g in dcap.groupby("manager_key", sort=False)}
    return pos_json, dst


# ---------------------------------------------------------------- compare

# The JSON diff moved to engine/publish/diff.py (phase 4); the names stay here for callers.
_diff = diff
_leaves = leaves


def _dst_known(path, engine_value, legacy_value):
    if "all_games" in path or "flipped_games" in path or "playoff" in path:
        if {engine_value, legacy_value} <= {86.46, 84.46} and engine_value != legacy_value:
            return "published file used an older matchup_data.csv (McQuaid 84.46 in 2025 week 14; 86.46 is right)"
    return None


def verify_position_impact(tables: dict, golden: dict, cfg: dict, analysis: dict | None = None) -> tuple[list[Comparison], list[str]]:
    lk = name_to_key(cfg)
    names = {m["id"]: m["name"] for m in cfg.get("managers") or []}
    for long in ("Carmine Pittelli Jr.", "Ryan P McQuaid"):      # the legacy files' spelling
        names[lk[long.lower()]] = long
    hidden = excluded_manager_keys(cfg)
    games = legacy_games(golden["matchup_data"], cfg)
    lineups = legacy_lineups(tables, golden, cfg)
    picks = legacy_picks(golden["draft_history_all_positions"], cfg)
    active = picks[["season", "manager_key"]].drop_duplicates()
    acq = legacy_acquisition(lineups, golden["waiver_stints_full"], golden["pi_player_stints"], cfg)

    def top8(season, st):
        st = st.assign(pct=st["wins"] / st["games"]).sort_values(["pct", "points"], ascending=False, kind="stable")
        return st["manager_key"].head(LEGACY_CUTOFF).tolist()

    pos_json, dst_json = build_payloads(games, lineups, picks, active, acq, names, LEGACY_NTH, LEGACY_SEASONS, hidden,
                                        top8, legacy_dst_standings(golden["matchup_data"], cfg), dst_all_drafted=True)
    checks = compare_json("position impact", pos_json, golden["position_impact_data"])
    checks += compare_json("D/ST impact", dst_json, golden["dst_removed_data"], known=_dst_known)
    info = [f"INFO  legacy inputs: {len(games)} games, nth pick {LEGACY_NTH}, top {LEGACY_CUTOFF} by win%"]
    if analysis and "position_flip_rates" in analysis:
        info += engine_changes(analysis, pos_json, dst_json, names, cfg)
    return checks, info


def engine_changes(an: dict, pos_json: dict, dst_json: dict, names: dict, cfg: dict) -> list[str]:
    fr = an["position_flip_rates"].set_index("position")
    lines = ["INFO  engine: every counted game (2026 so far, and 2020 games against the excluded managers, who are "
             "hidden); bracket weeks only; Nth pick from the lineup slots; one D/ST calculation (first-pick "
             "definition); playoff field by league.yaml cutoff with division winners; acquisition by how each "
             "rostered week's player arrived",
             f"INFO      games {pos_json['total_games']} -> {int(fr['total'].iloc[0])}; flip rate legacy -> engine: " + ", ".join(
                 f"{p} {pos_json['flip_rates'][p]['pct']}% -> {fr.loc[p, 'pct']}%" for p in fr.index)]
    acq = an["position_acquisition"]
    lt = acq[acq["manager_key"].isna()].set_index("position")
    parts = []
    for p in lt.index:
        leg = pos_json["acquisition_source"][p]["league_total"]
        tot_l, tot_e = sum(leg.values()), lt.loc[p, ["drafted", "waiver", "traded"]].sum()
        parts.append(f"{p} " + "/".join(f"{round(leg[k] / tot_l * 100)}" for k in ("drafted", "waiver", "traded"))
                     + " -> " + "/".join(f"{round(lt.loc[p, k] / tot_e * 100)}" for k in ("drafted", "waiver", "traded")))
    lines.append("INFO      league points drafted/waiver/traded %: " + "; ".join(parts))
    nth = an["position_draft_vs_waiver"].groupby("position")["nth_pick"].first().to_dict()
    lines.append(f"INFO      Nth pick from lineup slots: {nth}")
    po = an["dst_season_playoffs"].set_index("season")
    ch = []
    for s, r in po.iterrows():
        leg = dst_json["season_playoffs"].get(str(s))
        gained = [names.get(m, m) for m in json.loads(r["gained"])]
        lost = [names.get(m, m) for m in json.loads(r["lost"])]
        ch.append(f"{s}: +{gained} -{lost} champion changed {r['champion_changed']}"
                  + (f" (legacy +{leg['gained']} -{leg['lost']})" if leg else ""))
    lines.append("INFO      playoff field without D/ST: " + "; ".join(ch))
    return lines
