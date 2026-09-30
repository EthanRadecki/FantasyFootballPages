import pandas as pd

from engine.analytics import projected_sos as sos

A, B = "m_a", "m_b"
SLOTS = ["QB", "RB", "RB/WR/TE", "K"]


def lineups_table():
    """Week 1 finished (sets the slot shape), weeks 2 and 3 still to play."""
    rows = []
    for team, mk in ((1, A), (2, B)):
        for slot, pos in (("QB", "QB"), ("RB", "RB"), ("RB/WR/TE", "WR"), ("K", "K"), ("BE", "RB")):
            rows.append({"season": 2026, "week": 1, "team_id": team, "manager_key": mk, "slot": slot,
                         "position": pos, "started": slot != "BE", "points": 1.0, "player_id": 0})
    return pd.DataFrame(rows)


def proj(week, team, mk, rows):
    """rows: (player_id, position, slot, projected points or None)"""
    return [{"season": 2026, "week": week, "source": "roster", "team_id": team, "manager_key": mk,
             "player_id": pid, "player_name": f"p{pid}", "position": pos, "pro_team_id": 1, "slot": slot,
             "projected_points": pts} for pid, pos, slot, pts in rows]


def available(week, rows):
    return [{"season": 2026, "week": week, "source": "available", "team_id": None, "manager_key": None,
             "player_id": pid, "player_name": f"fa{pid}", "position": pos, "pro_team_id": 1, "slot": None,
             "projected_points": pts} for pid, pos, pts in rows]


def tables(projections, byes=()):
    m = pd.DataFrame([{"season": 2026, "week": 1, "team_id": t, "manager_key": k, "opponent_manager_key": o,
                       "points": 100.0, "opponent_points": 90.0, "result": "W" if t == 1 else "L",
                       "is_bye": False, "is_playoff_week": False, "tier": "REGULAR"} for t, k, o in ((1, A, B), (2, B, A))])
    fm = pd.DataFrame([{"season": 2026, "week": w, "team_id": t, "opponent_team_id": 3 - t, "manager_key": k,
                        "opponent_manager_key": o} for w in (2, 3) for t, k, o in ((1, A, B), (2, B, A))])
    return {"matchups": m, "lineups": lineups_table(), "future_matchups": fm,
            "projections": pd.DataFrame(projections),
            "pro_teams": pd.DataFrame([{"season": 2026, "pro_team_id": 1, "bye_week": w} for w in byes],
                                      columns=["season", "pro_team_id", "bye_week"])}


def team_rows(lu, week, mk):
    return lu[(lu["week"] == week) & (lu["manager_key"] == mk)].set_index("slot")


def test_only_unfinished_weeks_are_projected():
    t = tables(proj(2, 1, A, [(1, "QB", "QB", 20.0)]))
    assert sos.remaining_weeks(t)["week"].tolist() == [2, 3]


def test_best_projected_lineup_uses_bench_and_returning_ir_players():
    t = tables(proj(2, 1, A, [(1, "QB", "QB", 20.0), (2, "RB", "RB", 5.0), (3, "RB", "BE", 12.0),
                              (4, "WR", "IR", 15.0), (5, "WR", "RB/WR/TE", 0.0), (6, "K", "K", 8.0)]))
    lu = team_rows(sos.projected_lineups(t), 2, A)
    assert lu.loc["RB", "player_id"] == 3                  # benched RB projected higher than the starter
    assert lu.loc["RB/WR/TE", "player_id"] == 4            # IR player projected to be back fills the flex
    assert lu["projected_points"].sum() == 20 + 12 + 15 + 8


def test_empty_slot_takes_the_best_available_player_once():
    rows = proj(2, 1, A, [(1, "QB", "QB", None), (2, "RB", "RB", 10.0), (3, "WR", "BE", 9.0), (6, "K", "K", 0.0)])
    rows += available(2, [(50, "QB", 14.0), (51, "QB", 16.0), (52, "K", 0.0), (53, "K", 7.0)])
    lu = team_rows(sos.projected_lineups(tables(rows)), 2, A)
    assert lu.loc["QB", "player_id"] == 51 and lu.loc["QB", "source"] == "available"   # no projection: bye or out
    assert lu.loc["K", "player_id"] == 53
    assert lu.loc["RB/WR/TE", "player_id"] == 3 and lu.loc["RB/WR/TE", "source"] == "roster"


def test_sos_averages_opponents_and_ranks_hardest_first():
    totals = pd.DataFrame([(2026, w, k, p) for w, k, p in ((2, A, 100.0), (2, B, 120.0), (3, A, 110.0), (3, B, 90.0))],
                          columns=["season", "week", "manager_key", "proj_points"])
    sched = pd.DataFrame([(2026, w, k, o) for w in (2, 3) for k, o in ((A, B), (B, A))],
                         columns=["season", "week", "manager_key", "opponent_manager_key"])
    out = sos.sos_from_totals(totals, sched).set_index("manager_key")
    assert out.loc[A, "sos_avg_opp_ppg"] == 105.0 and out.loc[A, "own_avg_proj_ppg"] == 105.0
    assert out.loc[B, "sos_avg_opp_ppg"] == 105.0
    only3 = sos.sos_from_totals(totals, sched, start_week=3).set_index("manager_key")
    assert only3.loc[A, "sos_avg_opp_ppg"] == 90.0 and only3.loc[A, "sos_rank"] == 2
    assert only3.loc[B, "sos_rank"] == 1 and only3.loc[B, "weeks_counted"] == 1


def test_legacy_lineup_swaps_a_starter_on_bye_for_the_best_bench_player():
    rows = proj(2, 1, A, [(1, "QB", "QB", 20.0), (2, "RB", "RB", 10.0), (3, "RB", "BE", 6.0), (4, "WR", "BE", 7.0),
                          (5, "WR", "RB/WR/TE", 0.0), (6, "K", "K", 8.0), (7, "RB", "IR", 30.0)])
    lu = team_rows(sos.legacy_lineups(tables(rows), {"WR": 8.0}), 2, A)
    assert lu.loc["RB/WR/TE", "player_id"] == 4             # zero-projected starter: best bench player that fits
    assert 7 not in set(lu["player_id"])                    # IR is never used by the legacy method


def test_analyze_projected_sos_tables():
    rows = []
    for w in (2, 3):
        rows += proj(w, 1, A, [(1, "QB", "QB", 20.0), (2, "RB", "RB", 10.0), (3, "WR", "RB/WR/TE", 9.0), (4, "K", "K", 7.0)])
        rows += proj(w, 2, B, [(11, "QB", "QB", 18.0), (12, "RB", "RB", 12.0), (13, "WR", "RB/WR/TE", 8.0), (14, "K", "K", 6.0)])
    out = sos.analyze_projected_sos(tables(rows))
    s = out["projected_sos"].set_index("manager_key")
    assert s.loc[A, "sos_avg_opp_ppg"] == 44.0 and s.loc[B, "sos_avg_opp_ppg"] == 46.0
    assert s.loc[B, "sos_rank"] == 1 and s.loc[A, "start_week"] == 2 and not s["hidden"].any()


def test_sos_math_reproduces_the_legacy_sos_file_and_rankings_page():
    import gzip
    import json
    from pathlib import Path

    from engine.config import load_config
    from engine.legacy_sos import check_sos_math

    g = Path(__file__).parent / "golden" / "sos"
    with gzip.open(g / "rankings_2026_week03.json.gz", "rt", encoding="utf-8") as f:
        ranking = json.load(f)
    checks = check_sos_math(pd.read_csv(g / "projected_sos_weekly_detail.csv.gz"), pd.read_csv(g / "schedule_2026.csv.gz"),
                            pd.read_csv(g / "projected_sos_2026.csv.gz"), ranking, load_config("leagues/preach/league.yaml"))
    failed = [c.render() for c in checks if not c.ok]
    assert not failed, "\n".join(failed)
