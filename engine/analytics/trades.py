"""Trade analysis: which trades were real, how they group, and how each side did.

Replaces the legacy relay detect_trade_reversals -> build_trade_universe ->
compute_stints / rebuild_player_stints -> compute_metrics -> compute_quad.
Verified against those scripts' outputs by engine/legacy_trades.py.

Steps:
1. trade_items: every executed player move in a trade, from and to manager
2. reversals, two passes (both from the legacy pipeline):
   a. mirror pairs: a trade whose moves are the exact reverse of another trade
      in the same season (made as a joke or in anger, then undone)
   b. netting: two or more 2-manager trades between the same pair in the same
      scoring period whose moves cancel out
3. trade_groups: trades in the same scoring period that share a player, or
   three 2-manager trades that form a complete triangle, are one multi-team
   trade; each manager's net gives and receives (a player who passes through
   cancels out)
4. metrics per side: Trade Grade, Realized Gains, Necessity, Fit
5. QUAD: the four metrics z-scored across all sides and combined

Player ids replace the legacy name matching throughout.
"""

from __future__ import annotations

import json
from collections import Counter
from itertools import combinations

import numpy as np
import pandas as pd

from engine.analytics import stints as stints_mod
from engine.analytics import weeks
from engine.normalize.moves import executed_moves

NECESSITY_ELIGIBLE = {"RB", "WR", "TE", "K", "D/ST"}
NECESSITY_SHRINKAGE_K = 3          # shrinks low-sample necessity toward 0
FLEX_SLOT = "RB/WR/TE"
QUAD_WEIGHTS = {"z_realized_gains": 0.35, "z_trade_grade": 0.30, "z_fit_score": 0.20, "z_necessity": 0.15}
LOW_STAKES_POSITIONS = {"K", "D/ST"}
LOW_STAKES_MULTIPLIER = 0.15


# ----------------------------------------------------------------- 1. items

def trade_items(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """One row per player moved in an executed trade."""
    tx = executed_moves(tables["transactions"])
    tx = tx[tx["type"].eq("TRADE_ACCEPT") & tx["item_type"].eq("TRADE")]
    owner = tables["teams"].set_index(["season", "team_id"])["manager_key"]

    def manager(col: str) -> np.ndarray:
        return owner.reindex(pd.MultiIndex.from_arrays([tx["season"], tx[col]])).to_numpy()

    # A trade's items can come from different sources (league feed, player
    # cards); take the period and time from whichever item carries them.
    by_tid = tx.groupby("transaction_id")
    period = tx["scoring_period"].fillna(by_tid["scoring_period"].transform("max"))
    proposed = tx["proposed_at_ms"].fillna(by_tid["proposed_at_ms"].transform("max"))
    if period.isna().any() or proposed.isna().any():
        bad = sorted(tx.loc[period.isna() | proposed.isna(), "transaction_id"].unique())
        raise ValueError(f"trade items with no scoring period or proposal time: {bad[:5]}")
    items = pd.DataFrame({
        "season": tx["season"].astype(int).to_numpy(),
        "scoring_period": period.astype(int).to_numpy(),
        "transaction_id": tx["transaction_id"].to_numpy(),
        "proposed_at_ms": proposed.astype("int64").to_numpy(),
        "player_id": tx["player_id"].astype(int).to_numpy(),
        "from_manager_key": manager("from_team_id"),
        "to_manager_key": manager("to_team_id"),
    })
    names = tables["player_seasons"][["season", "player_id", "player_name", "position"]]
    items = items.merge(names, on=["season", "player_id"], how="left")
    unknown = items["from_manager_key"].isna() | items["to_manager_key"].isna()
    if unknown.any():
        raise ValueError(f"trade items whose team has no owner: {sorted(items.loc[unknown, 'transaction_id'].unique())[:5]}")
    return items.sort_values(["season", "scoring_period", "proposed_at_ms", "transaction_id", "player_id"],
                             kind="stable").reset_index(drop=True)


# ------------------------------------------------------------- 2. reversals

def _moves(items: pd.DataFrame) -> dict[str, frozenset]:
    return {tid: frozenset(zip(g["player_id"], g["from_manager_key"], g["to_manager_key"]))
            for tid, g in items.groupby("transaction_id", sort=False)}


def mirror_reversals(items: pd.DataFrame) -> pd.DataFrame:
    """Pairs of trades in one season where one exactly undoes the other."""
    moves = _moves(items)
    info = items.groupby("transaction_id", sort=False).agg(
        season=("season", "first"), scoring_period=("scoring_period", "first"),
        proposed_at_ms=("proposed_at_ms", "first"))
    by_sig: dict[tuple, list[str]] = {}
    for tid, sig in moves.items():
        by_sig.setdefault((info.at[tid, "season"], sig), []).append(tid)
    pairs = []
    for tid, sig in moves.items():
        season = info.at[tid, "season"]
        reverse = frozenset((p, to, frm) for p, frm, to in sig)
        for other in by_sig.get((season, reverse), []):
            a, b = sorted([tid, other], key=lambda t: (info.at[t, "proposed_at_ms"], t))
            if tid == a:   # record each pair once, from the earlier trade
                pairs.append({"season": int(season), "original_transaction_id": a, "reversal_transaction_id": b,
                              "original_at_ms": int(info.at[a, "proposed_at_ms"]),
                              "reversal_at_ms": int(info.at[b, "proposed_at_ms"]), "reason": "mirror"})
    return pd.DataFrame(pairs, columns=["season", "original_transaction_id", "reversal_transaction_id",
                                        "original_at_ms", "reversal_at_ms", "reason"])


def netting_reversals(items: pd.DataFrame) -> set[str]:
    """2-manager trades between the same pair in one scoring period whose
    moves cancel out: every player ends with the manager who first gave him up."""
    out: set[str] = set()
    for _, period in items.groupby(["season", "scoring_period"], sort=True):
        pairs: dict[frozenset, list[str]] = {}
        for tid, g in period.groupby("transaction_id", sort=False):
            mgrs = frozenset(set(g["from_manager_key"]) | set(g["to_manager_key"]))
            if len(mgrs) == 2:
                pairs.setdefault(mgrs, []).append(tid)
        for tids in pairs.values():
            if len(tids) < 2:
                continue
            sub = period[period["transaction_id"].isin(tids)].sort_values("proposed_at_ms", kind="stable")
            first_from: dict[int, str] = {}
            last_to: dict[int, str] = {}
            for p, frm, to in zip(sub["player_id"], sub["from_manager_key"], sub["to_manager_key"]):
                first_from.setdefault(p, frm)
                last_to[p] = to
            if first_from and all(first_from[p] == last_to[p] for p in first_from):
                out.update(tids)
    return out


def real_trade_items(items: pd.DataFrame, remove_mirrors: bool = True) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(items with both kinds of reversal removed, log of what was removed).
    remove_mirrors=False skips the mirror pass (the legacy universe did)."""
    mirror = mirror_reversals(items if remove_mirrors else items.iloc[0:0])
    mirrored = set(mirror["original_transaction_id"]) | set(mirror["reversal_transaction_id"])
    after_mirror = items[~items["transaction_id"].isin(mirrored)]
    netted = netting_reversals(after_mirror)
    info = items.drop_duplicates("transaction_id").set_index("transaction_id")
    net_log = pd.DataFrame([{"season": int(info.at[t, "season"]), "original_transaction_id": t,
                             "reversal_transaction_id": None, "original_at_ms": int(info.at[t, "proposed_at_ms"]),
                             "reversal_at_ms": None, "reason": "netting"} for t in sorted(netted)],
                           columns=mirror.columns)
    log = pd.concat([mirror, net_log], ignore_index=True) if len(net_log) else mirror
    kept = after_mirror[~after_mirror["transaction_id"].isin(netted)].reset_index(drop=True)
    return kept, log


# ---------------------------------------------------------------- 3. groups

def _group_period(period: pd.DataFrame) -> list[list[str]]:
    tids = list(dict.fromkeys(period["transaction_id"]))
    players = {t: set(g["player_id"]) for t, g in period.groupby("transaction_id", sort=False)}
    mgrs = {t: frozenset(set(g["from_manager_key"]) | set(g["to_manager_key"]))
            for t, g in period.groupby("transaction_id", sort=False)}
    parent = {t: t for t in tids}

    def find(x: str) -> str:
        while parent[x] != x:
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for t1, t2 in combinations(tids, 2):            # shared player
        if players[t1] & players[t2]:
            union(t1, t2)
    two = [t for t in tids if len(mgrs[t]) == 2]     # complete triangle of 2-manager trades
    for t1, t2 in combinations(two, 2):
        for t3 in two:
            if t3 in (t1, t2):
                continue
            all_mgrs = mgrs[t1] | mgrs[t2] | mgrs[t3]
            if len(all_mgrs) != 3:
                continue
            if set(combinations(sorted(all_mgrs), 2)) == {tuple(sorted(mgrs[t])) for t in (t1, t2, t3)}:
                union(t1, t2)
                union(t2, t3)
    groups: dict[str, list[str]] = {}
    for t in tids:
        groups.setdefault(find(t), []).append(t)
    return list(groups.values())


def trade_sides(items: pd.DataFrame, net_by: str = "count") -> pd.DataFrame:
    """One row per (trade group, manager) with that manager's net gives and
    receives. Group ids run in time order within the analyzed seasons.

    net_by="count" nets each player by how many times the manager received
    and gave him, so a player who changes hands several times lands with the
    right manager. net_by="set" reproduces the legacy output, which netted by
    set difference and dropped any player the manager both gave and received.
    """
    if net_by not in ("count", "set"):
        raise ValueError(f"net_by must be 'count' or 'set', not {net_by!r}")
    groups = []
    for (season, sp), period in items.groupby(["season", "scoring_period"], sort=True):
        for tids in _group_period(period):
            sub = period[period["transaction_id"].isin(tids)]
            groups.append((int(season), int(sp), int(sub["proposed_at_ms"].min()), sorted(tids), sub))
    groups.sort(key=lambda g: (g[0], g[1], g[2], g[3]))

    rows = []
    for gid, (season, sp, earliest, tids, sub) in enumerate(groups, start=1):
        all_mgrs = set(sub["from_manager_key"]) | set(sub["to_manager_key"])
        for mgr in sorted(all_mgrs):
            gave = Counter(sub.loc[sub["from_manager_key"] == mgr, "player_id"])
            got = Counter(sub.loc[sub["to_manager_key"] == mgr, "player_id"])
            if net_by == "count":
                net = {p: got.get(p, 0) - gave.get(p, 0) for p in set(gave) | set(got)}
                net_got = sorted(int(p) for p, n in net.items() if n > 0)
                net_gave = sorted(int(p) for p, n in net.items() if n < 0)
            else:
                net_got = sorted(int(p) for p in set(got) - set(gave))
                net_gave = sorted(int(p) for p in set(gave) - set(got))
            if not net_got and not net_gave:
                continue   # pure pass-through
            rows.append({
                "group_id": gid, "season": season, "scoring_period": sp, "manager_key": mgr,
                "num_transactions_in_group": len(tids), "num_managers_in_group": len(all_mgrs),
                "transaction_ids": json.dumps(tids),
                "gave_player_ids": json.dumps(net_gave), "got_player_ids": json.dumps(net_got),
                "earliest_ts": earliest,
            })
    cols = ["group_id", "season", "scoring_period", "manager_key", "num_transactions_in_group",
            "num_managers_in_group", "transaction_ids", "gave_player_ids", "got_player_ids", "earliest_ts"]
    return pd.DataFrame(rows, columns=cols)


# --------------------------------------------------------------- 4. metrics

def trade_stints(sides: pd.DataFrame, z_lineups: pd.DataFrame, all_lineups: pd.DataFrame,
                 ir_counts_as_started: bool = False) -> pd.DataFrame:
    """Stint of every player a manager received, from the trade week on."""
    acq = [{"group_id": r.group_id, "season": r.season, "scoring_period": r.scoring_period,
            "manager_key": r.manager_key, "player_id": pid, "start_week": r.scoring_period}
           for r in sides.itertuples() for pid in json.loads(r.got_player_ids)]
    acq = pd.DataFrame(acq, columns=["group_id", "season", "scoring_period", "manager_key", "player_id", "start_week"])
    return stints_mod.stints(acq, z_lineups, all_lineups, ir_counts_as_started).drop(columns="start_week")


def _necessity(season: int, manager: str, player_id: int, start: int, weeks_rostered: int,
               roster: dict, weight: dict) -> tuple[float, int]:
    """Acquired player's points minus the best pre-existing bench alternative
    (same position, or any eligible position when he played the flex), per week."""
    if weeks_rostered == 0:
        return 0.0, 0
    before = roster.get((season, manager, start - 1))
    pre_ids = set() if before is None else set(
        before.loc[before["position"].isin(NECESSITY_ELIGIBLE), "player_id"]) - {player_id}
    total, n = 0.0, 0
    for wk in range(start, start + weeks_rostered):   # legacy: assumes consecutive weeks
        week = roster.get((season, manager, wk))
        if week is None:
            continue
        acq = week[week["player_id"] == player_id]
        if not len(acq):
            continue
        slot, pos, pts = acq["slot"].iloc[0], acq["position"].iloc[0], acq["points"].iloc[0]
        if pos not in NECESSITY_ELIGIBLE:
            continue
        bench = week[week["player_id"].isin(pre_ids) & week["slot"].eq(stints_mod.BENCH)]
        pool = bench if slot == FLEX_SLOT else bench[bench["position"] == pos]
        if not len(pool):
            continue
        best = pool.loc[pool["points"].idxmax(), "points"]
        total += (pts - best) * weight.get((season, wk), weeks.REGULAR_WEIGHT)
        n += 1
    return total, n


def _fit(season: int, manager: str, positions: set, start: int, by_pos: dict) -> float:
    """Average weekly z at the affected positions after the trade minus before."""
    if not positions or start <= 1:
        return 0.0
    scores = []
    for pos in positions:
        rows = by_pos.get((season, manager, pos))
        if rows is None:
            continue
        before, after = rows[rows["week"] < start], rows[rows["week"] >= start]
        if not len(before) or not len(after):
            continue
        b = before.groupby("week")["weighted_z"].mean().mean()
        a = after.groupby("week")["weighted_z"].mean().mean()
        if pd.notna(b) and pd.notna(a):
            scores.append(a - b)
    return float(np.mean(scores)) if scores else 0.0


def side_metrics(sides: pd.DataFrame, stint_rows: pd.DataFrame, z_lineups: pd.DataFrame,
                 weights: pd.DataFrame) -> pd.DataFrame:
    """Trade Grade, Realized Gains, Necessity, and Fit for every side.

    A player's value is his stint with whoever received him in the group, so
    what a manager gave up is measured on the receiving manager's roster.
    """
    stint = stint_rows.set_index(["group_id", "player_id"])[["total_z", "realized_z", "weeks_rostered", "position"]]
    stint = stint[~stint.index.duplicated()].to_dict("index")
    roster = {k: g for k, g in z_lineups.groupby(["season", "manager_key", "week"])}
    by_pos = {k: g for k, g in z_lineups.groupby(["season", "manager_key", "position"])}
    weight = {(s, w): v for s, w, v in weights[["season", "week", "week_weight"]].itertuples(index=False)}

    def total(gid: int, ids: list, col: str) -> float:
        return sum((stint.get((gid, p)) or {}).get(col, 0) or 0 for p in ids)

    rows = []
    for r in sides.itertuples():
        got, gave = json.loads(r.got_player_ids), json.loads(r.gave_player_ids)
        nec_total, nec_weeks, positions = 0.0, 0, set()
        for pid in got:
            info = stint.get((r.group_id, pid))
            if not info or info["weeks_rostered"] == 0:
                continue
            positions.add(info["position"])
            d, n = _necessity(r.season, r.manager_key, pid, r.scoring_period, info["weeks_rostered"], roster, weight)
            nec_total += d
            nec_weeks += n
        rows.append({
            "group_id": r.group_id, "manager_key": r.manager_key,
            "trade_grade": total(r.group_id, got, "total_z") - total(r.group_id, gave, "total_z"),
            "realized_gains": total(r.group_id, got, "realized_z") - total(r.group_id, gave, "realized_z"),
            "necessity_raw": nec_total, "necessity_weeks": nec_weeks,
            "necessity_per_week": nec_total / (nec_weeks + NECESSITY_SHRINKAGE_K) if nec_weeks > 0 else np.nan,
            "fit_score": _fit(r.season, r.manager_key, positions, r.scoring_period, by_pos),
        })
    return sides.merge(pd.DataFrame(rows, columns=["group_id", "manager_key", "trade_grade", "realized_gains",
                                                   "necessity_raw", "necessity_weeks", "necessity_per_week",
                                                   "fit_score"]),
                       on=["group_id", "manager_key"])


# ------------------------------------------------------------------ 5. QUAD

def _zscore(s: pd.Series) -> pd.Series:
    return (s - s.mean()) / s.std()


def is_low_stakes(got_positions: list, gave_positions: list) -> bool:
    """One side of the exchange was nothing but kickers and D/STs."""
    def only_k_dst(ps: list) -> bool:
        return len(ps) > 0 and all(p in LOW_STAKES_POSITIONS for p in ps)
    return only_k_dst(got_positions) or only_k_dst(gave_positions)


def quad(metrics: pd.DataFrame) -> pd.DataFrame:
    """Z-score each metric across every side, combine, re-standardize, and
    dampen low-stakes sides. Expects a low_stakes column."""
    out = metrics.copy()
    out["z_trade_grade"] = _zscore(out["trade_grade"])
    out["z_realized_gains"] = _zscore(out["realized_gains"])
    out["z_fit_score"] = _zscore(out["fit_score"])
    out["z_necessity"] = _zscore(out["necessity_per_week"]).fillna(0)   # no comparison -> average
    out["quad_raw"] = sum(out[k] * w for k, w in QUAD_WEIGHTS.items())
    out["QUAD_unadjusted"] = _zscore(out["quad_raw"])
    out["QUAD"] = np.where(out["low_stakes"], out["QUAD_unadjusted"] * LOW_STAKES_MULTIPLIER, out["QUAD_unadjusted"])
    return out


# ---------------------------------------------------------------- pipeline

def analyze_trades(tables: dict[str, pd.DataFrame], seasons: list[int] | None = None,
                   legacy_mode: bool = False) -> dict[str, pd.DataFrame]:
    """Every trade table, for the given seasons (default: all). QUAD is scored
    against all sides in those seasons.

    Points are ESPN's raw points (negative D/ST scores stay negative; the
    league never adopted a floor).

    legacy_mode=True reproduces the legacy trade_universe and metrics_final
    exactly, for verification only. The legacy pipeline differs from the
    engine in four ways, all reversed in normal mode:
    - trades were grouped before mirror reversals were removed
    - net gives and receives used set netting (drops players who bounced)
    - the position baseline counted IR players
    - IR weeks counted as started in Realized Gains
    """
    if seasons is not None:
        tables = {k: (v[v["season"].isin(seasons)] if "season" in v.columns else v) for k, v in tables.items()}
    lineups = weeks.bracket_lineups(tables)
    baseline = weeks.position_baseline(lineups, include_ir=legacy_mode)
    weights = weeks.week_weights(tables)
    forfeits = weeks.forfeited_weeks(tables)
    z_all = weeks.with_z(lineups, baseline, weights)
    z_play = weeks.drop_forfeits(z_all, forfeits)

    items = trade_items(tables)
    kept, reversals = real_trade_items(items, remove_mirrors=not legacy_mode)
    sides = trade_sides(kept, net_by="set" if legacy_mode else "count")
    stint_rows = trade_stints(sides, z_play, z_all, ir_counts_as_started=legacy_mode)
    metrics = side_metrics(sides, stint_rows, z_play, weights)

    pos = tables["player_seasons"].set_index(["season", "player_id"])["position"].to_dict()
    metrics["low_stakes"] = [
        is_low_stakes([pos.get((s, p), "") for p in json.loads(got)], [pos.get((s, p), "") for p in json.loads(gave)])
        for s, got, gave in zip(metrics["season"], metrics["got_player_ids"], metrics["gave_player_ids"])]
    metrics = quad(metrics)
    return {
        "position_baseline": baseline,
        "week_weights": weights,
        "forfeited_weeks": forfeits,
        "trade_items": items,
        "trade_reversals": reversals,
        "trade_sides": sides,
        "trade_stints": stint_rows,
        "trade_metrics": metrics,
    }
