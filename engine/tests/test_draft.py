import numpy as np
import pandas as pd

from engine.analytics import draft


def stats(rows):
    """rows: (season, player_id, position, ppg, games)"""
    return pd.DataFrame([{"season": s, "player_id": p, "stat_position": pos, "ppg": ppg, "games": g}
                         for s, p, pos, ppg, g in rows])


def picks(rows):
    """rows: (season, overall_pick, round, player_id, position, manager)"""
    return pd.DataFrame([{"season": s, "overall_pick": o, "round": r, "draft_slot": o, "player_id": p,
                          "position": pos, "manager_key": m} for s, o, r, p, pos, m in rows])


def test_round_weights_and_tiers():
    assert [draft.round_weight(r) for r in (1, 3, 4, 7, 8, 12, 13, 16)] == [1.0, 1.0, 0.85, 0.85, 0.7, 0.7, 0.55, 0.55]
    assert [draft.tier(r) for r in (1, 4, 8, 16)] == ["Early", "Middle", "Late", "Late"]


def test_baseline_is_the_mean_of_the_top_n_at_the_position():
    s = stats([(2024, i, "QB", float(i), 17) for i in range(1, 21)])
    b = draft.baselines(s).set_index(["season", "position"])["baseline"]
    assert b[(2024, "QB")] == np.mean(range(7, 21))          # top 14 of 1..20


def test_baseline_ignores_players_below_the_games_floor_unless_legacy():
    s = stats([(2024, i, "TE", 10.0, 17) for i in range(14)] + [(2024, 99, "TE", 40.0, 1)])
    assert draft.baselines(s).iloc[0]["baseline"] == 10.0
    assert draft.baselines(s, min_games=False).iloc[0]["baseline"] == round((13 * 10.0 + 40.0) / 14, 4)


def test_live_baseline_floor_is_half_the_weeks_played_up_to_eight():
    assert [draft.baseline_min_games(w) for w in (1, 2, 3, 4, 9, 15, 16, 17)] == [1, 1, 1, 2, 4, 7, 8, 8]
    assert draft.baseline_min_games(None) == 8


def test_expected_prv_uses_picks_within_three_excluding_itself_and_needs_eight_games():
    s = stats([(2024, i, "QB", 0.0, 17) for i in range(100, 114)]           # baseline 0
              + [(2024, 1, "RB", 10.0, 17), (2024, 2, "RB", 4.0, 17), (2024, 3, "RB", 30.0, 5)])   # RB baseline: the two with 8+ games
    p = picks([(2024, 1, 1, 1, "RB", "a"), (2024, 3, 1, 2, "RB", "b"), (2024, 4, 1, 3, "RB", "c")])
    out = draft.surplus(p, s).set_index("overall_pick")
    base = np.mean([10.0, 4.0])
    assert np.isclose(out.at[1, "prv"], round(10.0 - base, 4))
    assert out.at[4, "zeroed"] and out.at[4, "surplus"] == 0.0            # 5 games < 8
    assert out.at[1, "n_comps"] == 1 and np.isclose(out.at[1, "expected_prv"], out.at[3, "prv"])


def test_live_pick_needs_half_the_weeks_played():
    s = stats([(2026, i, "WR", 10.0, 6) for i in range(1, 30)] + [(2026, 99, "WR", 20.0, 2)])
    p = picks([(2026, 1, 1, 99, "WR", "a"), (2026, 2, 1, 1, "WR", "b")])
    out = draft.surplus(p, s, live_seasons={2026}, live_weeks={2026: 6}).set_index("player_id")
    assert out.at[99, "zeroed"] and not out.at[1, "zeroed"]          # week 6: 3 games needed
    legacy = draft.surplus(p, s, live_seasons={2026}, live_weeks={2026: 6}, baseline_floor=False).set_index("player_id")
    assert not legacy.at[99, "zeroed"]


def test_live_season_compares_with_finished_seasons_plus_itself():
    s = stats([(2025, 1, "WR", 10.0, 17), (2026, 2, "WR", 12.0, 2), (2026, 3, "WR", 8.0, 2)])
    p = picks([(2025, 5, 1, 1, "WR", "a"), (2026, 5, 1, 2, "WR", "b"), (2026, 6, 1, 3, "WR", "c")])
    out = draft.surplus(p, s, live_seasons={2026}, live_weeks={2026: 2}).set_index(["season", "overall_pick"])
    assert out.at[(2026, 5), "n_comps"] == 2            # 2025 pick 5 and 2026 pick 6
    assert out.at[(2025, 5), "n_comps"] == 0            # finished picks never see the live season


def test_hit_needs_the_top_n_cutoff_among_players_with_ten_games():
    s = stats([(2024, i, "TE", float(i), 12) for i in range(1, 11)] + [(2024, 99, "TE", 50.0, 3)])
    p = picks([(2024, 1, 1, 4, "TE", "a"), (2024, 2, 1, 3, "TE", "b"), (2024, 3, 1, 99, "TE", "c")])
    h = draft.hits(p, s).set_index("player_id")
    # cutoff = 7th best of 1..10 = 4.0 (the 3-game player is not in the benchmark)
    assert h.at[4, "hit"] and not h.at[3, "hit"] and h.at[99, "hit"]
    assert h.at[4, "pts_above_avg"] == round(4.0 - 5.5, 2)


def test_hidden_managers_are_graded_but_not_ranked():
    import pandas as pd

    from engine.analytics import draft

    sur = pd.DataFrame({"season": 2020, "manager_key": ["a", "x", "b"], "player_id": [1, 2, 3],
                        "surplus_wtd": [1.0, 5.0, -1.0], "weight": 1.0, "zeroed": False,
                        "hidden": [False, True, False]})
    career = draft.career_grades(sur, [2020]).set_index("manager_key")
    assert career.loc["a", "rank"] == 1 and career.loc["b", "rank"] == 2 and pd.isna(career.loc["x", "rank"])
    season = draft.season_grades(sur).set_index("manager_key")
    assert season.loc["a", "season_rank"] == 1 and pd.isna(season.loc["x", "season_rank"])


def test_board_orders_picks_and_applies_legacy_rules():
    from engine.analytics.draft import board, board_data
    t = {
        "draft_picks": pd.DataFrame({"season": [2024] * 4, "overall_pick": [2, 1, 3, 4], "espn_overall_pick": [1, 2, 3, 4],
                                     "round": [1, 1, 2, 2], "draft_slot": [2, 1, 2, 1], "player_id": [10, 11, 12, 13],
                                     "manager_key": ["b", "a", "b", "a"]}),
        "player_seasons": pd.DataFrame({"season": [2024] * 4, "player_id": [10, 11, 12, 13],
                                        "player_name": ["RB Guy", "WR Guy", "K Guy", "QB Guy"],
                                        "position": ["RB", "WR", "K", "QB"]}),
    }
    stats = pd.DataFrame({"season": [2024] * 4, "player_id": [10, 11, 12, 13], "ppg": [12.3, 15.0, 8.0, 20.1],
                          "games": [16, 17, 17, 9]})
    eng = board(t, stats)
    assert eng["player_name"].tolist() == ["WR Guy", "RB Guy", "K Guy", "QB Guy"]      # draft order, not ESPN's numbers
    assert eng.loc[eng["position"] == "K", "ppg"].item() == 8.0
    leg = board(t, stats, all_positions=False, force_zero={(2024, 1)})                 # ESPN pick 1 = RB Guy
    assert pd.isna(leg.loc[leg["position"] == "K", "ppg"].item())
    assert leg.loc[leg["player_name"] == "RB Guy", ["ppg", "games"]].values.tolist() == [[0.0, 0]]
    assert board(t, stats, live={2024}, live_stats=False)["ppg"].isna().all()
    data = board_data(eng, {"a": "Ann", "b": "Bob"})
    assert [p["p"] for p in data["DRAFT"]["2024"]["1"]] == ["WR Guy", "RB Guy"]
    assert data["SLOT_ORDER"] == {"2024": ["Ann", "Bob"]}
