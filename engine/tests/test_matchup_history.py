import pandas as pd

from engine.analytics import matchup_history as mh
from engine.analytics.records import games as record_games

A, B, C, D, X = "m_a", "m_b", "m_c", "m_d", "m_x"
DIV = {A: 0, B: 0, C: 1, D: 1, X: 1}          # A, B in conference 0 (REP); C, D, X in 1 (DEM)
LABELS = {0: "REP", 1: "DEM"}
TID = {A: 1, B: 2, C: 3, D: 4, X: 5}


def game(wk, a, pa, b, pb, season=2024, regular=3, tier=None, gid=None):
    tier = tier or ("REGULAR" if wk <= regular else "WINNERS_BRACKET")
    gid = gid or wk * 100 + TID[a] * 10 + TID[b]
    out = []
    for m, p, o, op in ((a, pa, b, pb), (b, pb, a, pa)):
        out.append({"season": season, "week": wk, "matchup_period": wk, "game_id": gid, "team_id": TID[m],
                    "manager_key": m, "opponent_manager_key": o, "points": float(p), "opponent_points": float(op),
                    "result": "W" if p > op else ("L" if p < op else "T"), "is_bye": False,
                    "is_playoff_week": wk > regular, "tier": tier})
    return out


def tables(rows, managers=(A, B, C, D), final_rank=None, seeds=None):
    ranks = final_rank or {k: i + 1 for i, k in enumerate(managers)}
    seeds = seeds or ranks
    return {"matchups": pd.DataFrame(rows),
            "seasons": pd.DataFrame({"season": [2024], "regular_season_periods": [3], "playoff_team_count": [2],
                                     "final_scoring_period": [4]}),
            "teams": pd.DataFrame({"season": 2024, "team_id": [TID[k] for k in managers], "manager_key": list(managers),
                                   "team_name": [f"T{k}" for k in managers], "division_id": [DIV[k] for k in managers],
                                   "final_rank": [ranks[k] for k in managers], "playoff_seed": [seeds[k] for k in managers]})}


def season_rows():
    return (game(1, A, 100, C, 90) + game(1, B, 80, D, 95) + game(2, A, 0, D, 120) + game(2, B, 110, C, 100)
            + game(3, A, 105, B, 104.9) + game(3, C, 99, D, 98) + game(4, A, 130, B, 120))


def test_head_to_head_counts_a_forfeit_loss():
    h = mh.head_to_head(tables(season_rows())).set_index(["manager_key", "opponent_key"])
    assert (h.loc[(A, D), "wins"], h.loc[(A, D), "losses"]) == (0, 1)
    assert h.loc[(A, B), "games"] == 2 and h.loc[(A, B), "wins"] == 2


def test_closest_scopes():
    g = record_games(tables(season_rows()))
    assert mh.closest(g, "all", 1).iloc[0]["margin"] == 0.1
    assert mh.closest(g, "playoff", 5)["margin"].tolist() == [10.0]
    assert not mh.closest(g, "regular", 10)["is_playoff"].any()


def test_conference_records_count_interconference_games_only():
    res = mh.conference_tables(tables(season_rows()), LABELS)
    m = res["conference_managers"].set_index("manager_key")
    assert (m.loc[A, "wins"], m.loc[A, "losses"]) == (1, 1) and m.loc[A, "conference"] == "REP"
    s = res["conference_summary"].set_index("conference")
    assert s.loc["REP", "wins_regular"] == 2 and s.loc["DEM", "wins_regular"] == 2
    assert s.loc["REP", "titles"] == 1 and s.loc["REP", "playoff_trips"] == 2 and s.loc["DEM", "playoff_trips"] == 0


def test_ppg_exclusion_engine_drops_only_the_forfeiters_points():
    ppg = {(2024, 2, A)}
    eng = mh.conference_tables(tables(season_rows()), LABELS, ppg_exclusions=ppg)["conference_managers"].set_index("manager_key")
    leg = mh.conference_tables(tables(season_rows()), LABELS, ppg_exclusions=ppg,
                               legacy_mode=True)["conference_managers"].set_index("manager_key")
    assert eng.loc[A, "pf_per_game"] == 100 and eng.loc[A, "pa_per_game"] == 105   # 90 and 120 allowed
    assert leg.loc[A, "pa_per_game"] == 90                                         # legacy dropped the whole game
    assert eng.loc[D, "pf_per_game"] == 107.5 and leg.loc[D, "pf_per_game"] == 95   # D's 120 counts in the engine
    assert eng.loc[D, "pa_per_game"] == 80                                          # A's 0 is not D's PA
    assert eng.loc[A, "losses"] == leg.loc[A, "losses"] == 1


def test_excluded_managers_count_but_are_hidden():
    rows = season_rows() + game(1, X, 200, B, 50, gid=999)
    t = tables(rows, managers=(A, B, C, D, X))
    eng = mh.conference_tables(t, LABELS, {X})["conference_managers"].set_index("manager_key")
    leg = mh.conference_tables(t, LABELS, {X}, legacy_mode=True)["conference_managers"].set_index("manager_key")
    assert eng.loc[B, "losses"] == leg.loc[B, "losses"] + 1
    assert eng.loc[X, "hidden"] and X not in leg.index


def test_rivalries_order_by_meetings_then_closeness_then_names():
    riv = pd.DataFrame({"manager_key": [A, A, B], "opponent_key": [B, C, C], "wins": [3, 2, 2], "losses": [1, 2, 2],
                        "ties": 0, "games": [4, 4, 4], "hidden": False})
    names = {A: "Zed", B: "Amy", C: "Bob"}
    out = mh.order_rivalries(riv, names)
    assert list(zip(out["first_name"], out["second_name"])) == [("Amy", "Bob"), ("Bob", "Zed"), ("Amy", "Zed")]
    assert (out.loc[2, "first_wins"], out.loc[2, "second_wins"]) == (1, 3)     # written from Amy's side
