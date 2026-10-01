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
engine's sections with the legacy settings, shaped by the same code the
build uses (engine/publish/pages/impact.py), then compared field by field
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
    """position_impact_data.json and dst_removed_data.json, in the published
    shape: the frames are computed from these inputs with the legacy settings,
    then shaped by the same code the build uses (engine/publish/pages/impact.py)."""
    from engine.publish.pages.impact import shape_payloads

    started = pi.pos_started(lineups)
    rates, season_rates, net = pi.flip_summary(games, started)
    cap = pi.draft_capital(picks, active[~active["manager_key"].isin(hidden)], nth, seasons, hidden)
    corr_pts, corr_stats = pi.correlation(pi.standings_from_games(games), started, picks, nth)
    labels = pi.playoff_labels(games)
    dg = pi.dst_games(games, started, labels)
    mstats, mflips = pi.dst_managers(dg, lineups)
    real = lineups[lineups["started"] & (lineups["slot"] != "IR")]
    dpts, dstat = pi.correlation(dst_standings, pi.pos_started(real), picks, {"D/ST": 1}, from_rounded=dst_all_drafted)
    order, box = pi.draft_order(lineups, picks, nth, hidden)
    frames = {
        "positions": pi.POSITIONS, "total_games": int(len(games)), "flip_rates": rates, "season_flips": season_rates,
        "net": net, "consistency": pi.consistency(lineups), "dvw": pi.draft_vs_waiver(lineups, picks, nth, hidden),
        "order": order, "box": box, "cap": cap, "corr_pts": corr_pts, "corr_stats": corr_stats,
        "acq": pi.acquisition_summary(acquisition, hidden=hidden), "dst_games": dg, "dst_managers": mstats,
        "dst_flips": mflips, "dst_playoffs": pi.season_playoffs(dg, qualify),
        "dst_dvw": pi.draft_vs_waiver(lineups, picks, {"D/ST": 1}, frozenset() if dst_all_drafted else hidden,
                                      all_drafted=dst_all_drafted),
        "dst_corr_pts": dpts, "dst_corr_stats": dstat,
    }
    return shape_payloads(frames, lambda mk: _name(names, mk), nth, hidden)


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
