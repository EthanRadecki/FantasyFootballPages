"""Compare the trades analysis with the legacy trade pipeline's outputs.

Golden files (engine/tests/golden/trades/), all from the legacy pipeline:
    trades_mapped.csv.gz         every trade item (input to detect_trade_reversals)
    trades_mapped_clean.csv.gz   after mirror-reversal removal
    trade_universe.csv.gz        trade groups and each manager's net gives/receives
    position_baseline.csv.gz     weekly position mean and standard deviation
    player_stints_fixed.csv.gz   stint of every received player
    metrics_final.csv.gz         per-side metrics and QUAD
    lineup_efficiency.csv.gz     used here only for its Forfeited_Lineup flag

The legacy trade_universe (and so everything after it) was built by an
earlier version of build_trade_universe than the one saved in engine/_legacy:
- it grouped the raw trades_mapped.csv, before mirror reversals were removed
- it netted each manager's gives and receives by set difference, so a player
  who changed hands more than once in a group vanished from both sides
  (2020 week 11 Malich/Serafin/Slansky/Bileydi, 2020 week 13 Castaldo/Radecki)
The saved script fixes the netting (count-based) and the separate
detect_trade_reversals step removes mirror pairs. The engine keeps both fixes.
Two league decisions (2026-09-29) also differ from legacy: the position
baseline leaves out IR players, and IR weeks do not count as started.
Verification therefore runs the engine twice: in legacy mode, which must
reproduce every legacy file exactly, and in normal mode, whose differences
from legacy mode are listed (sides changed, QUAD shift) for review.

Legacy group ids follow the legacy file order; groups are matched on
(season, scoring period, earliest proposal time), which is unique per group.
"""

from __future__ import annotations

import json

import pandas as pd

from engine.analytics import trades as trades_mod
from engine.legacy import Comparison, compare, name_to_key, resolve_names

GROUP_KEYS = ["season", "scoring_period", "earliest_ts"]


def _ids(s: str) -> str:
    return json.dumps(sorted(int(x) for x in json.loads(s)))


def legacy_positions(tables: dict[str, pd.DataFrame], rosters: pd.DataFrame, cfg: dict) -> tuple[dict, int]:
    """Tables with the legacy position put back on lineup rows where the legacy
    rosters file used a player's position from another season (the known
    difference in check_rosters). Lets the trade checks run on the exact inputs
    the legacy pipeline saw. Returns (tables, rows changed)."""
    lookup = name_to_key(cfg)
    leg = pd.DataFrame({
        "season": rosters["Season"].astype(int), "week": rosters["Week"].astype(int),
        "manager_key": resolve_names(rosters["Manager"], lookup),
        "player_id": rosters["Player_ID"].astype(int), "legacy_position": rosters["Position"],
    })
    lu = tables["lineups"].merge(leg, on=["season", "week", "manager_key", "player_id"], how="left")
    other = tables["lineups"][["player_id", "season", "position"]].drop_duplicates()
    other = other.rename(columns={"season": "other_season", "position": "legacy_position"})
    cand = lu[lu["legacy_position"].notna() & (lu["legacy_position"] != lu["position"])]
    ok = cand.merge(other, on=["player_id", "legacy_position"])
    ok = ok[ok["other_season"] != ok["season"]]
    keys = ["season", "week", "manager_key", "player_id"]
    flag = lu[keys].merge(ok[keys].drop_duplicates().assign(_x=True), on=keys, how="left")["_x"].notna().to_numpy()
    lu.loc[flag, "position"] = lu.loc[flag, "legacy_position"]
    out = dict(tables)
    out["lineups"] = lu.drop(columns="legacy_position")
    return out, int(flag.sum())


def _legacy_sides(universe: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    return pd.DataFrame({
        "legacy_group_id": universe["group_id"].astype(int),
        "season": universe["season"].astype(int),
        "scoring_period": universe["scoring_period"].astype(int),
        "earliest_ts": universe["earliest_ts"].astype("int64"),
        "manager_key": resolve_names(universe["manager"], name_to_key(cfg)),
        "num_transactions_in_group": universe["num_transactions_in_group"].astype(int),
        "num_managers_in_group": universe["num_managers_in_group"].astype(int),
        "gave_player_ids": universe["gave_player_ids"].map(_ids),
        "got_player_ids": universe["got_player_ids"].map(_ids),
    })


def check_forfeits(analysis: dict, lineup_eff: pd.DataFrame, cfg: dict) -> Comparison:
    f = lineup_eff[lineup_eff["Forfeited_Lineup"].astype(bool)]
    exp = pd.DataFrame({"season": f["Season"].astype(int), "week": f["Week"].astype(int),
                        "manager_key": resolve_names(f["Manager"], name_to_key(cfg)), "forfeited": True})
    covered = pd.DataFrame({"season": lineup_eff["Season"].astype(int), "week": lineup_eff["Week"].astype(int),
                            "manager_key": resolve_names(lineup_eff["Manager"], name_to_key(cfg))})
    act = analysis["forfeited_weeks"].merge(covered, on=["season", "week", "manager_key"]).assign(forfeited=True)
    return compare("forfeited lineups vs lineup_efficiency.csv", exp, act,
                   keys=["season", "week", "manager_key"], values=["forfeited"])


def check_week_weights(analysis: dict, rosters: pd.DataFrame) -> Comparison:
    """Legacy playoff_weights.build_week_weight_lookup, from the rosters' week labels."""
    roles = {4: [1.15, 1.3, 1.6, 2.0], 3: [1.3, 1.6, 2.0]}
    rows = []
    w = rosters[["Season", "Week", "Week_Label"]].drop_duplicates()
    for season, g in w.groupby("Season"):
        rounds = sorted(g.loc[g["Week_Label"].str.contains("Playoff", na=False), "Week_Label"].unique(),
                        key=lambda x: int(x.split()[-1]))
        weights = dict(zip(rounds, roles.get(len(rounds), [2.0] * len(rounds))))
        for _, r in g.iterrows():
            rows.append({"season": int(season), "week": int(r["Week"]), "week_weight": weights.get(r["Week_Label"], 1.0)})
    exp = pd.DataFrame(rows)
    act = analysis["week_weights"].merge(exp[["season", "week"]], on=["season", "week"])
    return compare("playoff week weights vs playoff_weights.py", exp, act,
                   keys=["season", "week"], values=["week_weight"], tolerance=1e-9)


def check_position_baseline(analysis: dict, legacy: pd.DataFrame) -> Comparison:
    exp = legacy.rename(columns={"Season": "season", "Week": "week", "Position": "position"})
    return compare("position baseline vs position_baseline.csv", exp, analysis["position_baseline"],
                   keys=["season", "week", "position"], values=["pos_mean", "pos_std"], tolerance=1e-9)


def check_trade_items(analysis: dict, legacy: pd.DataFrame, cfg: dict) -> Comparison:
    lookup = name_to_key(cfg)
    exp = pd.DataFrame({
        "transaction_id": legacy["Transaction_ID"], "player_id": legacy["Player_ID"].astype(int),
        "season": legacy["Season"].astype(int), "scoring_period": legacy["Scoring_Period"].astype(int),
        "proposed_at_ms": legacy["Proposed_Date_Unix_ms"].astype("int64"),
        "from_manager_key": resolve_names(legacy["From_Manager"], lookup),
        "to_manager_key": resolve_names(legacy["To_Manager"], lookup),
    })
    return compare("trade items vs trades_mapped.csv", exp, analysis["trade_items"],
                   keys=["transaction_id", "player_id"],
                   values=["season", "scoring_period", "proposed_at_ms", "from_manager_key", "to_manager_key"],
                   tolerance=0)


def check_mirror_reversals(analysis: dict, legacy_clean: pd.DataFrame) -> Comparison:
    """Items left after mirror-pair removal vs trades_mapped_clean.csv."""
    items = analysis["trade_items"]
    rev = trades_mod.mirror_reversals(items)
    mirrored = set(rev["original_transaction_id"]) | set(rev["reversal_transaction_id"])
    act = items[~items["transaction_id"].isin(mirrored)]
    exp = pd.DataFrame({"transaction_id": legacy_clean["Transaction_ID"],
                        "player_id": legacy_clean["Player_ID"].astype(int),
                        "season": legacy_clean["Season"].astype(int)})
    return compare("mirror reversals vs trades_mapped_clean.csv", exp, act,
                   keys=["transaction_id", "player_id"], values=["season"])


def check_trade_sides(analysis: dict, universe: pd.DataFrame, cfg: dict) -> Comparison:
    return compare("trade groups vs trade_universe.csv", _legacy_sides(universe, cfg), analysis["trade_sides"],
                   keys=GROUP_KEYS + ["manager_key"],
                   values=["num_transactions_in_group", "num_managers_in_group", "gave_player_ids", "got_player_ids"])


def _group_map(analysis: dict, universe: pd.DataFrame) -> pd.DataFrame:
    """legacy group_id -> engine group_id, through (season, period, earliest time)."""
    leg = universe.groupby("group_id").agg(season=("season", "first"), scoring_period=("scoring_period", "first"),
                                           earliest_ts=("earliest_ts", "first")).reset_index()
    leg = leg.rename(columns={"group_id": "legacy_group_id"})
    eng = analysis["trade_sides"].drop_duplicates("group_id")[["group_id"] + GROUP_KEYS]
    return leg.astype({"season": int, "scoring_period": int, "earliest_ts": "int64"}).merge(eng, on=GROUP_KEYS, how="left")


def check_trade_stints(analysis: dict, legacy: pd.DataFrame, universe: pd.DataFrame, cfg: dict) -> Comparison:
    gmap = _group_map(analysis, universe)
    exp = legacy.rename(columns={"group_id": "legacy_group_id"}).merge(
        gmap[["legacy_group_id"] + GROUP_KEYS], on="legacy_group_id", suffixes=("_x", ""))
    exp = pd.DataFrame({
        **{k: exp[k] for k in GROUP_KEYS},
        "manager_key": resolve_names(exp["receiving_manager"], name_to_key(cfg)),
        "player_id": exp["player_id"].astype(int), "position": exp["position"].fillna(""),
        "weeks_rostered": exp["weeks_rostered"].astype(int),
        "total_z": exp["total_z"], "realized_z": exp["realized_z"],
    })
    act = analysis["trade_stints"].merge(analysis["trade_sides"].drop_duplicates("group_id")[["group_id", "earliest_ts"]],
                                         on="group_id")
    act = act.assign(position=act["position"].fillna(""))
    return compare("trade stints vs player_stints_fixed.csv", exp, act, keys=GROUP_KEYS + ["manager_key", "player_id"],
                   values=["position", "weeks_rostered", "total_z", "realized_z"], tolerance=1e-9)


RAW_METRICS = ["trade_grade", "realized_gains", "necessity_raw", "necessity_weeks", "necessity_per_week", "fit_score"]
QUAD_COLS = ["z_trade_grade", "z_realized_gains", "z_fit_score", "z_necessity", "quad_raw", "QUAD_unadjusted", "QUAD"]
NAN = -999999.0


def _metrics_frame(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    out = df.copy()
    for c in cols:
        out[c] = out[c].astype(float).fillna(NAN)   # NaN must match NaN, not slip past the tolerance
    return out


def check_trade_metrics(analysis: dict, legacy: pd.DataFrame, universe: pd.DataFrame, cfg: dict) -> Comparison:
    gmap = _group_map(analysis, universe)
    exp = legacy.rename(columns={"group_id": "legacy_group_id"}).merge(
        gmap[["legacy_group_id"] + GROUP_KEYS], on="legacy_group_id", suffixes=("_x", ""))
    exp = exp.assign(manager_key=resolve_names(exp["manager"], name_to_key(cfg)))
    exp = _metrics_frame(exp, RAW_METRICS)
    act = _metrics_frame(analysis["trade_metrics"], RAW_METRICS + QUAD_COLS)
    exp = _metrics_frame(exp, QUAD_COLS)
    return compare("trade metrics vs metrics_final.csv", exp, act, keys=GROUP_KEYS + ["manager_key"],
                   values=RAW_METRICS + ["low_stakes"] + QUAD_COLS, tolerance=1e-9)


def check_quad_math(legacy: pd.DataFrame) -> Comparison:
    """The engine's QUAD step, fed the legacy per-side metrics, must reproduce
    the legacy z-scores and QUAD exactly."""
    inputs = legacy[["group_id", "manager"] + RAW_METRICS + ["low_stakes"]].copy()
    inputs["low_stakes"] = inputs["low_stakes"].astype(bool)
    act = _metrics_frame(trades_mod.quad(inputs), QUAD_COLS)
    exp = _metrics_frame(legacy, QUAD_COLS)
    return compare("QUAD math on legacy metrics vs metrics_final.csv", exp, act,
                   keys=["group_id", "manager"], values=QUAD_COLS, tolerance=1e-9)


def explorer_frame(nodes: list[dict], lookup: dict) -> pd.DataFrame:
    rows = []
    for n in nodes:
        for m in n["managers"]:
            rows.append({"legacy_group_id": n["gid"], "season": n["season"], "scoring_period": n["sp"],
                         "multi": n["multi"], "positions": json.dumps(sorted(n["positions"])),
                         "manager_key": lookup[m["m"].strip().lower()], "got": json.dumps(m["got"]),
                         "gave": json.dumps(m["gave"]), "tg": m["tg"], "rg": m["rg"], "fit": m["fit"],
                         "nec": m["nec"], "quad": m["quad"]})
    return pd.DataFrame(rows)


EXPLORER_VALUES = ["multi", "positions", "got", "gave", "tg", "rg", "fit", "nec", "quad"]


def check_trade_explorer(tables: dict, analysis: dict, legacy_nodes: list[dict], universe: pd.DataFrame,
                         cfg: dict) -> Comparison:
    """The site's trade_explorer_data.js (build_trade_explorer_data.py) from the
    legacy-mode metrics. Known differences, by pattern:
    - a player ESPN has renamed since (same player id, e.g. Will/William Fuller V)
    - a group's position list where the legacy position is one ESPN gave that
      player in another season (Taysom Hill: QB then, TE in 2023)"""
    lookup = name_to_key(cfg)
    gmap = _group_map(analysis, universe)
    exp = explorer_frame(legacy_nodes, lookup).merge(gmap[["legacy_group_id", "group_id"]], on="legacy_group_id")
    exp = exp.drop(columns=["legacy_group_id"])
    act = pd.DataFrame({"group_id": [], "manager_key": []})
    for n in trades_mod.explorer_nodes(analysis["trade_explorer"]):
        for m in n["managers"]:
            act = pd.concat([act, pd.DataFrame([{
                "group_id": n["gid"], "season": n["season"], "scoring_period": n["sp"], "multi": n["multi"],
                "positions": json.dumps(sorted(n["positions"])), "manager_key": m["m"], "got": json.dumps(m["got"]),
                "gave": json.dumps(m["gave"]), "tg": m["tg"], "rg": m["rg"], "fit": m["fit"], "nec": m["nec"],
                "quad": m["quad"]}])], ignore_index=True)
    act["group_id"] = act["group_id"].astype(int)

    sides = analysis["trade_explorer"].set_index(["group_id", "manager_key"])
    ids = analysis["trade_sides"].set_index(["group_id", "manager_key"])
    ever = tables["player_seasons"].groupby("player_id")["position"].agg(set).to_dict()
    known = []
    both = exp.merge(act, on=["group_id", "manager_key"], suffixes=("_l", "_e"))
    for r in both.itertuples():
        for col in ("got", "gave"):
            a, b = sorted(json.loads(getattr(r, f"{col}_l"))), sorted(json.loads(getattr(r, f"{col}_e")))
            if a != b and len(a) == len(b):
                known.append({"group_id": r.group_id, "manager_key": r.manager_key, "column": col,
                              "reason": "ESPN renamed the player since the trade (same player id)"})
        pl, pe = set(json.loads(r.positions_l)), set(json.loads(r.positions_e))
        if pl != pe:
            moved = [p for side in analysis["trade_sides"][analysis["trade_sides"]["group_id"] == r.group_id]["got_player_ids"]
                     for p in json.loads(side)]
            if all(any(pos in ever.get(p, set()) for p in moved) for pos in pl - pe):
                known.append({"group_id": r.group_id, "manager_key": r.manager_key, "column": "positions",
                              "reason": "legacy used a position ESPN gave the player another season"})
    exp = _metrics_frame(exp, ["tg", "rg", "fit", "nec", "quad"])
    act = _metrics_frame(act, ["tg", "rg", "fit", "nec", "quad"])
    for frame in (exp, act):      # the order players are listed in is not compared
        for col in ("got", "gave"):
            frame[col] = frame[col].map(lambda v: json.dumps(sorted(json.loads(v))))
    return compare("trade explorer vs trade_explorer_data.js", exp, act, keys=["group_id", "manager_key"],
                   values=EXPLORER_VALUES, tolerance=1e-9, known=pd.DataFrame(known))


def engine_vs_legacy_mode(engine: dict, legacy: dict, cfg: dict) -> list[str]:
    """What the engine's two fixes change relative to legacy mode."""
    e, l = engine["trade_metrics"], legacy["trade_metrics"]
    names = engine["trade_items"].drop_duplicates("player_id").set_index("player_id")["player_name"].to_dict()
    who = {m["id"]: m["name"] for m in cfg.get("managers") or []}
    key = ["season", "scoring_period", "manager_key"]

    def players(df: pd.DataFrame) -> pd.DataFrame:
        return df.groupby(key).agg(
            gave=("gave_player_ids", lambda x: set().union(*(json.loads(v) for v in x))),
            got=("got_player_ids", lambda x: set().union(*(json.loads(v) for v in x)))).reset_index()

    m = players(e).merge(players(l), on=key, how="outer", suffixes=("_e", "_l"))
    for c in ("gave_e", "got_e", "gave_l", "got_l"):
        m[c] = m[c].apply(lambda v: v if isinstance(v, set) else set())
    changed = m[(m["gave_e"] != m["gave_l"]) | (m["got_e"] != m["got_l"])]
    n_mirror = int((engine["trade_reversals"]["reason"] == "mirror").sum())
    lines = [f"INFO  engine vs legacy mode: {n_mirror} mirror reversal pair(s) removed before grouping, "
             f"{len(e)} trade sides (legacy {len(l)}), {len(changed)} side(s) with different players (count netting); "
             "baseline without IR, IR weeks not started"]

    def fmt(ids: set) -> str:
        return ", ".join(sorted(str(names.get(i, i)) for i in ids)) or "nothing"

    for _, r in changed.iterrows():
        adds = []
        if r["gave_e"] != r["gave_l"]:
            adds.append(f"also gave {fmt(r['gave_e'] - r['gave_l'])}" if r["gave_e"] > r["gave_l"]
                        else f"gave {fmt(r['gave_l'])} -> {fmt(r['gave_e'])}")
        if r["got_e"] != r["got_l"]:
            adds.append(f"also got {fmt(r['got_e'] - r['got_l'])}" if r["got_e"] > r["got_l"]
                        else f"got {fmt(r['got_l'])} -> {fmt(r['got_e'])}")
        lines.append(f"      {r['season']} week {r['scoring_period']} {who.get(r['manager_key'], r['manager_key'])}: "
                     + "; ".join(adds))
    q = e.merge(l, on=key + ["got_player_ids", "gave_player_ids"], suffixes=("_e", "_l"))
    d = (q["QUAD_e"] - q["QUAD_l"]).abs()
    lines.append(f"INFO  QUAD change on the {len(q)} sides with the same players: max {d.max():.4f}, "
                 f"mean {d.mean():.4f}")
    return lines


def verify_trades(tables: dict[str, pd.DataFrame], golden: dict[str, pd.DataFrame], cfg: dict) -> tuple[list, list[str]]:
    """Run the trades analysis on the legacy inputs and compare every stage.
    Returns (comparisons, info lines)."""
    seasons = sorted(golden["metrics_final"]["season"].unique().tolist())
    adjusted, n_pos = legacy_positions(tables, golden["weekly_rosters_bracket_only"], cfg)
    legacy_run = trades_mod.analyze_trades(adjusted, seasons=seasons, legacy_mode=True)
    engine_run = trades_mod.analyze_trades(adjusted, seasons=seasons)
    info = [f"INFO  inputs: seasons {seasons[0]}-{seasons[-1]}; {n_pos} lineup row(s) use the legacy position "
            "(legacy used a later-season position, see the lineups check); trades run in legacy mode"]
    results = [
        check_forfeits(legacy_run, golden["lineup_efficiency"], cfg),
        check_week_weights(legacy_run, golden["weekly_rosters_bracket_only"]),
        check_position_baseline(legacy_run, golden["position_baseline"]),
        check_trade_items(legacy_run, golden["trades_mapped"], cfg),
        check_mirror_reversals(legacy_run, golden["trades_mapped_clean"]),
        check_trade_sides(legacy_run, golden["trade_universe"], cfg),
        check_trade_stints(legacy_run, golden["player_stints_fixed"], golden["trade_universe"], cfg),
        check_trade_metrics(legacy_run, golden["metrics_final"], golden["trade_universe"], cfg),
        check_quad_math(golden["metrics_final"]),
    ]
    if "trade_explorer_data" in golden:
        results.append(check_trade_explorer(adjusted, legacy_run, golden["trade_explorer_data"],
                                            golden["trade_universe"], cfg))
    info += engine_vs_legacy_mode(engine_run, legacy_run, cfg)
    if "trade_explorer" in engine_run:
        ne, nl = engine_run["trade_explorer"]["group_id"].nunique(), legacy_run["trade_explorer"]["group_id"].nunique()
        info.append(f"INFO  trade explorer: {ne} trades in engine mode ({nl} in legacy mode); the metric "
                    "changes above carry over to each trade's node")
    return results, info
