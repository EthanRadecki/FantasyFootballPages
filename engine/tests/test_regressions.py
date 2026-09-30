import gzip
import json
from pathlib import Path

import numpy as np
import pandas as pd

from engine.analytics import regressions as rg
from engine.config import load_config
from engine.legacy_regressions import check_positions, check_quarterly

GOLDEN = Path(__file__).parent / "golden"


def test_ols_standardized_coefficients_use_sample_sds():
    rng = np.random.default_rng(0)
    X = pd.DataFrame({"a": rng.normal(size=50), "b": rng.normal(size=50)})
    y = 2 * X["a"].to_numpy() - X["b"].to_numpy() + rng.normal(scale=0.1, size=50)
    fit = rg.ols(y, X)
    assert abs(fit["coef"]["a"] - 2) < 0.1
    assert abs(fit["std_coef"]["a"] - fit["coef"]["a"] * X["a"].std() / y.std(ddof=1)) < 1e-12
    assert fit["n"] == 50 and fit["r2"] > 0.99


def test_logit_score_equations_are_zero_at_the_fit():
    rng = np.random.default_rng(1)
    X = pd.DataFrame({"q1": rng.normal(size=200), "q2": rng.normal(size=200)})
    y = (rng.random(200) < 1 / (1 + np.exp(-(0.8 * X["q1"] - 0.3 * X["q2"])))).astype(float).to_numpy()
    fit = rg.logit(y, X)
    Z = (X - X.mean()) / X.std(ddof=0)
    A = np.column_stack([np.ones(len(Z)), Z.to_numpy()])
    b = np.array([fit["intercept"], fit["coef"]["q1"], fit["coef"]["q2"]])
    p = 1 / (1 + np.exp(-A @ b))
    assert np.abs(A.T @ (y - p)).max() < 1e-8          # maximum likelihood: the gradient vanishes
    assert fit["coef"]["q1"] > 0 > fit["coef"]["q2"] and 0.5 < fit["auc"] <= 1
    assert abs(fit["odds_ratio"]["q1"] - np.exp(fit["coef"]["q1"])) < 1e-12


def test_weekly_position_points_fill_an_empty_position_with_zero():
    lu = pd.DataFrame({"manager_key": "a", "season": 2024, "week": [1, 1, 2], "position": ["QB", "K", "QB"],
                       "points": [20.0, 8.0, 15.0], "started": True})
    wk = rg.weekly_position_points(lu, ["QB", "K"])
    assert wk.loc[("a", 2024, 2), "K"] == 0 and wk.loc[("a", 2024, 1), "QB"] == 20


def test_quarters_follow_the_season_length_in_the_engine():
    assert rg.quarters_for(14, True)[-1] == (10, 14)
    assert rg.quarters_for(14, False)[-1] == (10, 13)
    assert rg.quarters_for(13, True)[-1] == (10, 13)


def test_quarter_averages():
    s = pd.DataFrame({"season": 2024, "manager_key": "a", "week": [1, 2, 4, 10, 14], "points": [90.0, 110, 100, 120, 80]})
    q = rg.quarter_averages(s, rg.quarters_for(14, True)).iloc[0]
    assert q["Q1"] == 100 and q["Q2"] == 100 and pd.isna(q["Q3"]) and q["Q4"] == 100


def goldens():
    g = {"matchup_data": pd.read_csv(GOLDEN / "matchup_data.csv.gz"),
         "weekly_rosters_bracket_only": pd.read_csv(GOLDEN / "weekly_rosters_bracket_only.csv.gz"),
         "preach_manager_stats": pd.read_csv(GOLDEN / "manager_seasons" / "preach_manager_stats.csv.gz")}
    with gzip.open(GOLDEN / "regressions" / "extra_analytics_regressions.json.gz", "rt", encoding="utf-8") as f:
        g["extra_analytics_regressions"] = json.load(f)
    return g


def test_legacy_inputs_reproduce_the_positional_table_and_model():
    for result in check_positions(goldens(), load_config("leagues/preach/league.yaml")):
        assert result.ok, result.render()


def test_legacy_inputs_reproduce_the_quarterly_correlations():
    result = check_quarterly(goldens(), load_config("leagues/preach/league.yaml"))
    assert result.ok, result.render()


def test_league_field_takes_division_winners_then_the_best_records():
    rows = []
    # division 0: a 2-0, b 1-1; division 1: d 1-1, c 0-2. With a cutoff of 2 the field is the two
    # division winners, a and d, although b has the same record as d
    for wk, x, px, y, py in ((1, "a", 100, "c", 90), (1, "b", 95, "d", 80), (2, "a", 100, "b", 90),
                             (2, "d", 110, "c", 70)):
        for m, p, o, op in ((x, px, y, py), (y, py, x, px)):
            rows.append({"season": 2024, "week": wk, "team_id": m, "manager_key": m, "opponent_manager_key": o,
                         "points": float(p), "opponent_points": float(op), "result": "W" if p > op else "L",
                         "is_bye": False, "is_playoff_week": False, "tier": "REGULAR"})
    t = {"matchups": pd.DataFrame(rows),
         "seasons": pd.DataFrame({"season": [2024], "playoff_team_count": [4], "final_scoring_period": [2]}),
         "teams": pd.DataFrame({"season": 2024, "manager_key": list("abcd"), "division_id": [0, 0, 1, 1]})}
    made = rg.league_field(t, cutoff=2).set_index("manager_key")["made"]
    assert made.to_dict() == {"a": 1, "b": 0, "c": 0, "d": 1}
