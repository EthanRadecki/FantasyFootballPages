import json
from pathlib import Path

import numpy as np
import pandas as pd

from engine.analytics import stints, trades, weeks
from engine.config import load_config
from engine.legacy import name_to_key, resolve_names

GOLDEN = Path(__file__).parent / "golden"
A, B, C = "m_aaaaaaaaaaaa", "m_bbbbbbbbbbbb", "m_cccccccccccc"


def items(rows):
    """rows: (transaction_id, period, ts, player_id, from, to)"""
    return pd.DataFrame([{"season": 2024, "scoring_period": sp, "transaction_id": t, "proposed_at_ms": ts,
                          "player_id": p, "from_manager_key": f, "to_manager_key": to}
                         for t, sp, ts, p, f, to in rows])


def matchups(rows, result="L"):
    """rows: (season, week, team/manager, points, is_bye, is_playoff_week, tier)"""
    return pd.DataFrame([{"season": s, "week": w, "team_id": k, "manager_key": k, "points": p, "is_bye": bye,
                          "is_playoff_week": po, "tier": tier, "result": "BYE" if bye else result}
                         for s, w, k, p, bye, po, tier in rows])


# ------------------------------------------------------------------ weeks

def test_week_weights_count_back_from_the_final():
    rows = [(2020, w, A, 100, False, w > 13, "WINNERS_BRACKET" if w > 13 else "REGULAR") for w in range(1, 18)]
    rows += [(2022, w, A, 100, False, w > 14, "WINNERS_BRACKET" if w > 14 else "REGULAR") for w in range(1, 18)]
    w = weeks.week_weights({"matchups": matchups(rows)}).set_index(["season", "week"])["week_weight"]
    assert [w[(2020, k)] for k in (13, 14, 15, 16, 17)] == [1.0, 1.15, 1.3, 1.6, 2.0]
    assert [w[(2022, k)] for k in (14, 15, 16, 17)] == [1.0, 1.3, 1.6, 2.0]


def test_consolation_only_playoff_week_is_not_a_round():
    m = matchups([(2024, 15, A, 90, False, True, "WINNERS_BRACKET"), (2024, 16, A, 90, False, True, "LOSERS_CONSOLATION_LADDER")])
    w = weeks.week_weights({"matchups": m}).set_index("week")["week_weight"]
    assert w[15] == 2.0 and w[16] == 1.0


def test_forfeit_is_a_zero_in_a_finished_game_not_a_bye_or_an_unplayed_week():
    m = matchups([(2024, 14, A, 0.0, False, False, "REGULAR"), (2024, 14, B, 0.0, True, False, "REGULAR"),
                  (2024, 14, C, 88.0, False, False, "REGULAR")])
    unplayed = matchups([(2026, 3, A, 0.0, False, False, "REGULAR")], result=None)
    f = weeks.forfeited_weeks({"matchups": pd.concat([m, unplayed])})
    assert f[["season", "week", "manager_key"]].values.tolist() == [[2024, 14, A]]


def test_position_baseline_uses_starters_and_bench_but_not_ir():
    lu = pd.DataFrame({"season": 2024, "week": 1, "position": "RB", "points": [10.0, 20.0, 0.0],
                       "slot": ["RB", "BE", "IR"]})
    b = weeks.position_baseline(lu).iloc[0]
    assert b["pos_mean"] == 15.0 and np.isclose(b["pos_std"], np.sqrt(50.0))
    legacy = weeks.position_baseline(lu, include_ir=True).iloc[0]
    assert legacy["pos_mean"] == 10.0 and np.isclose(legacy["pos_std"], 10.0)


# ----------------------------------------------------------------- stints

def z_rows(rows):
    """rows: (week, slot, weighted_z) for manager A, player 1"""
    return pd.DataFrame([{"season": 2024, "manager_key": A, "player_id": 1, "week": w, "slot": s,
                          "position": "WR", "weighted_z": z} for w, s, z in rows])


def test_stint_counts_later_weeks_even_after_a_gap_but_ir_is_not_started():
    acq = pd.DataFrame([{"season": 2024, "manager_key": A, "player_id": 1, "start_week": 3}])
    z = z_rows([(2, "WR", 5.0), (3, "WR", 1.0), (4, "BE", 2.0), (6, "IR", -1.0)])
    s = stints.stints(acq, z).iloc[0]
    assert s["weeks_rostered"] == 3 and s["total_z"] == 2.0 and s["realized_z"] == 1.0 and s["position"] == "WR"
    legacy = stints.stints(acq, z, ir_counts_as_started=True).iloc[0]
    assert legacy["realized_z"] == 0.0


def test_player_never_rostered_after_trade_has_empty_stint():
    acq = pd.DataFrame([{"season": 2024, "manager_key": A, "player_id": 1, "start_week": 9}])
    s = stints.stints(acq, z_rows([(2, "WR", 5.0)])).iloc[0]
    assert s["weeks_rostered"] == 0 and s["total_z"] == 0.0 and pd.isna(s["position"])


# -------------------------------------------------------------- reversals

def test_mirror_pair_is_found_across_periods_in_one_season():
    it = items([("t1", 3, 100, 1, A, B), ("t1", 3, 100, 2, B, A),
                ("t2", 5, 200, 1, B, A), ("t2", 5, 200, 2, A, B),
                ("t3", 5, 300, 3, A, C)])
    kept, log = trades.real_trade_items(it)
    assert set(kept["transaction_id"]) == {"t3"}
    assert log[["original_transaction_id", "reversal_transaction_id", "reason"]].values.tolist() == [["t1", "t2", "mirror"]]


def test_netting_trades_between_one_pair_in_one_period_are_removed():
    it = items([("t1", 3, 100, 1, A, B), ("t1", 3, 100, 2, B, A),
                ("t2", 3, 200, 1, B, A), ("t2", 3, 200, 3, A, B),
                ("t3", 3, 300, 3, B, A), ("t3", 3, 300, 2, A, B)])
    assert trades.netting_reversals(it) == {"t1", "t2", "t3"}


# ----------------------------------------------------------------- groups

def test_player_who_bounces_nets_by_count_not_set():
    # A gives 1 to B, B gives 1 back, then A gives 1 to B again for 2: A really gave 1 and got 2.
    it = items([("t1", 3, 100, 1, A, B), ("t2", 3, 200, 1, B, A), ("t3", 3, 300, 1, A, B), ("t3", 3, 300, 2, B, A)])
    count = trades.trade_sides(it).set_index("manager_key")
    assert json.loads(count.at[A, "gave_player_ids"]) == [1] and json.loads(count.at[A, "got_player_ids"]) == [2]
    legacy = trades.trade_sides(it, net_by="set").set_index("manager_key")
    assert json.loads(legacy.at[A, "gave_player_ids"]) == [] and json.loads(legacy.at[A, "got_player_ids"]) == [2]


def test_three_two_manager_trades_forming_a_triangle_are_one_group():
    it = items([("t1", 4, 100, 1, A, B), ("t2", 4, 110, 2, B, C), ("t3", 4, 120, 3, C, A),
                ("t4", 4, 130, 9, A, B)])
    s = trades.trade_sides(it)
    assert s["group_id"].nunique() == 1 and s["num_transactions_in_group"].iloc[0] == 4


def test_unrelated_trades_in_one_period_stay_separate_and_ids_follow_time():
    it = items([("late", 4, 500, 1, A, B), ("early", 4, 100, 2, B, C)])
    s = trades.trade_sides(it).drop_duplicates("group_id")
    assert s["transaction_ids"].tolist() == ['["early"]', '["late"]'] and s["group_id"].tolist() == [1, 2]


# ------------------------------------------------------------------- QUAD

def test_low_stakes_needs_a_side_that_is_only_kickers_and_dst():
    assert trades.is_low_stakes(["K"], ["RB"])
    assert trades.is_low_stakes(["RB"], ["D/ST", "K"])
    assert not trades.is_low_stakes(["RB", "D/ST"], ["WR"])
    assert not trades.is_low_stakes([], ["WR"])


def test_quad_dampens_low_stakes_sides():
    m = pd.DataFrame({"trade_grade": [1.0, -1.0, 3.0], "realized_gains": [1.0, -1.0, 2.0],
                      "fit_score": [0.1, -0.1, 0.0], "necessity_per_week": [np.nan, 1.0, 2.0],
                      "low_stakes": [False, False, True]})
    q = trades.quad(m)
    assert q["z_necessity"].iloc[0] == 0.0
    assert np.isclose(q["QUAD"].iloc[2], q["QUAD_unadjusted"].iloc[2] * trades.LOW_STAKES_MULTIPLIER)
    assert q["QUAD"].iloc[0] == q["QUAD_unadjusted"].iloc[0]


# ----------------------------------------------------------------- golden

def legacy_tables():
    """Canonical-shaped tables built from the legacy input files, so the whole
    trades port can be checked in CI without an ESPN pull."""
    cfg = load_config("leagues/preach/league.yaml")
    lk = name_to_key(cfg)
    r = pd.read_csv(GOLDEN / "weekly_rosters_bracket_only.csv.gz")
    tm = pd.read_csv(GOLDEN / "trades" / "trades_mapped.csv.gz")
    mk = resolve_names(r["Manager"], lk)
    lineups = pd.DataFrame({"season": r["Season"], "week": r["Week"], "team_id": mk, "manager_key": mk,
                            "player_id": r["Player_ID"], "player_name": r["Player"], "position": r["Position"],
                            "slot": r["Slot"], "started": r["Started"], "points": r["Points"]})
    started = lineups[lineups["started"]].groupby(["season", "week", "manager_key"])["points"].sum()
    weeks_ = r.assign(manager_key=mk).groupby(["Season", "Week", "manager_key"])["Week_Label"].first().reset_index()
    playoff = weeks_["Week_Label"].str.startswith("Playoff")
    pts = [started.get((s, w, k), 0.0) for s, w, k in zip(weeks_["Season"], weeks_["Week"], weeks_["manager_key"])]
    m = pd.DataFrame({"season": weeks_["Season"], "week": weeks_["Week"], "team_id": weeks_["manager_key"],
                      "manager_key": weeks_["manager_key"], "points": pts, "is_bye": False,
                      "is_playoff_week": playoff, "tier": np.where(playoff, "WINNERS_BRACKET", "REGULAR"),
                      "result": "L"})
    tx = pd.DataFrame({"season": tm["Season"], "scoring_period": tm["Scoring_Period"],
                       "transaction_id": tm["Transaction_ID"], "type": "TRADE_ACCEPT", "status": "EXECUTED",
                       "item_type": "TRADE", "player_id": tm["Player_ID"],
                       "from_team_id": resolve_names(tm["From_Manager"], lk),
                       "to_team_id": resolve_names(tm["To_Manager"], lk),
                       "proposed_at_ms": tm["Proposed_Date_Unix_ms"], "source": "league"})
    teams = pd.DataFrame([(s, k, k) for s in range(2020, 2026) for k in set(lk.values())],
                         columns=["season", "team_id", "manager_key"])
    ps = pd.concat([lineups[["season", "player_id", "player_name", "position"]],
                    pd.DataFrame({"season": tm["Season"], "player_id": tm["Player_ID"], "player_name": tm["Player"],
                                  "position": None})]).drop_duplicates(["season", "player_id"])
    tables = {"lineups": lineups, "matchups": m, "transactions": tx, "teams": teams, "player_seasons": ps}
    return tables, r, cfg


def test_legacy_mode_reproduces_every_legacy_trade_file():
    from engine.cli import TRADE_GOLDENS
    from engine.legacy_trades import verify_trades

    tables, rosters, cfg = legacy_tables()
    golden = {n: pd.read_csv(GOLDEN / "trades" / f"{n}.csv.gz") for n in TRADE_GOLDENS}
    golden["weekly_rosters_bracket_only"] = rosters
    results, info = verify_trades(tables, golden, cfg)
    failed = [r.render() for r in results if not r.ok]
    assert not failed, "\n".join(failed)
    assert any("4 side(s) with different players" in line for line in info)
