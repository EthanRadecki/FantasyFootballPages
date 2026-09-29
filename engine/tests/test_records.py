import pandas as pd

from engine.analytics import lineups, records, weeks
from engine.config import excluded_manager_keys

A, B = "m_aaaaaaaaaaaa", "m_bbbbbbbbbbbb"
SLOTS = ["QB", "RB", "RB", "WR", "WR", "TE", "RB/WR/TE", "D/ST", "K"]


def roster(rows):
    """rows: (name, position, slot, points)"""
    return pd.DataFrame([{"player_name": n, "player_id": i, "position": p, "slot": s, "points": pts,
                          "started": s not in ("BE", "IR")} for i, (n, p, s, pts) in enumerate(rows)])


def test_slots_come_from_the_most_common_started_lineup():
    lu = pd.concat([roster([("q", "QB", "QB", 1), ("r", "RB", "RB", 1)]).assign(season=2024, week=w, team_id=1)
                    for w in (1, 2)] + [roster([("q", "QB", "QB", 1)]).assign(season=2024, week=3, team_id=1)])
    assert sorted(lineups.lineup_slots(lu)[2024]) == ["QB", "RB"]


def test_optimal_lineup_fills_fixed_slots_then_flex_and_skips_ir():
    r = roster([("q", "QB", "QB", 20), ("r1", "RB", "RB", 10), ("r2", "RB", "BE", 15), ("r3", "RB", "BE", 12),
                ("w1", "WR", "WR", 8), ("w2", "WR", "WR", 7), ("w3", "WR", "BE", 11), ("t", "TE", "TE", 5),
                ("d", "D/ST", "D/ST", 4), ("k", "K", "K", 9), ("hurt", "RB", "IR", 40)])
    # QB 20, RB 15+12, WR 11+8, TE 5, FLEX best left (RB 10), D/ST 4, K 9
    assert lineups.optimal_points(r, SLOTS) == 94


def test_display_order_puts_flex_after_the_positions_it_covers():
    assert lineups.display_order(SLOTS) == ["QB", "RB", "WR", "TE", "RB/WR/TE", "D/ST", "K"]


def matchups(rows):
    """rows: (season, week, game_id, team_id, manager, points, opp_points, result, bye, playoff_week, tier)"""
    return pd.DataFrame([{"season": s, "week": w, "game_id": g, "team_id": t, "manager_key": m, "points": p,
                          "opponent_points": o, "result": r, "is_bye": bye, "is_playoff_week": po, "tier": tier,
                          "opponent_manager_key": None}
                         for s, w, g, t, m, p, o, r, bye, po, tier in rows])


def test_counted_games_drop_byes_consolation_and_unfinished_weeks():
    m = matchups([
        (2024, 1, 1, 1, A, 100, 90, "W", False, False, "REGULAR"),
        (2024, 1, 1, 2, B, 90, 100, "L", False, False, "REGULAR"),
        (2024, 1, 2, 3, "m_c", 80, None, "BYE", True, False, "REGULAR"),
        (2024, 15, 3, 1, A, 70, 60, "W", False, True, "LOSERS_CONSOLATION_LADDER"),
        (2024, 15, 3, 2, B, 60, 70, "L", False, True, "LOSERS_CONSOLATION_LADDER"),
        (2026, 3, 4, 1, A, 0, 0, None, False, False, "REGULAR"),
    ])
    g = weeks.counted_games({"matchups": m})
    assert sorted(zip(g["week"], g["manager_key"])) == [(1, A), (1, B)]


def game_tables():
    m = matchups([(2024, 1, 1, 2, B, 20.0, 30.0, "L", False, False, "REGULAR"),     # home listed first
                  (2024, 1, 1, 1, A, 30.0, 20.0, "W", False, False, "REGULAR")])
    lu = pd.concat([
        roster([("a1", "QB", "QB", 30.0), ("a2", "QB", "BE", 5.0)]).assign(team_id=1, manager_key=A),
        roster([("b1", "QB", "QB", 20.0), ("b2", "QB", "BE", 35.0), ("b3", "QB", "IR", 50.0)]).assign(team_id=2, manager_key=B),
    ]).assign(season=2024, week=1)
    lu["player_id"] = range(len(lu))
    teams = pd.DataFrame({"season": 2024, "team_id": [1, 2], "manager_key": [A, B], "team_name": ["Aces", "Bees"]})
    seasons = pd.DataFrame({"season": [2024], "regular_season_periods": [14]})
    ps = lu[["season", "player_id", "player_name", "position"]]
    return {"matchups": m, "lineups": lu, "teams": teams, "seasons": seasons, "player_seasons": ps}


def test_team_a_is_the_away_team_and_missed_win_uses_the_optimal_lineup():
    t = game_tables()
    g = records.games(t).iloc[0]
    assert (g["team_a_key"], g["team_b_key"], g["team_a_name"], g["margin"]) == (A, B, "Aces", 10.0)
    eff = lineups.efficiency(t).set_index("manager_key")
    assert eff.at[B, "optimal_points"] == 35.0 and eff.at[B, "missed_win"]      # IR 50 never counts
    assert not eff.at[A, "missed_win"] and not eff.at[B, "forfeited"]


def test_leaders_count_every_roster_week_but_points_only_when_started():
    t = game_tables()
    lead = records.player_seasons_by_manager(t).set_index("player_name")
    assert (lead.at["b2", "weeks_rostered"], lead.at["b2", "games_played"], lead.at["b2", "total_points"]) == (1, 0, 0.0)
    assert (lead.at["b1", "games_played"], lead.at["b1", "total_points"]) == (1, 20.0)


def test_best_weeks_keep_the_top_scores_per_manager_position_and_season():
    t = game_tables()
    best = records.best_weeks(t, per_group=1)
    assert sorted(best["player_name"]) == ["a1", "b1"]


def test_excluded_managers_resolve_from_slugs():
    cfg = {"managers": [{"name": "Ann A", "id": A}, {"name": "Bob B", "id": B}],
           "analysis": {"exclude_managers": ["bob-b"]}}
    assert excluded_manager_keys(cfg) == {B}
