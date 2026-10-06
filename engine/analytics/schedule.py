"""Schedule analyses: schedule luck and schedule swap.

Both use finished regular-season games only (no byes, no playoff games of any
tier): once the field shrinks each round, comparing a score with the league
is no longer meaningful.

Schedule luck
    Each week, a manager "should have" won when their score beat the league
    median that week. Luck = actual wins - expected wins, per manager and
    season.

Schedule swap
    For every manager A and every other manager B in a season: A's record had
    A played B's real opponents, using A's own weekly score against the score
    B's opponent actually put up. Win percentage, not raw wins, so seasons
    with uneven schedules compare fairly. Weeks are skipped when B's real
    opponent was A (A cannot play itself), when A has no game that week, and
    when A forfeited that week (a sat lineup is not a performance). A forfeit
    still counts as the opponent's score: every manager wearing that schedule
    gets the win, as the real opponent did.

Excluded managers (league.yaml analysis.exclude_managers) take part in every
calculation: their scores set the weekly median, their games and schedules
count. They are only hidden from view: every output row carries `hidden`, and
publishing leaves hidden rows out.

legacy_mode=True reproduces the legacy scripts (build_schedule_luck.py,
build_schedule_swap.py). The engine default applies every fix in
ENGINE_CHANGES; `fixes` picks a subset, and `engine analyze --verify` prints
the effect of each one alone.

All functions are pure: canonical tables in, DataFrames out.
"""

from __future__ import annotations

from collections import defaultdict

import pandas as pd

from engine.analytics.weeks import counted_games, forfeited_weeks

LEGACY_SEASON_LENGTH = 14   # build_schedule_swap.py scaled every season to 14 weeks

# Engine fixes to the legacy method, each switchable so --verify can show its
# own effect. legacy_mode turns them all off.
ENGINE_CHANGES = {
    "include_excluded": "excluded managers (Sullivan, Serafin) count in every calculation (weekly median, their "
                        "games, their schedules) and are only hidden from view",
    "season_length": "wins gained scales to each season's regular-season length (13 weeks in 2020 and 2021), not 14; "
                     "the live season's to the weeks played so far",
    "half_ties": "a tie counts as half a win; a score equal to the median is half an expected win",
}


def _fixes(legacy_mode: bool, fixes) -> frozenset:
    if fixes is not None:
        return frozenset(fixes)
    return frozenset() if legacy_mode else frozenset(ENGINE_CHANGES)


def regular_games(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Finished regular-season games, one row per team."""
    g = counted_games(tables)
    g = g[~g["is_playoff_week"]]
    return g[["season", "week", "manager_key", "opponent_manager_key", "points", "opponent_points",
              "result"]].reset_index(drop=True)


def _season_lengths(tables: dict[str, pd.DataFrame], legacy_mode: bool) -> dict[int, int]:
    s = tables["seasons"]
    if legacy_mode:
        return {int(y): LEGACY_SEASON_LENGTH for y in s["season"]}
    return {int(y): int(n) for y, n in zip(s["season"], s["regular_season_periods"])}


def season_lengths(tables: dict[str, pd.DataFrame]) -> dict[int, int]:
    """Regular-season games per season: the league's regular season, or for a season still in its
    regular season the weeks finished so far (M1b, Ethan 2026-10-06: the live season's wins gained
    scale to the games played, not to a full season)."""
    played = regular_games(tables).groupby("season")["week"].nunique()
    return {y: min(n, int(played.get(y, n))) for y, n in _season_lengths(tables, False).items()}


def schedule_luck(tables: dict[str, pd.DataFrame], exclude_managers: set[str] = frozenset(),
                  legacy_mode: bool = False, fixes=None) -> pd.DataFrame:
    """(season, manager_key, games, actual_wins, expected_wins, schedule_luck, hidden)."""
    fx = _fixes(legacy_mode, fixes)
    g = regular_games(tables)
    if "include_excluded" not in fx:
        # Legacy dropped the excluded managers' own rows, median included.
        g = g[~g["manager_key"].isin(exclude_managers)]
    median = g.groupby(["season", "week"])["points"].median().rename("median_points").reset_index()
    rows = g.merge(median, on=["season", "week"])
    above = rows["points"] > rows["median_points"]
    if "half_ties" not in fx:
        rows["expected_win"] = above.astype(float)
        rows["actual_win"] = rows["result"].eq("W").astype(float)
    else:
        level = rows["points"] == rows["median_points"]
        rows["expected_win"] = above.astype(float) + 0.5 * level.astype(float)
        rows["actual_win"] = rows["result"].map({"W": 1.0, "T": 0.5}).fillna(0.0)
    out = rows.groupby(["season", "manager_key"]).agg(
        games=("week", "size"), actual_wins=("actual_win", "sum"), expected_wins=("expected_win", "sum")).reset_index()
    out["schedule_luck"] = out["actual_wins"] - out["expected_wins"]
    out["hidden"] = out["manager_key"].isin(exclude_managers)
    return out.sort_values(["season", "manager_key"]).reset_index(drop=True)


def _outcome(own: float, opp: float, ties: bool) -> str:
    if own > opp:
        return "W"
    if ties and own == opp:
        return "T"
    return "L"


def _pct(w: float, l: float, t: float) -> float:
    n = w + l + t
    return (w + 0.5 * t) / n if n else 0.0


def schedule_swap(tables: dict[str, pd.DataFrame], exclude_managers: set[str] = frozenset(),
                  legacy_mode: bool = False, fixes=None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (pairs, summary).

    pairs:   season, manager_key, schedule_key (whose schedule was worn), wins,
             losses, ties, games, pct, hidden (either manager is hidden)
    summary: season, manager_key, wins, losses, ties, pct (actual record over
             the games used), avg_alt_pct (mean over every other schedule),
             wins_gained ((avg_alt_pct - pct) x season length, season_lengths()), hidden
    """
    fx = _fixes(legacy_mode, fixes)
    g = regular_games(tables)
    if "include_excluded" not in fx:
        # Legacy dropped excluded managers and every game against them.
        g = g[~g["manager_key"].isin(exclude_managers) & ~g["opponent_manager_key"].isin(exclude_managers)]
    forfeits = {tuple(r) for r in forfeited_weeks(tables)[["season", "week", "manager_key"]].itertuples(index=False)}
    lengths = season_lengths(tables) if "season_length" in fx else _season_lengths(tables, True)
    ties = "half_ties" in fx

    # season -> manager -> week -> (own points, opponent key, opponent points, result)
    sched: dict = defaultdict(lambda: defaultdict(dict))
    for r in g.itertuples(index=False):
        sched[int(r.season)][r.manager_key][int(r.week)] = (float(r.points), r.opponent_manager_key,
                                                           float(r.opponent_points), r.result)

    pairs, summary = [], []
    for season in sorted(sched):
        managers = sorted(sched[season])
        for mgr in managers:
            mine = sched[season][mgr]
            actual = defaultdict(int)
            for own, _, opp, result in mine.values():
                actual[result if ties and result in ("W", "L", "T") else _outcome(own, opp, ties)] += 1
            actual_pct = _pct(actual["W"], actual["L"], actual["T"])
            alt_pcts = []
            for other in managers:
                if other == mgr:
                    continue
                rec = defaultdict(int)
                for week, (_, opp_key, opp_points, _) in sched[season][other].items():
                    if opp_key == mgr or week not in mine or (season, week, mgr) in forfeits:
                        continue
                    rec[_outcome(mine[week][0], opp_points, ties)] += 1
                p = _pct(rec["W"], rec["L"], rec["T"])
                alt_pcts.append(p)
                pairs.append({"season": season, "manager_key": mgr, "schedule_key": other, "wins": rec["W"],
                              "losses": rec["L"], "ties": rec["T"], "games": rec["W"] + rec["L"] + rec["T"],
                              "pct": p, "hidden": mgr in exclude_managers or other in exclude_managers})
            avg = sum(alt_pcts) / len(alt_pcts) if alt_pcts else 0.0
            summary.append({"season": season, "manager_key": mgr, "wins": actual["W"], "losses": actual["L"],
                            "ties": actual["T"], "pct": actual_pct, "avg_alt_pct": avg,
                            "wins_gained": (avg - actual_pct) * lengths.get(season, LEGACY_SEASON_LENGTH),
                            "hidden": mgr in exclude_managers})
    pair_cols = ["season", "manager_key", "schedule_key", "wins", "losses", "ties", "games", "pct", "hidden"]
    sum_cols = ["season", "manager_key", "wins", "losses", "ties", "pct", "avg_alt_pct", "wins_gained", "hidden"]
    return pd.DataFrame(pairs, columns=pair_cols), pd.DataFrame(summary, columns=sum_cols)


def analyze_schedule(tables: dict[str, pd.DataFrame], exclude_managers: set[str] = frozenset(),
                     legacy_mode: bool = False, fixes=None) -> dict[str, pd.DataFrame]:
    pairs, summary = schedule_swap(tables, exclude_managers, legacy_mode, fixes)
    return {
        "schedule_luck": schedule_luck(tables, exclude_managers, legacy_mode, fixes),
        "schedule_swap": pairs,
        "schedule_swap_summary": summary,
    }
