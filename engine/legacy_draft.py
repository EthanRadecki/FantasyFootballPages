"""Compare the draft value analysis with the legacy draft files.

Golden files (engine/tests/golden/draft/):
    espn_player_stats_season.csv.gz    legacy stats pull, 2020-2025 (rerun 2026-09-29)
    espn_player_stats_2026.csv.gz      legacy 2026 stats at the last site update
    draft_surplus_v2.csv.gz            per-pick surplus, 2020-2025
    surplus_value_data.json.gz         career and season grades
    surplus_value_2026_live.csv.gz     per-pick surplus, 2026 live
    draft_heatmap.json.gz              per-manager board by round and slot
    hit_rate_data.json.gz              hit rate by round and tier, steals
    draft_with_stats.csv.gz            legacy pick-to-stats matches (hand-kept zeros)

The checks run in layers, as for trades:
1. the stats themselves: engine.legacy.check_player_stats (normalize --verify)
2. the draft logic, in legacy mode, fed the legacy stats files: must match
   every legacy number exactly
3. engine mode vs legacy mode, listed for review

Legacy mode inputs, each a documented legacy behavior:
- ESPN's pick numbering (before the 2021 draft-order correction)
- the hand-kept injury list: picks zeroed with 8+ games (draft_surplus_v2)
- name matching: legacy matched picks to stats by name, so a 2026 pick whose
  ESPN draft name differs from its stats name ("James Cook" vs "James Cook
  III") got no stats; picks marked manual_zero in draft_with_stats likewise
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from engine.analytics import draft as draft_mod
from engine.config import excluded_manager_keys
from engine.legacy import Comparison, compare, name_to_key, resolve_names

NAN = -999999.0


def _num(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    out = df.copy()
    for c in cols:
        out[c] = out[c].astype(float).fillna(NAN)
    return out


def legacy_stats(golden: dict) -> pd.DataFrame:
    """The legacy stats files, shaped like player_stats."""
    s = pd.concat([golden["espn_player_stats_season"], golden["espn_player_stats_2026"]], ignore_index=True)
    return pd.DataFrame({"season": s["season"].astype(int), "player_id": s["player_id"].astype(int),
                         "position": s["position"], "avg_points": s["ppr_per_game"].astype(float),
                         "games": s["games_played"].astype(int)})


def legacy_zeroes(golden: dict, stats: pd.DataFrame) -> tuple[set, set, set, dict]:
    """(injury-zeroed picks, name-missed picks, hit-rate zeroed picks, counts by reason)."""
    v2 = golden["draft_surplus_v2"]
    injury = {(int(r.season), int(r.overall_pick)) for r in v2[(v2["injury_zeroed"] == 1) & (v2["games_played"] >= 8)].itertuples()}
    live = golden["surplus_value_2026_live"]
    played = stats[stats["games"] > 0][["season", "player_id"]]
    names = live[live["no_data_yet"] == 1][["season", "overall_pick", "player_name"]]
    names = names.merge(golden["draft_picks_2026"], on=["season", "overall_pick"]).merge(played, on=["season", "player_id"])
    name_miss = {(int(r.season), int(r.overall_pick)) for r in names.itertuples()}
    dws = golden["draft_with_stats"]
    manual = {(int(r.season), int(r.overall_pick)) for r in dws[dws["match_status"] == "manual_zero"].itertuples()}
    counts = {"hand-kept injury list (8+ games, zeroed)": len(injury),
              "2026 pick name differs from its stats name (legacy name match missed)": len(name_miss),
              "hand-kept manual_zero list in draft_with_stats (hit rate)": len(manual)}
    return injury, name_miss, manual, counts


def check_surplus(analysis: dict, v2: pd.DataFrame, live: pd.DataFrame, cfg: dict) -> Comparison:
    lookup = name_to_key(cfg)
    exp = pd.concat([
        pd.DataFrame({"season": v2["season"], "overall_pick": v2["overall_pick"], "round": v2["round"],
                      "draft_slot": v2["draft_slot"], "manager_key": resolve_names(v2["manager"], lookup),
                      "position": v2["position"], "ppg": v2["ppr_per_game"], "games": v2["games_played"],
                      "prv": v2["prv"], "expected_prv": v2["expected_prv"], "n_comps": v2["n_comps"],
                      "surplus": v2["surplus"], "surplus_wtd": v2["surplus_wtd"], "zeroed": v2["injury_zeroed"].astype(bool)}),
        pd.DataFrame({"season": live["season"], "overall_pick": live["overall_pick"], "round": live["round"],
                      "draft_slot": live["draft_slot"], "manager_key": resolve_names(live["manager"], lookup),
                      "position": live["position"], "ppg": live["ppr_per_game"], "games": live["games_played"],
                      "prv": live["prv"], "expected_prv": live["expected_prv"], "n_comps": live["n_comps"],
                      "surplus": live["surplus"], "surplus_wtd": live["surplus_wtd"],
                      "zeroed": live["no_data_yet"].astype(bool)}),
    ], ignore_index=True)
    num = ["ppg", "games", "prv", "expected_prv", "n_comps", "surplus", "surplus_wtd"]
    return compare("draft surplus vs draft_surplus_v2.csv + surplus_value_2026_live.csv", _num(exp, num),
                   _num(analysis["draft_surplus"], num), keys=["season", "overall_pick"],
                   values=["round", "draft_slot", "manager_key", "position", "zeroed"] + num, tolerance=1e-6)


def check_grades(analysis: dict, grades: dict, live_json: dict, cfg: dict) -> Comparison:
    lookup = name_to_key(cfg)
    career = pd.DataFrame(grades["career_grades"])
    exp_c = pd.DataFrame({"kind": "career", "season": 0, "manager_key": resolve_names(career["manager"], lookup),
                          "grade": career["avg_surplus"], "total": career["weighted_total"],
                          "picks": career["total_picks"], "rank": career["rank"]})
    seasons = pd.DataFrame(grades["season_grades"])
    exp_s = pd.DataFrame({"kind": "season", "season": seasons["season"],
                          "manager_key": resolve_names(seasons["manager"], lookup), "grade": seasons["draft_grade"],
                          "total": seasons["draft_grade"], "picks": NAN, "rank": seasons["season_rank"]})
    live = pd.DataFrame([{"manager": m, **v} for m, v in live_json.items()])
    exp_l = pd.DataFrame({"kind": "live", "season": 2026, "manager_key": resolve_names(live["manager"], lookup),
                          "grade": live["draft_grade"], "total": live["draft_surplus_total"],
                          "picks": live["total_picks"], "rank": live["rank"]})
    c = analysis["draft_career_grades"]
    act_c = pd.DataFrame({"kind": "career", "season": 0, "manager_key": c["manager_key"], "grade": c["avg_surplus"],
                          "total": c["weighted_total"].round(2), "picks": c["total_picks"], "rank": c["rank"]})
    s = analysis["draft_season_grades"]
    fin = s[s["season"] != 2026]
    act_s = pd.DataFrame({"kind": "season", "season": fin["season"], "manager_key": fin["manager_key"],
                          "grade": fin["draft_grade"], "total": fin["draft_grade"], "picks": NAN,
                          "rank": fin["season_rank"]})
    lv = s[s["season"] == 2026].sort_values("draft_grade", ascending=False, kind="stable").reset_index(drop=True)
    act_l = pd.DataFrame({"kind": "live", "season": 2026, "manager_key": lv["manager_key"], "grade": lv["draft_grade"],
                          "total": lv["draft_grade"], "picks": lv["total_picks"], "rank": lv.index + 1})
    return compare("draft grades vs surplus_value_data.json + surplus_value_2026_live.json",
                   pd.concat([exp_c, exp_s, exp_l]), pd.concat([act_c, act_s, act_l]),
                   keys=["kind", "season", "manager_key"], values=["grade", "total", "picks", "rank"], tolerance=1e-6)


def check_heatmap(analysis: dict, heat: dict, cfg: dict) -> Comparison:
    lookup = name_to_key(cfg)
    rows = [{"manager_key": lookup[m.strip().lower()], "round": c["round"], "draft_slot": c["slot"],
             "avg_surplus": c["avg_surplus"], "n_seasons": c["n_seasons"]}
            for m, v in heat.items() for c in v["board"].values()]
    return compare("draft heatmap vs draft_heatmap.json", pd.DataFrame(rows), analysis["draft_heatmap"],
                   keys=["manager_key", "round", "draft_slot"], values=["avg_surplus", "n_seasons"], tolerance=1e-6)


def check_hit_rate(analysis: dict, hit: dict, tables: dict, cfg: dict) -> Comparison:
    """by_round hits and totals, tier x position rates, overall tiers, steals.
    Legacy position concentration counts (rb, wr, ...) used seasons 2020-2024
    only; they are rebuilt the same way here from the draft table."""
    h = analysis["draft_hits"]
    lookup = name_to_key(cfg)
    rows_exp, rows_act = [], []
    for r in hit["by_round"]:
        rows_exp.append({"table": "round", "key": str(r["round"]), "total": r["total_picks"], "hits": r["hits"],
                         "rate": r["hit_rate"]})
    for rnd, g in h.groupby("round"):
        rows_act.append({"table": "round", "key": str(rnd), "total": len(g), "hits": int(g["hit"].sum()),
                         "rate": round(g["hit"].sum() / len(g) * 100, 1)})
    for r in hit["overall"]:
        rows_exp.append({"table": "tier", "key": r["tier_short"], "total": r["total_picks"], "hits": r["hits"],
                         "rate": r["hit_rate"]})
    for name, _, _ in draft_mod.TIERS:
        g = h[h["tier"] == name]
        rows_act.append({"table": "tier", "key": name, "total": len(g), "hits": int(g["hit"].sum()),
                         "rate": round(g["hit"].sum() / len(g) * 100, 1)})
    for pos, rates in hit["tier_pos"].items():
        for (name, _, _), rate in zip(draft_mod.TIERS, rates):
            rows_exp.append({"table": "tier_pos", "key": f"{name}_{pos}", "total": NAN, "hits": NAN, "rate": rate})
            g = h[(h["tier"] == name) & (h["position"] == pos)]
            rows_act.append({"table": "tier_pos", "key": f"{name}_{pos}", "total": NAN, "hits": NAN,
                             "rate": round(g["hit"].sum() / len(g) * 100, 1) if len(g) else 0})
    dp = tables["draft_picks"].merge(tables["player_seasons"][["season", "player_id", "position"]],
                                     on=["season", "player_id"], how="left")
    dp = dp[dp["season"] <= 2024]
    for r in hit["by_round"]:
        g = dp[dp["round"] == r["round"]]["position"].value_counts()
        for col, pos in (("rb", "RB"), ("wr", "WR"), ("qb", "QB"), ("te", "TE"), ("k", "K"), ("dst", "D/ST")):
            rows_exp.append({"table": "round_pos", "key": f"{r['round']}_{col}", "total": r[col], "hits": NAN, "rate": NAN})
            rows_act.append({"table": "round_pos", "key": f"{r['round']}_{col}", "total": int(g.get(pos, 0)),
                             "hits": NAN, "rate": NAN})
    steal_sets = [("all", hit["top_steals"], draft_mod.steals(h))]
    for season, lst in hit["season_steals"].items():
        steal_sets.append((season, lst, draft_mod.steals(h[h["season"] == int(season)])))
    for label, lst, act in steal_sets:
        act = act.reset_index(drop=True)
        for i, s in enumerate(lst):
            rows_exp.append({"table": f"steals_{label}", "key": str(i + 1),
                             "total": s["season"] * 1000 + s["round"] * 10 + 0, "hits": s["games"],
                             "rate": s["pts_above_avg"], "manager_key": lookup[s["manager"].strip().lower()]})
        for i, s in act.iterrows():
            rows_act.append({"table": f"steals_{label}", "key": str(i + 1),
                             "total": s["season"] * 1000 + s["round"] * 10 + 0, "hits": s["games"],
                             "rate": s["pts_above_avg"], "manager_key": s["manager_key"]})
    exp, act = pd.DataFrame(rows_exp), pd.DataFrame(rows_act)
    for df in (exp, act):
        df["manager_key"] = df.get("manager_key", pd.Series(dtype=object)).fillna("")
    # A steals list can end on a tie: the legacy sort was unstable, so another
    # pick with the same points above average can take the place.
    tie = exp.merge(act, on=["table", "key"], suffixes=("", "_e"))
    tie = tie[tie["table"].str.startswith("steals") & (tie["rate"] == tie["rate_e"])
              & (tie["manager_key"] != tie["manager_key_e"])][["table", "key"]]
    known = pd.concat([tie.assign(column=c, reason="steals list tied on points above average; unstable legacy sort")
                       for c in ("total", "hits", "manager_key")], ignore_index=True)
    return compare("hit rate vs hit_rate_data.json", _num(exp, ["total", "hits", "rate"]),
                   _num(act, ["total", "hits", "rate"]), keys=["table", "key"],
                   values=["total", "hits", "rate", "manager_key"], tolerance=1e-6, known=known)


def engine_vs_legacy(engine: dict, legacy: dict, cfg: dict) -> list[str]:
    """What the engine changes relative to legacy mode, finished seasons only
    (a live season also moves with every new week of stats)."""
    who = {m["id"]: m["name"] for m in cfg.get("managers") or []}
    e, l = engine["draft_surplus"], legacy["draft_surplus"]
    m = e.merge(l, on=["season", "player_id", "manager_key"], suffixes=("_e", "_l"))
    live = set(draft_mod.live_seasons_from(e))
    fin = m[~m["season"].isin(live)]
    d = (fin["surplus_e"] - fin["surplus_l"]).abs()
    small, big = int(((d > 0.005) & (d <= 0.5)).sum()), int((d > 0.5).sum())
    ce, cl = engine["draft_career_grades"], legacy["draft_career_grades"]
    ranks = ce[["manager_key", "rank"]].merge(cl[["manager_key", "rank"]], on="manager_key", suffixes=("_e", "_l"))
    changed = ranks[ranks["rank_e"] != ranks["rank_l"]].sort_values("rank_e")
    lines = [f"INFO  engine vs legacy mode, finished seasons ({len(fin)} picks): {big} change surplus by more than 0.5, "
             f"{small} by 0.005 to 0.5 (2021 pick numbers corrected, stats by player id, hand-kept zeros dropped, "
             "full player pool, baseline needs 8 games)"]
    if len(changed):
        lines.append("      career rank changes: " + ", ".join(
            f"{who.get(r.manager_key, r.manager_key)} {r.rank_l} -> {r.rank_e}" for r in changed.itertuples()))
    return lines


def verify_draft(tables: dict, golden: dict, cfg: dict) -> tuple[list[Comparison], list[str]]:
    exclude = excluded_manager_keys(cfg)
    stats = legacy_stats(golden)
    dp26 = tables["draft_picks"][tables["draft_picks"]["season"] == 2026][["season", "overall_pick", "player_id"]]
    golden = {**golden, "draft_picks_2026": dp26}
    injury, name_miss, hit_zero, counts = legacy_zeroes(golden, stats)
    legacy = draft_mod.analyze_draft(tables, exclude, legacy_mode=True, legacy_universe=stats,
                                     force_zero=injury, hit_force_zero=hit_zero, no_stats=name_miss)
    engine = draft_mod.analyze_draft(tables, exclude)
    info = ["INFO  legacy mode inputs: legacy stats files; " + "; ".join(f"{k}: {v}" for k, v in counts.items())]
    results = [
        check_surplus(legacy, golden["draft_surplus_v2"], golden["surplus_value_2026_live"], cfg),
        check_grades(legacy, golden["surplus_value_data"], golden["surplus_value_2026_live_json"], cfg),
        check_heatmap(legacy, golden["draft_heatmap"], cfg),
        check_hit_rate(legacy, golden["hit_rate_data"], tables, cfg),
    ]
    if "draft_board_page" in golden:
        results += check_board(legacy, golden["draft_board_page"], cfg)
        info.append(board_changes(engine, legacy)[0])
    return results, info + engine_vs_legacy(engine, legacy, cfg) + hidden_effect(tables, engine, exclude, cfg)


def board_frame(data: dict) -> pd.DataFrame:
    rows = [{"season": int(s), "round": int(r), "pick_in_round": i + 1, "player_name": p["p"], "position": p["pos"],
             "ppg": p["ppg"], "games": p["g"]}
            for s, rounds in data["DRAFT"].items() for r, picks in rounds.items() for i, p in enumerate(picks)]
    return pd.DataFrame(rows)


def check_board(legacy: dict, page: dict, cfg: dict) -> list[Comparison]:
    """draft-history.html's inline DRAFT and SLOT_ORDER (generate_draft_board_data.py,
    run on a draft file already in the corrected 2021 order and with ESPN's names)."""
    names = {m["id"]: m["name"] for m in cfg.get("managers") or []}
    act_data = draft_mod.board_data(legacy["draft_board"], names)
    keys = ["season", "round", "pick_in_round"]
    exp, act = board_frame(page), board_frame(act_data)
    exp, act = _num(exp, ["ppg", "games"]), _num(act, ["ppg", "games"])
    board = compare("draft board vs draft-history.html", exp, act, keys=keys,
                    values=["player_name", "position", "ppg", "games"], tolerance=1e-9)
    so = lambda d: pd.DataFrame([{"season": int(s), "slot": i + 1, "manager": m}
                                 for s, ms in d["SLOT_ORDER"].items() for i, m in enumerate(ms)])
    slots = compare("draft slot order vs draft-history.html", so(page), so(act_data), keys=["season", "slot"],
                    values=["manager"])
    return [board, slots]


def board_changes(engine: dict, legacy: dict) -> list[str]:
    k = ["season", "overall_pick"]
    m = legacy["draft_board"].merge(engine["draft_board"], on=k, suffixes=("_l", "_e"))
    live = [s for s, g in m.groupby("season") if g["ppg_l"].isna().all()]
    filled = m["ppg_l"].isna() & m["ppg_e"].notna()
    by = m[filled].assign(what=m["position_e"].where(~m["season"].isin(live), "live season")).groupby("what").size()
    zero = (m["games_l"] == 0) & (m["games_e"] > 0)
    moved = m["ppg_l"].notna() & m["ppg_e"].notna() & ~zero & ((m["ppg_l"] - m["ppg_e"]).abs() > 1e-9)
    return [f"INFO  engine draft board: PPG added for {int(filled.sum())} pick(s) ("
            + ", ".join(f"{k_} {v}" for k_, v in by.items()) + "); "
            f"{int(zero.sum())} hand-kept zero(s) replaced by the player's real stats; "
            f"{int(moved.sum())} PPG value(s) 0.01 apart (ESPN's average at a rounding tie, e.g. 12.475)"]


def hidden_effect(tables: dict, engine: dict, exclude: set[str], cfg: dict) -> list[str]:
    """INFO: the effect of counting excluded managers' picks (hidden) instead
    of dropping them, measured against the engine with those picks dropped."""
    dp = tables["draft_picks"]
    dropped = draft_mod.analyze_draft({**tables, "draft_picks": dp[~dp["manager_key"].isin(exclude)]}, exclude)
    k = ["season", "overall_pick"]
    e, d = engine["draft_surplus"], dropped["draft_surplus"]
    m = e[~e["hidden"]].merge(d, on=k, suffixes=("_e", "_d"))
    moved = (m["surplus_e"] - m["surplus_d"]).abs()
    lines = [f"INFO  excluded managers' picks count in every calculation, hidden from view: "
             f"{int(e['hidden'].sum())} hidden pick(s); visible picks moving surplus: "
             f"{int((moved > 0.5).sum())} by more than 0.5, {int(((moved > 0.005) & (moved <= 0.5)).sum())} by 0.005 to 0.5"]
    who = {m_["id"]: m_["name"] for m_ in cfg.get("managers") or []}
    c = engine["draft_career_grades"].merge(dropped["draft_career_grades"], on="manager_key", suffixes=("_e", "_d"))
    c = c[c["rank_e"].notna() & (c["rank_e"] != c["rank_d"])]
    if len(c):
        lines.append("      career rank changes from this rule: " + ", ".join(
            f"{who.get(r.manager_key, r.manager_key)} {r.rank_d} -> {r.rank_e}" for r in c.itertuples()))
    return lines
