from pathlib import Path

import pandas as pd

from engine.analytics import manager_seasons as ms
from engine.config import conference_labels, excluded_games, load_config, validate_config
from engine.legacy import name_to_key, resolve_names
from engine.legacy_manager_seasons import check_finished

GOLDEN = Path(__file__).parent / "golden"
A, B, C, D, X = "m_a", "m_b", "m_c", "m_d", "m_x"


def game(wk, a, pa, b, pb, season=2024, regular_weeks=3, tier=None):
    tier = tier or ("REGULAR" if wk <= regular_weeks else "WINNERS_BRACKET")
    rows = []
    for m, p, o, op in ((a, pa, b, pb), (b, pb, a, pa)):
        rows.append({"season": season, "week": wk, "team_id": m, "manager_key": m, "opponent_manager_key": o,
                     "points": float(p), "opponent_points": float(op),
                     "result": "W" if p > op else ("L" if p < op else "T"), "is_bye": False,
                     "is_playoff_week": wk > regular_weeks, "tier": tier})
    return rows


def bye(wk, m, season=2024):
    return [{"season": season, "week": wk, "team_id": m, "manager_key": m, "opponent_manager_key": None,
             "points": 0.0, "opponent_points": 0.0, "result": "BYE", "is_bye": True, "is_playoff_week": False,
             "tier": "REGULAR"}]


def tables(rows, final_week=4, regular_weeks=3, final_rank=None, managers=(A, B, C, D, X)):
    m = pd.DataFrame(rows)
    seasons = pd.DataFrame({"season": [2024], "regular_season_periods": [regular_weeks],
                            "playoff_team_count": [2], "final_scoring_period": [final_week]})
    ranks = final_rank or {k: i + 1 for i, k in enumerate(managers)}
    teams = pd.DataFrame({"season": 2024, "team_id": list(managers), "team_name": [f"Team  {k}" for k in managers],
                          "division_id": 0, "division_name": "East", "final_rank": [ranks[k] for k in managers],
                          "playoff_seed": [ranks[k] for k in managers]})
    picks = pd.DataFrame({"season": 2024, "manager_key": list(managers), "draft_slot": range(1, len(managers) + 1)})
    return {"matchups": m, "seasons": seasons, "teams": teams, "draft_picks": picks}


FINAL = game(4, A, 1, B, 2)   # the final, so the season is finished


def test_records_use_finished_regular_season_games_only():
    t = tables(game(1, A, 100, B, 90) + game(2, A, 80, C, 120) + game(3, A, 110, D, 100) + FINAL
               + game(4, C, 50, D, 60, tier="LOSERS_CONSOLATION_LADDER"), managers=(A, B, C, D))
    a = ms.manager_seasons(t).set_index("manager_key").loc[A]
    assert (a["wins"], a["losses"], a["games"]) == (2, 1, 3)
    assert a["points_for"] == 290 and a["pa_per_game"] == 310 / 3
    assert a["win_pct"] == 2 / 3


def test_dominance_is_a_sample_z_score_counting_hidden_managers():
    t = tables(game(1, A, 100, B, 90) + game(1, C, 80, X, 130) + FINAL)
    out = ms.manager_seasons(t, {X}).set_index("manager_key")
    pfg = pd.Series({A: 100, B: 90, C: 80, X: 130}, dtype=float)
    z = (pfg - pfg.mean()) / pfg.std(ddof=1)
    assert abs(out.loc[A, "dominance"] - z[A]) < 1e-12 and abs(out.loc[X, "dominance"] - z[X]) < 1e-12
    assert out.loc[X, "hidden"]


def test_ranks_count_visible_managers_and_luck_is_pf_rank_minus_pa_rank():
    # A scored 100 (2nd of the visible three), allowed 90 (fewest among visible after X is left out)
    t = tables(game(1, A, 100, B, 90) + game(1, C, 80, X, 130) + FINAL)
    eng = ms.manager_seasons(t, {X}).set_index("manager_key")
    leg = ms.manager_seasons(t, {X}, legacy_mode=True).set_index("manager_key")
    assert eng.loc[A, "pf_rank"] == 1 and leg.loc[A, "pf_rank"] == 2      # X's 130 ranked first in legacy
    assert pd.isna(eng.loc[X, "pf_rank"])
    assert eng.loc[C, "luck_rating"] == eng.loc[C, "pf_rank"] - eng.loc[C, "pa_rank"]


def test_tied_values_share_the_best_rank():
    t = tables(game(1, A, 100, B, 90) + game(1, C, 100, D, 80) + FINAL, managers=(A, B, C, D))
    out = ms.manager_seasons(t).set_index("manager_key")
    assert out.loc[A, "pf_rank"] == out.loc[C, "pf_rank"] == 1


def test_ppg_exclusion_leaves_the_forfeit_out_of_pf_per_game_only():
    t = tables(game(1, A, 100, B, 90) + game(2, A, 0, B, 120) + FINAL, managers=(A, B, C, D))
    eng = ms.manager_seasons(t, ppg_exclusions={(2024, 2, A)}).set_index("manager_key")
    leg = ms.manager_seasons(t, ppg_exclusions={(2024, 2, A)}, legacy_mode=True).set_index("manager_key")
    assert eng.loc[A, "pf_per_game"] == 100 and leg.loc[A, "pf_per_game"] == 50
    assert eng.loc[A, "losses"] == 1 and eng.loc[A, "pa_per_game"] == 105


def test_legacy_differential_divides_by_weeks_played_including_a_bye():
    t = tables(game(1, A, 100, B, 90) + bye(2, A) + game(2, B, 90, C, 80) + FINAL, managers=(A, B, C, D))
    eng = ms.manager_seasons(t).set_index("manager_key")
    leg = ms.manager_seasons(t, legacy_mode=True).set_index("manager_key")
    assert eng.loc[A, "games"] == 1 and eng.loc[A, "point_diff_per_game"] == 10
    assert leg.loc[A, "point_diff_per_game"] == 5


def test_live_season_has_no_placement_and_finished_season_does():
    live = tables(game(1, A, 100, B, 90) + [dict(r, result=None) for r in FINAL])   # final not decided
    out = ms.manager_seasons(live).set_index("manager_key")
    assert out.loc[A, "is_live"] and pd.isna(out.loc[A, "final_rank"]) and pd.isna(out.loc[A, "made_playoffs"])
    done = ms.manager_seasons(tables(game(1, A, 100, B, 90) + game(1, C, 80, D, 70) + FINAL,
                                     managers=(A, B, C, D))).set_index("manager_key")
    assert done.loc[A, "final_rank"] == 1 and done.loc[A, "champion"] and not done.loc[C, "made_playoffs"]
    assert done.loc[A, "team_name"] == "Team m_a"      # ESPN double spaces collapsed


def test_excluded_games_reads_the_ppg_scope_from_league_yaml():
    cfg = load_config("leagues/preach/league.yaml")
    keys = {m["name"]: m["id"] for m in cfg["managers"]}
    assert excluded_games(cfg, "ppg") == {(2024, 14, keys["Ben Castaldo"])}
    assert excluded_games(cfg, "records") == set()


def test_conference_is_the_stable_label_for_the_division_id_whatever_espn_named_it():
    t = tables(game(1, A, 100, B, 90) + FINAL)
    out = ms.manager_seasons(t, conference_labels={0: "REP"}).set_index("manager_key")
    assert out.loc[A, "conference"] == "REP" and out.loc[A, "division_name"] == "East"
    assert ms.manager_seasons(t).set_index("manager_key").loc[A, "conference"] is None
    cfg = load_config("leagues/preach/league.yaml")
    assert conference_labels(cfg) == {0: "REP", 1: "DEM"}
    bad = dict(cfg, league=dict(cfg["league"], conference_labels={"East": "REP"}))
    assert not validate_config(bad).ok


def legacy_tables():
    """Canonical-shaped tables from the legacy matchup_data.csv, with the
    ESPN-only columns (placement, seeds, draft slot) taken from the stats
    file itself, so the computed columns are checked in CI."""
    cfg = load_config("leagues/preach/league.yaml")
    lk = name_to_key(cfg)
    md = pd.read_csv(GOLDEN / "matchup_data.csv.gz")
    stats = pd.read_csv(GOLDEN / "manager_seasons" / "preach_manager_stats.csv.gz")
    stats = stats[stats["Year"] <= md["Season_Year"].max()]
    num = md["Week"].str.extract(r"(\d+)$")[0].astype(int)
    playoff = md["Week"].str.startswith("Playoff")
    reg = num[~playoff].groupby(md["Season_Year"][~playoff]).max()
    week = num.where(~playoff, md["Season_Year"].map(reg) + num)
    key = resolve_names(md["Team_Name"], lk)
    m = pd.DataFrame({
        "season": md["Season_Year"].astype(int), "week": week, "team_id": key, "manager_key": key,
        "opponent_manager_key": resolve_names(md["Opponent_Name"], lk),
        "points": md["Team_Score"].astype(float), "opponent_points": md["Opponent_Score"].astype(float),
        "result": md["Outcome"].map({"Win": "W", "Loss": "L", "Tie": "T"}), "is_bye": False,
        "is_playoff_week": playoff, "tier": playoff.map({True: "WINNERS_BRACKET", False: "REGULAR"})})
    final = week.groupby(md["Season_Year"]).max()
    seasons = pd.DataFrame({"season": reg.index.astype(int), "regular_season_periods": reg.to_numpy(),
                            "final_scoring_period": final.to_numpy(), "playoff_team_count": 99})
    skey = resolve_names(stats["Manager"], lk)
    teams = pd.DataFrame({"season": stats["Year"].astype(int), "team_id": skey, "team_name": stats["Team"],
                          "division_id": stats["Conference"].map({"REP": 0, "DEM": 1}), "division_name": None,
                          "final_rank": stats["Placement_within_Year"],
                          "playoff_seed": stats["Playoffs"].map({1: 1, 0: 999})})
    picks = pd.DataFrame({"season": stats["Year"].astype(int), "manager_key": skey, "draft_slot": stats["Draft_Slot"]})
    return {"matchups": m, "seasons": seasons, "teams": teams, "draft_picks": picks}, md, stats, cfg


def test_legacy_mode_reproduces_the_legacy_stats_file():
    t, md, stats, cfg = legacy_tables()
    result = check_finished(t, stats, md, cfg, live=set())   # conference compared via league.yaml labels
    assert result.ok, result.render()
    assert result.expected_rows == 85
