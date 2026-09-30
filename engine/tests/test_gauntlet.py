import gzip
import json
from pathlib import Path

import numpy as np
import pandas as pd

from engine.analytics import gauntlet as gt
from engine.config import load_config
from engine.legacy_gauntlet import check_legacy

GOLDEN = Path(__file__).parent / "golden"
MGRS = ["a", "b", "c", "d"]


def league(weeks=9, skip=(), season=2024, regular=8):
    """a plays b and c plays d in odd weeks, a-c and b-d in even weeks.
    Scores rise by week so surges are positive late in the season."""
    rows = []
    for wk in range(1, weeks + 1):
        pairs = [("a", "b"), ("c", "d")] if wk % 2 else [("a", "c"), ("b", "d")]
        for x, y in pairs:
            if (wk, x) in skip or (wk, y) in skip:
                continue
            px, py = 100 + wk + MGRS.index(x), 90 + wk + MGRS.index(y)
            for m, o, p, op in ((x, y, px, py), (y, x, py, px)):
                rows.append({"season": season, "week": wk, "week_label": f"Week {wk}", "is_regular": wk <= regular,
                             "manager_key": m, "opponent_key": o, "points": float(p), "opponent_points": float(op)})
    return pd.DataFrame(rows)


def dominance(season=2024, values=(1.0, 0.5, -0.5, -1.0)):
    return pd.DataFrame({"season": season, "manager_key": MGRS, "dominance": list(values)})


def test_surge_is_the_last_five_games_against_the_regular_season_average():
    g = league()
    s = gt.surges(g)
    a = g[g["manager_key"] == "a"].sort_values("week")
    reg = a[a["is_regular"]]["points"].mean()
    assert abs(s[(2024, "a", 6)] - (a["points"].iloc[0:5].mean() - reg)) < 1e-12
    assert (2024, "a", 5) not in s                    # needs five earlier games


def test_windows_start_at_the_sixth_game_and_need_consecutive_weeks():
    win, _ = gt.windows(league(), dominance(), sizes=(3,))
    assert win[win["manager_key"] == "a"]["start_week"].tolist() == [6, 7]
    broken, _ = gt.windows(league(skip={(7, "a")}), dominance(), sizes=(3,))
    assert broken[broken["manager_key"] == "a"].empty   # week 7 missing: no three consecutive weeks from game 6


def test_window_score_is_the_weighted_logistic_of_shrunk_averages():
    g, d = league(), dominance()
    win, detail = gt.windows(g, d, sizes=(3,))
    r = win[(win["manager_key"] == "a") & (win["start_week"] == 6)].iloc[0]
    pts = g["points"].to_numpy()
    w = detail[(detail["manager_key"] == "a") & (detail["start_week"] == 6)]
    zp = ((w["opp_score"] - pts.mean()) / pts.std()).mean()
    assert abs(r["s_pts"] - gt.logistic(zp * 0.75)) < 1e-12
    assert abs(r["gs"] - (0.7 * r["s_pts"] + 0.15 * r["s_dom"] + 0.15 * r["s_streak"])) < 1e-12


def test_ties_share_a_rank_in_the_engine():
    win, _ = gt.windows(league(), dominance(values=(0, 0, 0, 0)), sizes=(3,))
    assert win["rank"].min() == 1 and (win["total"] == len(win)).all()


def test_champion_run_comes_from_the_bracket_and_a_bye_shortens_it():
    g = league(weeks=11, skip={(9, "a")}, regular=8)         # a has a first-round bye
    teams = pd.DataFrame({"season": 2024, "manager_key": MGRS, "final_rank": [1, 2, 3, 4]})
    runs = gt.champion_runs({"teams": teams}, g)
    assert runs == [(2024, "a", ["c", "b"])]


def test_extremes_hide_excluded_managers():
    win, _ = gt.windows(league(), dominance(), sizes=(3,))
    win["hidden"] = win["manager_key"].eq("a")
    hi, lo = gt.extremes(win, k=10)
    assert "a" not in set(hi["manager_key"]) | set(lo["manager_key"])


def test_legacy_inputs_reproduce_the_page():
    g = {"matchup_data": pd.read_csv(GOLDEN / "matchup_data.csv.gz"),
         "preach_manager_stats": pd.read_csv(GOLDEN / "manager_seasons" / "preach_manager_stats.csv.gz")}
    with gzip.open(GOLDEN / "gauntlet" / "extra_analytics_gauntlet.json.gz", "rt", encoding="utf-8") as f:
        g["extra_analytics_gauntlet"] = json.load(f)
    for result in check_legacy(g, load_config("leagues/preach/league.yaml")):
        assert result.ok, result.render()
