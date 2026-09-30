"""Draft value: how much each pick returned compared with picks made around it.

Replaces the legacy surplus_value_index.py, surplus_value_index_2026_live.py,
generate_draft_heatmap.py, hit_rate_by_round.py, and generate_draft_board_data.py.
Career and live (in-season) grading are one code path.

Method (unchanged from the legacy scripts):
1. Starter baseline per season and position: mean points per game of the top
   14 QB and TE, top 28 RB and WR, among the season's player pool, counting
   only players with 8 games; in a live season, half the weeks played so far
   (rounded down, at least 1), reaching 8 in week 16. The legacy baseline had
   no games floor (league decision 2026-09-29 to add it).
2. Position-relative value (PRV) = the pick's points per game minus that
   baseline. A pick needs the same games as the baseline (8 in a finished
   season; in a live season half the weeks played, at least 1, 8 from week
   16); otherwise it has no PRV and no surplus (injury neutral). The legacy
   live grades needed 1 game.
3. Expected PRV = mean PRV of every skill pick made within 3 overall picks,
   any season and position, excluding the pick itself. A finished season's
   picks are compared with finished seasons only; a live season's picks also
   with that season's picks.
4. Surplus = PRV - expected PRV, weighted by round (1-3: 1.00, 4-7: 0.85,
   8-12: 0.70, 13+: 0.55).

Stats come from the player pool by ESPN player id (the legacy scripts matched
names, and missed a few).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from engine.analytics.weeks import live_seasons

SKILL = ["RB", "WR", "QB", "TE"]
STARTER_RANK = {"QB": 14, "TE": 14, "RB": 28, "WR": 28}
MIN_GAMES = 8
MIN_GAMES_LIVE = 1
WINDOW = 3
ROUND_WEIGHTS = [(3, 1.00), (7, 0.85), (12, 0.70)]
LATE_WEIGHT = 0.55

HIT_TOP_N = {"WR": 24, "RB": 24, "QB": 7, "TE": 7}
HIT_BENCH_GAMES = 10
STEAL_MIN_ROUND = 8
STEAL_MIN_GAMES = 8
TIERS = [("Early", 1, 3), ("Middle", 4, 7), ("Late", 8, 99)]
HEATMAP_TIERS = [("early", 1, 3), ("middle", 4, 7), ("midlate", 8, 12), ("late", 13, 16)]


def round_weight(rnd: int) -> float:
    for last, w in ROUND_WEIGHTS:
        if rnd <= last:
            return w
    return LATE_WEIGHT


def tier(rnd: int) -> str:
    return next(name for name, lo, hi in TIERS if lo <= rnd <= hi)


# ------------------------------------------------------------------ inputs

def season_stats(tables: dict[str, pd.DataFrame], universe: pd.DataFrame | None = None) -> pd.DataFrame:
    """Per season and player: position, points per game (2 decimals, as the
    site shows it), and games. universe restricts the pool (legacy mode)."""
    ps = tables["player_stats"] if universe is None else universe
    return pd.DataFrame({
        "season": ps["season"].astype(int), "player_id": ps["player_id"].astype(int),
        "stat_position": ps["position"], "ppg": [round(float(a), 2) for a in ps["avg_points"]],   # Python rounding, as the site data used
        "games": ps["games"].astype(int),
    })


def baseline_min_games(weeks_played: int | None) -> int:
    """Games a player needs to count toward a position baseline: 8 in a
    finished season (weeks_played None); in a live season half the weeks
    played so far, rounded down, at least 1 and at most 8 (8 from week 16)."""
    if weeks_played is None:
        return MIN_GAMES
    return max(MIN_GAMES_LIVE, min(MIN_GAMES, weeks_played // 2))


def baselines(stats: pd.DataFrame, live_weeks: dict[int, int] | None = None, min_games: bool = True) -> pd.DataFrame:
    """(season, position) -> starter baseline PPG.

    Only players with enough games count toward it (baseline_min_games), so a
    one-game spot start cannot set the bar. live_weeks maps each live season to
    the weeks played so far. min_games=False reproduces the legacy baseline,
    which counted every player."""
    live_weeks = live_weeks or {}
    s = stats[stats["stat_position"].isin(SKILL)]
    if min_games:
        floor = s["season"].map(lambda season: baseline_min_games(live_weeks.get(season)))
        s = s[s["games"] >= floor]
    rows = []
    for (season, pos), g in s.groupby(["season", "stat_position"]):
        top = g.nlargest(STARTER_RANK[pos], "ppg")["ppg"].mean()
        rows.append({"season": season, "position": pos, "baseline": round(top, 4)})
    return pd.DataFrame(rows)


def skill_picks(tables: dict[str, pd.DataFrame], exclude: set[str] = frozenset(),
                espn_numbering: bool = False) -> pd.DataFrame:
    """Every skill-position pick with the drafting manager and the player's
    position that season. espn_numbering uses ESPN's own pick numbers (the
    legacy files did, before the draft-order correction)."""
    dp = tables["draft_picks"].copy()
    if espn_numbering and "espn_overall_pick" in dp:
        dp["overall_pick"] = dp["espn_overall_pick"].fillna(dp["overall_pick"]).astype(int)
        dp["round_pick"] = dp["espn_round_pick"].fillna(dp["round_pick"]).astype(int)
    pos = tables["player_seasons"][["season", "player_id", "player_name", "position"]]
    out = dp.merge(pos, on=["season", "player_id"], how="left")
    out = out[out["position"].isin(SKILL) & ~out["manager_key"].isin(exclude)]
    return out.sort_values(["season", "overall_pick"]).reset_index(drop=True)


# ----------------------------------------------------------------- surplus

def surplus(picks: pd.DataFrame, stats: pd.DataFrame, live_seasons: set[int] = frozenset(),
            force_zero: set[tuple[int, int]] = frozenset(),
            no_stats: set[tuple[int, int]] = frozenset(), baseline_floor: bool = True,
            live_weeks: dict[int, int] | None = None) -> pd.DataFrame:
    """PRV, expected PRV, and surplus for every pick.

    Legacy mode only, both keyed by (season, overall_pick):
    force_zero: picks with no PRV whatever their games (the hand-kept injury list)
    no_stats: picks treated as having no stats at all (legacy name match missed)"""
    base = baselines(stats, live_weeks, baseline_floor)
    out = picks.merge(stats[["season", "player_id", "ppg", "games"]], on=["season", "player_id"], how="left")
    out["ppg"] = out["ppg"].fillna(0.0)
    out["games"] = out["games"].fillna(0).astype(int)
    missed = pd.Series([(s, p) in no_stats for s, p in zip(out["season"], out["overall_pick"])], index=out.index)
    out.loc[missed, ["ppg", "games"]] = [0.0, 0]
    out = out.merge(base, on=["season", "position"], how="left")
    live = out["season"].isin(live_seasons)
    if baseline_floor:     # engine: the same sliding bar as the baseline
        weeks = live_weeks or {}
        floor = out["season"].map(lambda season: baseline_min_games(weeks.get(season) if season in live_seasons else None))
    else:                  # legacy: 1 game in a live season
        floor = np.where(live, MIN_GAMES_LIVE, MIN_GAMES)
    forced = pd.Series([(s, p) in force_zero for s, p in zip(out["season"], out["overall_pick"])], index=out.index)
    has_prv = (out["games"] >= floor) & ~forced
    out["prv"] = (out["ppg"] - out["baseline"].fillna(0)).round(4).where(has_prv)

    finished = ~live
    exp, n = [], []
    valid = out[out["prv"].notna()]
    for i, r in out.iterrows():
        pool = valid[(valid["overall_pick"] >= r["overall_pick"] - WINDOW)
                     & (valid["overall_pick"] <= r["overall_pick"] + WINDOW)]
        pool = pool[finished[pool.index] | (pool["season"] == r["season"])] if live[i] else pool[finished[pool.index]]
        pool = pool.drop(index=i, errors="ignore")
        exp.append(round(pool["prv"].mean(), 4) if len(pool) else np.nan)
        n.append(len(pool))
    out["expected_prv"] = exp
    out["n_comps"] = n
    out["surplus"] = (out["prv"] - out["expected_prv"]).round(4).fillna(0.0)
    out["actual_prv"] = out["prv"].fillna(0.0)
    out["expected_prv"] = out["expected_prv"].fillna(0.0)
    out["zeroed"] = out["prv"].isna()
    out["live"] = live
    out["weight"] = out["round"].map(round_weight)
    out["surplus_wtd"] = out["surplus"] * out["weight"]
    return out


def live_seasons_from(sur: pd.DataFrame) -> list[int]:
    """Seasons graded as live in a surplus table."""
    return sorted(sur.loc[sur["live"], "season"].unique().tolist()) if "live" in sur else []


def _visible_rank(values: pd.Series, hidden: pd.Series) -> pd.Series:
    """Rank (1 = highest) among visible rows only; hidden rows get no rank."""
    r = values.where(~hidden).rank(ascending=False, method="first")
    return r.astype("Int64")


def career_grades(sur: pd.DataFrame, seasons: list[int]) -> pd.DataFrame:
    s = sur[sur["season"].isin(seasons)]
    g = s.groupby("manager_key").agg(weighted_total=("surplus_wtd", "sum"), total_weight=("weight", "sum"),
                                     total_picks=("player_id", "size"), seasons=("season", "nunique"),
                                     hidden=("hidden", "any")).reset_index()
    g["avg_surplus"] = (g["weighted_total"] / g["total_weight"]).round(4)
    g = g.sort_values("avg_surplus", ascending=False, kind="stable").reset_index(drop=True)
    g["rank"] = _visible_rank(g["avg_surplus"], g["hidden"])
    return g


def season_grades(sur: pd.DataFrame) -> pd.DataFrame:
    g = sur.groupby(["season", "manager_key"]).agg(
        draft_grade=("surplus_wtd", "sum"), total_weight=("weight", "sum"), total_picks=("player_id", "size"),
        picks_with_data=("zeroed", lambda z: int((~z).sum())), hidden=("hidden", "any")).reset_index()
    g["draft_grade"] = g["draft_grade"].round(2)
    g["season_rank"] = g["draft_grade"].where(~g["hidden"]).groupby(g["season"]).rank(ascending=False).astype("Int64")
    return g


def heatmap(sur: pd.DataFrame) -> pd.DataFrame:
    """Per manager, round, and draft slot: average surplus and the picks."""
    g = sur.groupby(["manager_key", "round", "draft_slot"]).agg(
        avg_surplus=("surplus", lambda s: round(float(np.mean([round(float(x), 2) for x in s])), 3)),
        n_seasons=("surplus", "size"), hidden=("hidden", "any")).reset_index()
    return g


# ---------------------------------------------------------------- hit rate

def hit_thresholds(stats: pd.DataFrame) -> pd.DataFrame:
    """(season, position) -> hit cutoff (PPG of the Nth best player with 10+
    games) and position average (mean PPG of those players)."""
    bench = stats[(stats["games"] >= HIT_BENCH_GAMES) & stats["stat_position"].isin(HIT_TOP_N)]
    rows = []
    for (season, pos), g in bench.groupby(["season", "stat_position"]):
        ranked = g.sort_values("ppg", ascending=False)["ppg"].reset_index(drop=True)
        n = HIT_TOP_N[pos]
        rows.append({"season": season, "position": pos,
                     "cutoff": ranked.iloc[n - 1] if len(ranked) >= n else ranked.iloc[-1],
                     "pos_avg": round(ranked.mean(), 2)})
    return pd.DataFrame(rows)


def hits(picks: pd.DataFrame, stats: pd.DataFrame, force_zero: set[tuple[int, int]] = frozenset()) -> pd.DataFrame:
    """Every skill pick with hit flag (PPG at or above the season's top-N
    cutoff at the position) and points above the position average."""
    out = picks.merge(stats[["season", "player_id", "ppg", "games"]], on=["season", "player_id"], how="left")
    out["ppg"] = out["ppg"].fillna(0.0)
    out["games"] = out["games"].fillna(0).astype(int)
    forced = pd.Series([(s, p) in force_zero for s, p in zip(out["season"], out["overall_pick"])], index=out.index)
    out.loc[forced, ["ppg", "games"]] = [0.0, 0]
    out = out.merge(hit_thresholds(stats), on=["season", "position"], how="left")
    out["hit"] = (out["ppg"] > 0) & out["cutoff"].notna() & (out["ppg"] >= out["cutoff"])
    out["pts_above_avg"] = np.where(out["ppg"] == 0, 0.0, (out["ppg"] - out["pos_avg"].fillna(0)).round(2))
    out["tier"] = out["round"].map(tier)
    return out


def steals(h: pd.DataFrame, n: int = 10) -> pd.DataFrame:
    """Round 8+ picks with 8+ games, most points above the position average."""
    s = h[(h["round"] >= STEAL_MIN_ROUND) & (h["games"] >= STEAL_MIN_GAMES)]
    return s.sort_values("pts_above_avg", ascending=False, kind="stable").head(n)


# ---------------------------------------------------------------- pipeline

# ------------------------------------------------------------------ board

BOARD_COLUMNS = ["season", "round", "overall_pick", "draft_slot", "manager_key", "player_id", "player_name",
                 "position", "ppg", "games"]


def board(tables: dict[str, pd.DataFrame], stats: pd.DataFrame, live: set[int] = frozenset(),
          all_positions: bool = True, live_stats: bool = True,
          force_zero: set[tuple[int, int]] = frozenset()) -> pd.DataFrame:
    """The draft board (draft-history.html): every pick of every season in
    draft order, with the player's PPG and games that season.

    stats: season_stats() output. Legacy mode: PPG for skill positions only
    (all_positions=False), none for a live season (live_stats=False), and the
    hand-kept zero list, keyed by ESPN's pick numbers (force_zero)."""
    dp = tables["draft_picks"].copy()
    ps = tables["player_seasons"][["season", "player_id", "player_name", "position"]]
    out = dp.merge(ps, on=["season", "player_id"], how="left").merge(
        stats[["season", "player_id", "ppg", "games"]], on=["season", "player_id"], how="left")
    if not all_positions:
        out.loc[~out["position"].isin(SKILL), ["ppg", "games"]] = np.nan
    if not live_stats:
        out.loc[out["season"].isin(live), ["ppg", "games"]] = np.nan
    if force_zero:
        espn = out["espn_overall_pick"].fillna(out["overall_pick"]) if "espn_overall_pick" in out else out["overall_pick"]
        zero = pd.Series([(s, int(p)) in force_zero for s, p in zip(out["season"], espn)], index=out.index)
        out.loc[zero, ["ppg", "games"]] = [0.0, 0]
    return out.sort_values(["season", "overall_pick"])[BOARD_COLUMNS].reset_index(drop=True)


def board_data(board_df: pd.DataFrame, manager_names: dict[str, str] | None = None) -> dict:
    """The page's DRAFT (season -> round -> picks) and SLOT_ORDER (season ->
    managers by draft slot, from round 1)."""
    names = manager_names or {}
    draft: dict = {}
    for (season, rnd), g in board_df.groupby(["season", "round"], sort=True):
        draft.setdefault(str(int(season)), {})[str(int(rnd))] = [
            {"p": r.player_name, "pos": r.position, "ppg": None if pd.isna(r.ppg) else round(float(r.ppg), 2),
             "g": None if pd.isna(r.games) else int(r.games)} for r in g.itertuples()]
    slots = {str(int(season)): [names.get(k, k) for k in g.sort_values("draft_slot")["manager_key"]]
             for season, g in board_df[board_df["round"] == 1].groupby("season", sort=True)}
    return {"DRAFT": draft, "SLOT_ORDER": slots}


def live_weeks_played(tables: dict[str, pd.DataFrame], live: set[int]) -> dict[int, int]:
    """Live season -> weeks completed so far."""
    from engine.analytics.weeks import completed_weeks

    done = completed_weeks(tables).groupby("season")["week"].max()
    return {s: int(done.get(s, 0)) for s in live}


def analyze_draft(tables: dict[str, pd.DataFrame], exclude: set[str] = frozenset(), legacy_mode: bool = False,
                  legacy_universe: pd.DataFrame | None = None,
                  force_zero: set[tuple[int, int]] = frozenset(),
                  hit_force_zero: set[tuple[int, int]] = frozenset(),
                  no_stats: set[tuple[int, int]] = frozenset()) -> dict[str, pd.DataFrame]:
    """Draft value for every season with a draft and stats.

    legacy_mode reproduces the legacy files: ESPN's pick numbering, the legacy
    player universe (rostered plus 500 free agents), no games floor for the
    baseline, the hand-kept injury list, and excluded managers' picks dropped
    before surplus. Hit rate keeps every manager, as the legacy file did.

    Engine mode: excluded managers' picks count in every calculation (the
    expected-PRV comparison pool included) and are only hidden: every output
    row carries `hidden`, and ranks count visible managers only.
    """
    live = live_seasons(tables)
    stats = season_stats(tables, legacy_universe if legacy_mode else None)
    picks = skill_picks(tables, exclude if legacy_mode else frozenset(), espn_numbering=legacy_mode)
    picks["hidden"] = picks["manager_key"].isin(exclude)
    weeks_played = live_weeks_played(tables, live)
    sur = surplus(picks, stats, live, force_zero, no_stats, baseline_floor=not legacy_mode, live_weeks=weeks_played)
    finished = sorted(set(sur["season"]) - live)
    all_picks = skill_picks(tables, frozenset(), espn_numbering=legacy_mode)
    h = hits(all_picks[~all_picks["season"].isin(live)], stats, hit_force_zero)
    h["hidden"] = h["manager_key"].isin(exclude)
    return {
        "draft_baselines": baselines(stats, weeks_played, min_games=not legacy_mode),
        "draft_surplus": sur,
        "draft_career_grades": career_grades(sur, finished),
        "draft_season_grades": season_grades(sur),
        "draft_heatmap": heatmap(sur[sur["season"].isin(finished)]),
        "draft_hit_thresholds": hit_thresholds(stats),
        "draft_hits": h,
        "draft_board": board(tables, stats, live, all_positions=not legacy_mode, live_stats=not legacy_mode,
                             force_zero=hit_force_zero if legacy_mode else frozenset()),
    }
