"""Lineup decisions: actual vs best possible lineup, missed wins, blunders.

Replaces the legacy generate_lineup_efficiency.py and generate_blunder_rosters.py.

- The starting slots come from the data (the most common set of started slots
  in a season), not a hardcoded lineup, so any league shape works.
- The best possible lineup fills fixed slots first (best players at that
  position), then flex slots from what is left. IR players are never eligible.
- Only counted games (finished regular season and winners-bracket games).
- A forfeited week (0 points in a finished game) keeps its missed win but is
  left out of efficiency averages. So is a neglected lineup: 2 or more
  starting slots left empty while an active (non-zero) player who could fill
  one of them sat on the bench (`excluded` = forfeited or neglected).
- Bench depth (lineup-efficiency.html): each bench player's points minus the
  league's average bench points at his position that week (every counted
  team's bench, his own included), summed over the bench. legacy_mode leaves
  excluded managers' benches out of that average, as the page did; the engine
  counts them (they are only hidden).
"""

from __future__ import annotations

from collections import Counter

import pandas as pd

from engine.analytics import weeks

IR_SLOT = "IR"
NON_STARTING = {"BE", "IR"}


def lineup_slots(lineups: pd.DataFrame) -> dict[int, list[str]]:
    """season -> the starting slots most teams used, e.g. QB, RB, RB, WR, ..."""
    started = lineups[lineups["started"]]
    out = {}
    for season, g in started.groupby("season"):
        shapes = Counter(tuple(sorted(team["slot"])) for _, team in g.groupby(["week", "team_id"]))
        out[int(season)] = list(shapes.most_common(1)[0][0])
    return out


def eligible(slot: str) -> set[str]:
    """Positions a slot accepts: 'RB/WR/TE' -> {RB, WR, TE}; 'D/ST' -> {D/ST}."""
    from engine.normalize.espn import POSITIONS

    return {slot} if slot in POSITIONS.values() else set(slot.split("/"))


def best_lineup(pool: pd.DataFrame, slots: list[str], points: str = "points") -> list[tuple[str, object]]:
    """Fill each slot from `pool` (columns position and `points`): fixed slots
    first, then flex slots (fewest eligible positions first), each taking the
    best player left. Returns (slot, pool index or None if nothing fits)."""
    ranked = pool.sort_values(points, ascending=False, kind="stable")
    left = list(zip(ranked.index, ranked["position"]))
    out = []
    for slot in sorted(slots, key=lambda s: (len(eligible(s)), s)):
        ok = eligible(slot)
        pick = None
        for i, (idx, pos) in enumerate(left):
            if pos in ok:
                pick = idx
                del left[i]
                break
        out.append((slot, pick))
    return out


def optimal_points(roster: pd.DataFrame, slots: list[str]) -> float:
    """Best lineup score from this roster (IR players are not eligible)."""
    pool = roster[roster["slot"] != IR_SLOT]
    return float(sum(pool.loc[i, "points"] for _, i in best_lineup(pool, slots) if i is not None))


BENCH_SLOT = "BE"
NEGLECT_EMPTY_SLOTS = 2


def neglected(lu: pd.DataFrame, slots: dict[int, list[str]]) -> pd.DataFrame:
    """(season, week, team_id, neglected): NEGLECT_EMPTY_SLOTS or more starting
    slots empty while a bench player who could fill one of them scored (a
    real, active alternative; a player on bye or out scores 0)."""
    rows = []
    for (season, week, team_id), roster in lu.groupby(["season", "week", "team_id"]):
        empty = Counter(slots[int(season)]) - Counter(roster.loc[roster["started"], "slot"])
        flag = False
        if sum(empty.values()) >= NEGLECT_EMPTY_SLOTS:
            bench = roster[roster["slot"] == BENCH_SLOT]
            flag = any((bench["position"].isin(eligible(s)) & bench["points"].ne(0)).any() for s in empty)
        rows.append({"season": season, "week": week, "team_id": team_id, "neglected": flag})
    return pd.DataFrame(rows, columns=["season", "week", "team_id", "neglected"])


def bench_depth(lu: pd.DataFrame, baseline_from: pd.DataFrame | None = None) -> pd.DataFrame:
    """(season, week, team_id, bench_depth): each bench player's points minus the
    average bench points at his position that week, summed over the bench (0 for
    an empty bench). baseline_from: the lineup rows whose benches set the average
    (default: all of lu)."""
    base_rows = lu if baseline_from is None else baseline_from
    bench = base_rows[base_rows["slot"] == BENCH_SLOT]
    base = bench.groupby(["season", "week", "position"])["points"].mean().rename("bench_avg").reset_index()
    mine = lu[lu["slot"] == BENCH_SLOT].merge(base, on=["season", "week", "position"], how="left")
    mine["rel"] = mine["points"] - mine["bench_avg"]
    teams = lu[["season", "week", "team_id"]].drop_duplicates()
    out = teams.merge(mine.groupby(["season", "week", "team_id"])["rel"].sum().rename("bench_depth").reset_index(),
                      on=["season", "week", "team_id"], how="left")
    out["bench_depth"] = out["bench_depth"].fillna(0.0)
    return out


def depth_adjusted(gap: pd.Series, depth: pd.Series) -> pd.Series:
    """Gap minus the gap a straight line through (depth, gap) predicts for that
    depth (one row per manager); negative = better than the bench predicts."""
    ok = gap.notna() & depth.notna()
    if ok.sum() < 2 or depth[ok].nunique() < 2:
        return pd.Series(float("nan"), index=gap.index)
    import numpy as np

    slope, intercept = np.polyfit(depth[ok].astype(float), gap[ok].astype(float), 1)
    return gap - (intercept + slope * depth)


def efficiency(tables: dict[str, pd.DataFrame], exclude: set[str] = frozenset(),
               legacy_mode: bool = False) -> pd.DataFrame:
    """One row per manager per counted game: actual and optimal points, the
    gap, whether the best lineup would have won a game that was lost, the
    forfeit and neglect flags, and bench depth. legacy_mode: excluded managers'
    benches are left out of the bench average."""
    games = weeks.counted_games(tables)
    lu = weeks.game_lineups(tables)
    slots = lineup_slots(lu)
    forfeits = weeks.forfeited_weeks(tables).assign(forfeited=True)
    depth = bench_depth(lu, lu[~lu["manager_key"].isin(exclude)] if legacy_mode else None)

    rows = []
    for (season, week, team_id), roster in lu.groupby(["season", "week", "team_id"]):
        rows.append({"season": season, "week": week, "team_id": team_id,
                     "actual_points": roster.loc[roster["started"], "points"].sum(),
                     "optimal_points": optimal_points(roster, slots[int(season)])})
    eff = pd.DataFrame(rows, columns=["season", "week", "team_id", "actual_points", "optimal_points"])
    out = games[["season", "week", "team_id", "manager_key", "opponent_manager_key", "points", "opponent_points",
                 "result", "tier", "is_playoff_week"]].merge(eff, on=["season", "week", "team_id"], how="left")
    out["efficiency_gap"] = out["optimal_points"] - out["actual_points"]
    out["would_have_won"] = out["optimal_points"] > out["opponent_points"]
    out["missed_win"] = out["result"].eq("L") & out["would_have_won"]
    out = out.merge(forfeits, on=["season", "week", "manager_key"], how="left")
    out["forfeited"] = out["forfeited"].eq(True)
    out = out.merge(neglected(lu, slots), on=["season", "week", "team_id"], how="left").merge(
        depth, on=["season", "week", "team_id"], how="left")
    out["neglected"] = out["neglected"].eq(True)
    out["excluded"] = out["forfeited"] | out["neglected"]
    return out.sort_values(["season", "week", "manager_key"]).reset_index(drop=True)


def blunders(eff: pd.DataFrame, exclude: set[str] = frozenset(), n: int = 10) -> pd.DataFrame:
    """The n largest efficiency gaps (forfeits, neglected lineups and excluded managers left out)."""
    e = eff[~eff["excluded"] & ~eff["manager_key"].isin(exclude)]
    return e.sort_values(["efficiency_gap", "season", "week"], ascending=[False, True, True]).head(n)


def display_order(slots: list[str]) -> list[str]:
    """Starting slots in display order: ESPN's slot order, with each flex slot
    right after the last position it accepts (QB, RB, WR, TE, RB/WR/TE, D/ST, K)."""
    from engine.normalize.espn import SLOTS

    rank = {label: i for i, label in SLOTS.items()}
    fixed = sorted({s for s in slots if len(eligible(s)) == 1}, key=lambda s: rank.get(s, 99))
    for flex in sorted({s for s in slots if len(eligible(s)) > 1}, key=lambda s: rank.get(s, 99)):
        after = max((i for i, s in enumerate(fixed) if s in eligible(flex)), default=len(fixed) - 1)
        fixed.insert(after + 1, flex)
    return fixed


def box_score(roster: pd.DataFrame, slots: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(starters in display order then points, bench and IR by points)."""
    order = {s: i for i, s in enumerate(display_order(slots))}
    real = ~roster["slot"].isin(NON_STARTING)
    st = roster[real].assign(_o=roster.loc[real, "slot"].map(order).fillna(len(order)))
    st = st.sort_values(["_o", "points"], ascending=[True, False], kind="stable").drop(columns="_o")
    be = roster[~real].sort_values("points", ascending=False, kind="stable")
    return st, be
