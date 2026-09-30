import gzip
import json
from pathlib import Path

import numpy as np
import pandas as pd

from engine.analytics import attribution as attr
from engine.config import load_config
from engine.legacy_attribution import check_factors, check_fit

GOLDEN = Path(__file__).parent / "golden"


def rows(values):
    return pd.DataFrame([{"season": s, "manager_key": m, "value": v} for s, m, v in values])


def test_factor_table_totals_each_input():
    wp = pd.DataFrame({"season": [2024, 2024], "manager_key": ["a", "b"], "win_pct": [0.6, 0.4]})
    out = attr.factor_table(
        wp,
        draft=rows([(2024, "a", 3.0), (2024, "a", -1.0), (2024, "b", 1.0)]),
        waiver=rows([(2024, "a", 2.0), (2024, "a", -5.0), (2024, "b", -1.0)]),     # upside only
        lineup=rows([(2024, "a", 1.0), (2024, "a", 0.0), (2024, "b", 1.0), (2024, "b", 1.0)]),
        trade=rows([(2024, "a", 0.7)]),                                           # b made no trades
        luck=rows([(2024, "a", 1.0), (2024, "b", -1.0)])).set_index("manager_key")
    assert out.loc["a", "draft_value"] == 2 and out.loc["a", "waiver_value"] == 2 and out.loc["b", "waiver_value"] == 0
    assert out.loc["a", "lineup_value"] == -1 and out.loc["b", "lineup_value"] == -2
    assert out.loc["b", "trade_value"] == 0 and out.loc["a", "schedule_luck"] == 1


def test_factor_table_drops_seasons_missing_an_input():
    wp = pd.DataFrame({"season": [2024, 2026], "manager_key": ["a", "a"], "win_pct": [0.5, 1.0]})
    one = rows([(2024, "a", 1.0)])
    out = attr.factor_table(wp, one, one, one, one, one)
    assert out["season"].tolist() == [2024]     # the live season has no luck or draft value yet


def synthetic(n=40, seed=3):
    rng = np.random.default_rng(seed)
    df = pd.DataFrame({f: rng.normal(size=n) for f in attr.FACTORS})
    df["win_pct"] = (50 + df[attr.FACTORS].to_numpy() @ np.array([4.0, 2.0, 3.0, 1.0, 2.5])) / 100
    df["season"], df["manager_key"], df["hidden"] = 2024, [f"m{i % 8}" for i in range(n)], False
    return df


def test_fit_recovers_exact_coefficients_and_contributions_add_up():
    res = attr.fit(synthetic())
    c = res["attribution_coefficients"].set_index("factor")["coef"]
    assert np.allclose(c.to_numpy(), [4.0, 2.0, 3.0, 1.0, 2.5])
    assert abs(res["attribution_fit"].iloc[0]["r2"] - 1) < 1e-12
    m = res["attribution_managers"]
    parts = m[["draft", "waiver", "lineup", "trade", "luck"]].sum(axis=1)
    assert np.allclose(m["predicted"], res["attribution_fit"].iloc[0]["league_intercept"] + parts)
    assert np.allclose(m["residual"], m["win_pct"] - m["predicted"])


def test_standardized_coefficient_sd_choice():
    df = synthetic()
    df["win_pct"] += np.random.default_rng(1).normal(scale=0.02, size=len(df))
    eng = attr.fit(df)["attribution_coefficients"]["std_coef"].to_numpy()
    leg = attr.fit(df, sample_sd=False)["attribution_coefficients"]["std_coef"].to_numpy()
    n = len(df)
    assert np.allclose(leg / eng, np.sqrt(n / (n - 1)))   # legacy divided by the population SD of win%


def test_hidden_managers_are_in_the_fit_and_flagged():
    df = synthetic()
    df.loc[df["manager_key"] == "m0", "hidden"] = True
    res = attr.fit(df)
    assert res["attribution_fit"].iloc[0]["n"] == len(df)
    m = res["attribution_managers"].set_index("manager_key")
    assert m.loc["m0", "hidden"] and not m.loc["m1", "hidden"]


def goldens():
    g = {"matchup_data": pd.read_csv(GOLDEN / "matchup_data.csv.gz"),
         "draft_surplus_v2": pd.read_csv(GOLDEN / "draft" / "draft_surplus_v2.csv.gz"),
         "waiver_stints_full": pd.read_csv(GOLDEN / "waivers" / "waiver_stints_full.csv.gz"),
         "lineup_efficiency": pd.read_csv(GOLDEN / "trades" / "lineup_efficiency.csv.gz"),
         "metrics_final": pd.read_csv(GOLDEN / "trades" / "metrics_final.csv.gz"),
         "schedule_luck_season": pd.read_csv(GOLDEN / "schedule" / "schedule_luck_season.csv.gz"),
         "attribution_season_data_final": pd.read_csv(GOLDEN / "attribution" / "attribution_season_data_final.csv.gz")}
    with gzip.open(GOLDEN / "attribution" / "win_attribution_final.json.gz", "rt", encoding="utf-8") as f:
        g["win_attribution_final"] = json.load(f)
    return g


def test_legacy_inputs_reproduce_the_published_factor_table():
    result = check_factors(goldens(), load_config("leagues/preach/league.yaml"))
    assert result.ok, result.render()
    assert result.expected_rows == 83


def test_published_factor_table_reproduces_the_published_model():
    for result in check_fit(goldens(), load_config("leagues/preach/league.yaml")):
        assert result.ok, result.render()
