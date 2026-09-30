import gzip
import json
from pathlib import Path

import numpy as np
import pandas as pd

from engine.analytics import playoff_odds as po

GOLDEN = Path(__file__).parent / "golden"


def test_scoring_model_shrinks_toward_the_league():
    mu, sd, n = po.scoring_model({"a": [120.0], "b": [80.0, 100.0]}, ["a", "b", "c"])
    league = np.mean([120.0, 80.0, 100.0])
    assert mu["a"] == (120.0 + 3 * league) / 4 and mu["c"] == league and n == {"a": 1, "b": 2, "c": 0}


def test_simulate_top_cutoff_and_division_winners():
    rng = np.random.default_rng(1)
    teams = ["a", "b", "c", "d"]
    wins = {"a": 5, "b": 4, "c": 3, "d": 0}
    odds = po.simulate(teams, wins, {}, [], lambda t, w: 100.0, {t: 10.0 for t in teams}, rng.normal, 200, cutoff=2)
    assert odds == {"a": 100.0, "b": 100.0, "c": 0.0, "d": 0.0}
    div = {"a": 1, "b": 1, "c": 1, "d": 2}          # d wins its one-team division
    odds = po.simulate(teams, wins, {}, [], lambda t, w: 100.0, {t: 10.0 for t in teams}, rng.normal, 200,
                       cutoff=2, divisions=div)
    assert odds == {"a": 100.0, "b": 0.0, "c": 0.0, "d": 100.0}


def season_tables(n_weeks=3, played_weeks=(1,), divisions=None, future=True):
    teams = ["m_a", "m_b", "m_c", "m_d"]
    rows, fm, gid = [], [], 0
    pairs = [("m_a", "m_b"), ("m_c", "m_d")]
    for w in range(1, n_weeks + 1):
        for a, b in pairs:
            gid += 1
            done = w in played_weeks
            for t, o, p, op in ((a, b, 110.0, 90.0), (b, a, 90.0, 110.0)):
                rows.append({"season": 2026, "week": w, "game_id": gid, "team_id": teams.index(t) + 1, "manager_key": t,
                             "opponent_manager_key": o, "points": p if done else 0.0, "opponent_points": op if done else 0.0,
                             "result": ("W" if p > op else "L") if done else None, "is_bye": False,
                             "is_playoff_week": False, "tier": "REGULAR"})
                fm.append({"season": 2026, "week": w, "game_id": gid, "manager_key": t, "opponent_manager_key": o})
    return {
        "matchups": pd.DataFrame(rows),
        "future_matchups": pd.DataFrame(fm if future else [], columns=["season", "week", "game_id", "manager_key",
                                                                         "opponent_manager_key"]),
        "seasons": pd.DataFrame([{"season": 2026, "regular_season_periods": n_weeks, "playoff_team_count": 2}]),
        "teams": pd.DataFrame([{"season": 2026, "manager_key": t, "division_id": (divisions or {}).get(t, 0)}
                               for t in teams]),
    }


def test_finished_weeks_use_results_and_week_one_is_flat():
    t = season_tables(played_weeks=(1, 2, 3))
    odds = po.playoff_odds(t, trials=2000)
    w1 = odds[odds["week"] == 1]
    assert set(w1["odds"]) == {50.0} and set(w1["method"]) == {"flat"}      # 2 spots / 4 teams
    assert set(odds[odds["week"] > 1]["method"]) == {"results"}
    assert set(odds["week"]) == {1, 2, 3}


def test_live_week_blends_projections_and_later_weeks_are_not_computed():
    t = season_tables(played_weeks=(1,))
    t["projected_team_weeks"] = pd.DataFrame([{"season": 2026, "week": w, "manager_key": k, "proj_points": p}
                                              for w in (2, 3) for k, p in (("m_a", 60.0), ("m_b", 150.0),
                                                                           ("m_c", 100.0), ("m_d", 100.0))])
    odds = po.playoff_odds(t, trials=4000).set_index(["week", "manager_key"])
    assert set(odds.index.get_level_values("week")) == {1, 2}
    assert odds.loc[(2, "m_a"), "method"] == "results+projections"
    no_proj = po.playoff_odds({k: v for k, v in t.items() if k != "projected_team_weeks"}, trials=4000)
    no_proj = no_proj.set_index(["week", "manager_key"])
    assert odds.loc[(2, "m_b"), "odds"] > no_proj.loc[(2, "m_b"), "odds"]     # projection lifts b


def test_each_week_reproduces_on_its_own():
    t = season_tables(played_weeks=(1, 2, 3))
    full = po.playoff_odds(t, trials=1000)
    again = po.playoff_odds(t, trials=1000, seasons={2026})
    pd.testing.assert_frame_equal(full, again)


def test_division_winner_structure_comes_from_the_teams_table():
    t = season_tables(played_weeks=(1, 2, 3), divisions={"m_b": 1})     # b alone in division 1
    odds = po.playoff_odds(t, trials=1000).set_index(["week", "manager_key"])
    assert odds.loc[(3, "m_b"), "odds"] == 100.0


def test_config_rejects_a_bad_cutoff():
    from engine.config import load_config, validate_config

    cfg = load_config("leagues/preach/league.yaml")
    cfg["analysis"]["playoff_odds"] = {"cutoff": 0}
    assert any("playoff_odds.cutoff" in e for e in validate_config(cfg).errors)


def test_legacy_backtest_reproduces_2020_exactly():
    """2020 is the first season the legacy script simulated, so its random draws
    can be reproduced without running the later seasons."""
    from engine.config import load_config
    from engine.legacy_playoff_odds import check_backtest

    with gzip.open(GOLDEN / "playoff_odds" / "playoff_odds.json.gz", "rt", encoding="utf-8") as f:
        gold = json.load(f)
    md = pd.read_csv(GOLDEN / "matchup_data.csv.gz")
    r = check_backtest(md[md["Season_Year"] == 2020], {"2020": gold["2020"]}, load_config("leagues/preach/league.yaml"))
    assert r.ok, r.render()


def test_legacy_live_week_3_reproduces_exactly():
    from engine.config import load_config
    from engine.legacy_playoff_odds import check_live

    with gzip.open(GOLDEN / "playoff_odds" / "playoff_odds.json.gz", "rt", encoding="utf-8") as f:
        gold = json.load(f)
    with gzip.open(GOLDEN / "records" / "matchups.json.gz", "rt", encoding="utf-8") as f:
        games = json.load(f)
    r = check_live(games, pd.read_csv(GOLDEN / "sos" / "schedule_2026.csv.gz"),
                   pd.read_csv(GOLDEN / "sos" / "projected_sos_weekly_detail.csv.gz"), gold,
                   load_config("leagues/preach/league.yaml"))
    assert r.ok, r.render()
