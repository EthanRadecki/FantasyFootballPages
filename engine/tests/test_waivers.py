import pandas as pd

from engine.analytics import waivers

A, B = "m_a", "m_b"
TEAMS = {1: A, 2: B}


def tx(rows):
    """rows: (week, ts, type, item_type, player, from_team, to_team, txn_manager)"""
    return pd.DataFrame([{"season": 2024, "scoring_period": w, "proposed_at_ms": ts, "type": typ, "item_type": it,
                          "player_id": p, "from_team_id": f, "to_team_id": to, "manager_key": mk, "status": "EXECUTED"}
                         for w, ts, typ, it, p, f, to, mk in rows])


def lineup(rows):
    """rows: (week, team, player, slot, points)"""
    return pd.DataFrame([{"season": 2024, "week": w, "team_id": t, "manager_key": TEAMS[t], "player_id": p,
                          "player_name": f"p{p}", "position": "WR", "slot": s, "started": s not in ("BE", "IR"),
                          "points": pts} for w, t, p, s, pts in rows])


def tables(lu_rows, tx_rows, weeks=6):
    lu = lineup(lu_rows + [(w, t, 900 + t, "WR", 10.0) for w in range(1, weeks + 1) for t in (1, 2)])
    m = pd.DataFrame([{"season": 2024, "week": w, "team_id": t, "manager_key": TEAMS[t], "result": "W" if t == 1 else "L",
                       "is_bye": False, "is_playoff_week": False, "tier": "REGULAR", "points": 100.0}
                      for w in range(1, weeks + 1) for t in (1, 2)])
    teams = pd.DataFrame([{"season": 2024, "team_id": t, "manager_key": k} for t, k in TEAMS.items()])
    return {"lineups": lu, "matchups": m, "transactions": tx(tx_rows), "teams": teams}


def test_stint_runs_from_the_add_to_the_next_drop():
    t = tables([(2, 1, 5, "WR", 12.0), (3, 1, 5, "BE", 4.0)],
               [(2, 1, "WAIVER", "ADD", 5, 0, 1, A), (4, 2, "FREEAGENT", "DROP", 5, 1, 0, A)])
    s = waivers.waiver_stints(t).iloc[0]
    assert (s.start_week, s.end_week, s.weeks_rostered, s.total_points, s.type) == (2, 4, 2, 16.0, "WAIVER")


def test_undrafted_drop_and_readd_same_week_is_not_a_pickup():
    rows = [(w, 1, 5, "WR", 8.0) for w in range(1, 5)]
    t = tables(rows, [(1, 0, "DRAFT", "DRAFT", 5, 0, 1, A), (3, 10, "ROSTER", "DROP", 5, 1, 0, A),
                      (3, 11, "FREEAGENT", "ADD", 5, 0, 1, A)])
    assert waivers.waiver_stints(t).empty


def test_claiming_a_player_your_own_trade_dropped_is_not_a_pickup():
    t = tables([(3, 1, 5, "WR", 8.0)], [(3, 10, "TRADE_ACCEPT", "DROP", 5, 2, 0, A), (3, 11, "WAIVER", "ADD", 5, 0, 1, A)])
    assert waivers.waiver_stints(t).empty


def test_drop_forced_by_another_managers_trade_does_not_end_the_stint():
    rows = [(w, 1, 5, "WR", 8.0) for w in range(2, 6)]
    t = tables(rows, [(2, 1, "FREEAGENT", "ADD", 5, 0, 1, A), (4, 5, "TRADE_ACCEPT", "DROP", 5, 1, 0, B)])
    s = waivers.waiver_stints(t).iloc[0]
    assert s.weeks_rostered == 4 and s.end_week == 7


def test_ir_weeks_count_only_in_legacy_mode():
    t = tables([(2, 1, 5, "WR", 12.0), (3, 1, 5, "IR", 0.0)], [(2, 1, "WAIVER", "ADD", 5, 0, 1, A),
                                                              (4, 2, "WAIVER", "DROP", 5, 1, 0, A)])
    assert waivers.waiver_stints(t).iloc[0].weeks_rostered == 1
    assert waivers.waiver_stints(t, legacy_mode=True).iloc[0].weeks_rostered == 2


def test_excluded_managers_are_counted_but_hidden():
    t = tables([(2, 2, 5, "WR", 12.0)], [(2, 1, "WAIVER", "ADD", 5, 0, 2, B)])
    s = waivers.waiver_stints(t, {B})
    assert len(s) == 1 and s.iloc[0].hidden
    assert waivers.waiver_stints(t, {B}, legacy_mode=True).empty


def test_leaderboard_weights_by_weeks():
    st = pd.DataFrame([{"season": 2024, "manager_key": A, "position": "WR", "type": "WAIVER", "weeks_rostered": 1,
                        "total_points": 10.0, "total_z": 1.0, "hidden": False},
                       {"season": 2024, "manager_key": A, "position": "WR", "type": "FREEAGENT", "weeks_rostered": 3,
                        "total_points": 30.0, "total_z": -1.0, "hidden": False}])
    lb = waivers.waiver_leaderboard(st).set_index(["scope", "position", "type", "manager_key"])
    row = lb.loc[("career", "ALL", "ALL", A)]
    assert row.pickups == 2 and row.ppw == 10.0 and row.z_per_week == 0.0


def test_best_pickups_need_positive_value_and_three_weeks():
    st = pd.DataFrame([{"season": 2024, "manager_key": A, "position": "WR", "weeks_rostered": w, "total_z": z,
                        "hidden": False} for w, z in ((2, 5.0), (3, 1.0), (4, -1.0), (5, 2.0))])
    best = waivers.best_pickups(st)
    top = best[(best["scope"] == "career") & (best["list_position"] == "ALL")]
    assert top["total_z"].tolist() == [2.0, 1.0]


def test_roster_stints_split_on_gaps_and_list_starts():
    t = tables([(1, 1, 5, "WR", 1.0), (2, 1, 5, "BE", 1.0), (4, 1, 5, "WR", 1.0)], [])
    rs = waivers.roster_stints(t)
    rs = rs[rs["player_id"] == 5]
    assert list(zip(rs["start"], rs["end"], rs["started"])) == [(1, 2, "1"), (4, 4, "4")]
