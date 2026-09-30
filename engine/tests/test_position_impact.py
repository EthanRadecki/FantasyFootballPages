import pandas as pd

from engine.analytics import position_impact as pi

A, B, C, D = "m_a", "m_b", "m_c", "m_d"


def test_nth_pick_is_the_number_of_dedicated_starting_slots():
    slots = ["QB", "RB", "RB", "WR", "WR", "TE", "RB/WR/TE", "D/ST", "K"]
    assert pi.nth_pick_rule(slots) == {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "K": 1, "D/ST": 1}


def games(rows):
    return pd.DataFrame([{"season": 2024, "week": w, "is_regular": reg, "manager_a": a, "manager_b": b,
                          "score_a": sa, "score_b": sb} for w, reg, a, b, sa, sb in rows])


def test_removing_a_position_flips_winners_and_a_tie_counts_as_a_flip():
    g = games([(1, True, A, B, 100.0, 95.0), (2, True, A, B, 100.0, 90.0)])
    started = {(2024, 1, A, "K", ): 0}
    started = {(2024, 1, A, "K"): 10.0, (2024, 2, A, "K"): 10.0, (2024, 2, B, "K"): 0.0}
    f = pi.flip_games(g, started, "K")
    assert f["flipped"].tolist() == [True, True]          # 90 vs 95 flips; 90 vs 90 is a tie, still a flip
    assert f["adj_winner"].tolist() == [B, "TIE"]


def test_flip_summary_counts_net_games_per_manager():
    g = games([(1, True, A, B, 100.0, 95.0), (2, True, C, D, 80.0, 70.0)])
    rates, seasons, net = pi.flip_summary(g, {(2024, 1, A, "QB"): 20.0}, ["QB"])
    assert rates.iloc[0][["flips", "total", "pct"]].tolist() == [1, 2, 50.0]
    n = net.set_index("manager_key")["net"]
    assert n[A] == -1 and n[B] == 1 and n[C] == 0


def lineups(rows):
    return pd.DataFrame([{"season": s, "week": w, "manager_key": m, "player_key": p, "player_name": f"p{p}",
                          "position": pos, "slot": slot, "started": slot not in ("BE", "IR"), "points": pts}
                         for s, w, m, p, pos, slot, pts in rows])


def test_consistency_needs_four_starts_and_a_positive_average():
    lu = lineups([(2024, w, A, 1, "K", "K", pts) for w, pts in enumerate([8, 10, 12, 10], 1)]
                 + [(2024, w, B, 2, "K", "K", 5.0) for w in (1, 2, 3)])
    c = pi.consistency(lu, ["K"]).iloc[0]
    assert c["sample"] == 1 and round(c["avg_cv"], 3) == round((8 / 3) ** 0.5 / 10, 3)


def test_acquisition_classifies_each_week_by_how_the_player_arrived():
    lu = lineups([(2024, w, A, 1, "WR", "WR", 10.0) for w in (1, 2, 3, 4)])
    waiver = pd.DataFrame([{"season": 2024, "manager_key": A, "player_key": 1, "start_week": 3, "end_week": 5}])
    trade = pd.DataFrame([{"season": 2024, "manager_key": A, "player_key": 1, "week": 2}])
    acq = pi.acquisition_by_week(lu, waiver, trade).iloc[0]
    assert (acq["drafted"], acq["traded"], acq["waiver"]) == (10.0, 10.0, 20.0)


def test_playoff_qualifier_seats_division_winners_first():
    tables = {"seasons": pd.DataFrame([{"season": 2024, "playoff_team_count": 2}]),
              "teams": pd.DataFrame([{"season": 2024, "manager_key": m, "division_id": d}
                                     for m, d in ((A, 0), (B, 0), (C, 1), (D, 1))])}
    st = pd.DataFrame([{"manager_key": m, "wins": w, "games": 10, "points": 1000.0}
                       for m, w in ((A, 9), (B, 8), (C, 3), (D, 2))])
    assert pi.playoff_qualifier(tables, None)(2024, st) == [A, C]


def test_season_in_progress_has_no_playoff_comparison():
    g = games([(1, True, A, B, 100.0, 95.0)])
    dg = pi.dst_games(g, {}, pi.playoff_labels(g))
    assert pi.season_playoffs(dg, lambda s, st: st["manager_key"].tolist()).empty


def test_playoff_rounds_are_named_back_from_the_final():
    g = games([(14, True, A, B, 1, 0), (15, False, A, B, 1, 0), (16, False, A, B, 1, 0), (17, False, A, B, 1, 0)])
    labels = pi.playoff_labels(g)
    assert [labels[(2024, w)] for w in (14, 15, 16, 17)] == ["Week 14", "Quarterfinal", "Semifinal", "Championship"]
