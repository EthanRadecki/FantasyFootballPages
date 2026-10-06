from pathlib import Path

import pandas as pd

from engine.analytics import schedule
from engine.config import load_config
from engine.legacy import name_to_key, resolve_names

GOLDEN = Path(__file__).parent / "golden"
A, B, C, D, X = "m_a", "m_b", "m_c", "m_d", "m_x"


def games(rows, season=2024, regular_weeks=14):
    """rows: (week, manager, points, opponent, opponent_points); both sides of a
    game are listed. Result follows the scores."""
    out = []
    for wk, m, p, o, op in rows:
        res = "W" if p > op else ("L" if p < op else "T")
        out.append({"season": season, "week": wk, "team_id": m, "manager_key": m, "opponent_manager_key": o,
                    "points": float(p), "opponent_points": float(op), "result": res, "is_bye": False,
                    "is_playoff_week": wk > regular_weeks, "tier": "REGULAR" if wk <= regular_weeks else "WINNERS_BRACKET"})
    return out


def tables(rows, lengths=None):
    m = pd.DataFrame(rows)
    lengths = lengths or {int(s): 14 for s in m["season"].unique()}
    seasons = pd.DataFrame({"season": list(lengths), "regular_season_periods": list(lengths.values())})
    return {"matchups": m, "seasons": seasons}


def game(wk, a, pa, b, pb, season=2024):
    return games([(wk, a, pa, b, pb), (wk, b, pb, a, pa)], season)


def test_luck_compares_each_score_with_the_weekly_median():
    # week 1 scores 100, 90, 80, 70: median 85. B lost to A but beat the median.
    t = tables(game(1, A, 100, B, 90) + game(1, C, 80, D, 70))
    luck = schedule.schedule_luck(t).set_index("manager_key")
    assert luck.loc[B, "actual_wins"] == 0 and luck.loc[B, "expected_wins"] == 1 and luck.loc[B, "schedule_luck"] == -1
    assert luck.loc[C, "schedule_luck"] == 1


def test_luck_uses_regular_season_only():
    t = tables(game(1, A, 100, B, 90) + game(15, A, 50, B, 60))
    luck = schedule.schedule_luck(t).set_index("manager_key")
    assert luck.loc[A, "games"] == 1


def test_excluded_managers_count_in_every_calculation_but_are_hidden():
    # X (excluded) scores 200 and 150: engine median of 200, 150, 100, 90 is 125
    t = tables(game(1, X, 200, A, 100) + game(1, B, 90, C, 150))
    legacy = schedule.schedule_luck(t, {X}, legacy_mode=True).set_index("manager_key")
    engine = schedule.schedule_luck(t, {X}).set_index("manager_key")
    assert X not in legacy.index
    assert engine.loc[X, "hidden"] and not engine.loc[A, "hidden"]
    assert legacy.loc[A, "expected_wins"] == 0   # legacy median of 100, 90, 150 is 100; not above it
    assert engine.loc[A, "expected_wins"] == 0 and engine.loc[C, "expected_wins"] == 1


def test_swap_includes_excluded_schedules_and_flags_them_hidden():
    rows = game(1, X, 200, A, 100) + game(1, B, 90, C, 150) + game(2, X, 80, B, 95) + game(2, A, 70, C, 60)
    legacy, _ = schedule.schedule_swap(tables(rows), {X}, legacy_mode=True)
    engine, summary = schedule.schedule_swap(tables(rows), {X})
    assert X not in set(legacy["manager_key"]) | set(legacy["schedule_key"])
    r = swap_table(engine, A, X)          # X's opponents: A (skipped), B 95; A scored 70 in week 2
    assert (r["wins"], r["losses"], r["hidden"]) == (0, 1, True)
    assert not swap_table(engine, A, B)["hidden"]
    assert summary.set_index("manager_key").loc[X, "hidden"]


def test_score_equal_to_the_median_is_half_an_expected_win():
    t = tables(game(1, A, 100, B, 90) + games([(1, C, 80, A, 100)]))   # odd count: 100, 90, 80
    engine = schedule.schedule_luck(t).set_index("manager_key")
    legacy = schedule.schedule_luck(t, legacy_mode=True).set_index("manager_key")
    assert engine.loc[B, "expected_wins"] == 0.5 and legacy.loc[B, "expected_wins"] == 0


def swap_table(pairs, mgr, sched):
    return pairs[(pairs["manager_key"] == mgr) & (pairs["schedule_key"] == sched)].iloc[0]


def test_swap_skips_weeks_where_the_schedule_owner_played_you():
    rows = (game(1, A, 100, B, 90) + game(1, C, 80, D, 70)
            + game(2, A, 100, C, 90) + game(2, B, 80, D, 95))
    pairs, _ = schedule.schedule_swap(tables(rows))
    r = swap_table(pairs, A, B)          # B's opponents: A (skipped), D 95
    assert (r["wins"], r["losses"], r["games"]) == (1, 0, 1)
    r = swap_table(pairs, D, A)          # A's opponents: B 90, C 90; D scored 70, 95
    assert (r["wins"], r["losses"]) == (1, 1)


def test_swap_never_uses_a_forfeited_score_as_the_wearers_score():
    rows = game(1, A, 0, B, 90) + game(1, C, 80, D, 70) + game(2, A, 100, C, 60) + game(2, B, 50, D, 55)
    pairs, _ = schedule.schedule_swap(tables(rows))
    r = swap_table(pairs, A, D)          # D's opponents: C 80 (A forfeited that week, skipped), B 50
    assert (r["wins"], r["games"]) == (1, 1)


def test_a_forfeited_opponent_is_a_win_for_whoever_wears_that_schedule():
    rows = game(1, A, 0, B, 90) + game(1, C, 80, D, 70)
    for legacy_mode in (True, False):
        pairs, _ = schedule.schedule_swap(tables(rows), legacy_mode=legacy_mode)
        assert swap_table(pairs, C, B)["wins"] == 1   # C wears B's schedule: opponent A scored 0


def test_swap_skips_weeks_the_wearer_did_not_play():
    rows = game(1, A, 100, B, 90) + game(2, A, 100, C, 90) + game(2, B, 80, D, 95)
    pairs, _ = schedule.schedule_swap(tables(rows))
    assert swap_table(pairs, C, A)["games"] == 0   # C played week 2 only, and A's week 2 opponent was C


def test_wins_gained_scales_by_the_season_length():
    rows = game(1, A, 100, B, 90) + game(1, C, 80, D, 70) + game(2, A, 60, B, 90) + game(2, C, 80, D, 70)
    _, legacy = schedule.schedule_swap(tables(rows, {2024: 2}), legacy_mode=True)
    _, engine = schedule.schedule_swap(tables(rows, {2024: 2}))          # a finished two-week regular season
    le, en = legacy.set_index("manager_key"), engine.set_index("manager_key")
    gap = en.loc[A, "avg_alt_pct"] - en.loc[A, "pct"]
    assert abs(en.loc[A, "wins_gained"] - gap * 2) < 1e-9
    assert abs(le.loc[A, "wins_gained"] - gap * 14) < 1e-9
    # a 13-week season two weeks in scales to the two weeks played, not a full season (M1b)
    assert schedule.season_lengths(tables(rows, {2024: 13})) == {2024: 2}
    assert schedule.season_lengths(tables(rows, {2024: 2})) == {2024: 2}
    _, live = schedule.schedule_swap(tables(rows, {2024: 13}))
    assert abs(live.set_index("manager_key").loc[A, "wins_gained"] - gap * 2) < 1e-9


# ----------------------------------------------------------------- golden

def legacy_tables():
    """Canonical-shaped matchups and seasons built from the legacy
    matchup_data.csv, so the schedule port is checked in CI."""
    cfg = load_config("leagues/preach/league.yaml")
    lk = name_to_key(cfg)
    md = pd.read_csv(GOLDEN / "matchup_data.csv.gz")
    num = md["Week"].str.extract(r"(\d+)$")[0].astype(int)
    playoff = md["Week"].str.startswith("Playoff")
    reg = num[~playoff].groupby(md["Season_Year"][~playoff]).max()
    week = num.where(~playoff, md["Season_Year"].map(reg) + num)
    m = pd.DataFrame({
        "season": md["Season_Year"].astype(int), "week": week, "team_id": md["Team_Name"],
        "manager_key": resolve_names(md["Team_Name"], lk), "opponent_manager_key": resolve_names(md["Opponent_Name"], lk),
        "points": md["Team_Score"].astype(float), "opponent_points": md["Opponent_Score"].astype(float),
        "result": md["Outcome"].map({"Win": "W", "Loss": "L", "Tie": "T"}), "is_bye": False,
        "is_playoff_week": playoff, "tier": playoff.map({True: "WINNERS_BRACKET", False: "REGULAR"})})
    seasons = pd.DataFrame({"season": reg.index.astype(int), "regular_season_periods": reg.to_numpy()})
    return {"matchups": m, "seasons": seasons}, md, cfg


def test_legacy_mode_reproduces_the_legacy_schedule_files():
    import gzip
    import json

    from engine.legacy_schedule import verify_schedule

    t, md, cfg = legacy_tables()
    with gzip.open(GOLDEN / "schedule" / "schedule_swap.json.gz", "rt", encoding="utf-8") as f:
        swap = json.load(f)
    golden = {"schedule_swap": swap, "matchup_data": md,
              "schedule_luck_season": pd.read_csv(GOLDEN / "schedule" / "schedule_luck_season.csv.gz")}
    checks, info = verify_schedule(t, golden, cfg)
    failed = [r.render() for r in checks if not r.ok]
    assert not failed, "\n".join(failed)
    assert any("career luck" in line for line in info)
