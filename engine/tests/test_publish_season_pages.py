"""Season pages (PR A8): champions.html now, schedule_release.html next.

CI has no canonical tables, so each view is rebuilt from its golden: the golden
read into engine-shaped rows, the view builder writes it back, and it must equal
the golden. The rules themselves are checked on small synthetic leagues.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from engine.config import load_config
from engine.legacy import name_to_key
from engine.publish.config_json import short_name
from engine.publish.legacy_view import Names
from engine.publish.pages import champions as champ_pub

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = Path(__file__).parent / "golden"
CFG = load_config(ROOT / "leagues" / "preach" / "league.yaml")
LOOKUP = name_to_key(CFG)


def _json(rel):
    with gzip.open(GOLDEN / rel, "rt", encoding="utf-8") as f:
        return json.load(f)


def _names(spellings):
    ctx = SimpleNamespace(cfg=CFG, config={"managers": [{"key": m["id"], "name": m["name"], "short": short_name(m["name"])}
                                                        for m in CFG["managers"]]})
    return Names(ctx, spellings)


def _key(name: str) -> str:
    return LOOKUP[name.strip().lower()]


# ---------------------------------------------------------------- champions

def test_champions_view_rebuilds_the_page():
    gold = _json("champions/champions_inline.json.gz")
    finals = {f["year"]: f for f in gold["FINALS"]}
    runs, teams = [], {}
    for c in sorted(gold["CHAMPS"], key=lambda c: c["year"]):
        w, l, *t = (int(x) for x in c["record"].split("-"))
        k = _key(c["manager"])
        teams[(c["year"], k)] = c["team"]
        rounds = [{"label": r["label"], "week": r["week"], "points": r["total_score"],
                   "opponent_key": _key(c["runner_up"]), "opponent_points": finals[c["year"]]["runner_score"],
                   "starters": [{"slot": "RB/WR/TE" if p["pos"] == "FLEX" else p["pos"], "player_id": i,
                                 "name": p["name"], "position": p["pos"], "points": p["week_score"], "ppg": p["ppg"]}
                                for i, p in enumerate(r["roster"])]} for r in c["rounds"]]
        runs.append({"season": c["year"], "manager_key": k, "wins": w, "losses": l, "ties": t[0] if t else 0,
                     "pf_per_game": c["rs_ppg"], "playoff_ppg": c["po_ppg"], "runner_up_key": _key(c["runner_up"]),
                     "rounds": rounds})
    view = champ_pub.champions_view(runs, teams, _names(champ_pub.spellings(gold)))
    assert view == gold


def _tiny_league():
    """Two teams, a 3-week regular season, then a one-week bye for the champion and a final."""
    a, b = "m_00000000000a", "m_00000000000b"
    ms = pd.DataFrame({"season": [2030, 2030], "manager_key": [a, b], "wins": [2, 1], "losses": [1, 2],
                       "ties": [0, 0], "pf_per_game": [100.0, 90.0], "champion": [True, False]})
    games = pd.DataFrame({"season": [2030, 2030], "week": [4, 5], "is_playoff": [True, True],
                          "team_a_key": [b, a], "team_b_key": ["m_00000000000c", b],
                          "team_a_points": [80.0, 110.5], "team_b_points": [70.0, 99.25]})
    lu = pd.DataFrame([  # player 1: a normal starter; 2: a started zero counts; 3: bye on the bench and IR skipped
        (1, "S", 10.0, True), (2, "S", 20.0, True), (3, "S", 30.0, True), (4, "S", 99.0, True),
        (1, "K", 6.0, True), (2, "K", 0.0, True), (3, "K", 9.0, True),
        (1, "D", 0.0, False), (2, "D", 4.0, False), (3, "D", 50.0, False),
    ], columns=["week", "name", "points", "started"])
    lu = lu.assign(season=2030, manager_key=a, player_id=lu["name"].map({"S": 1, "K": 2, "D": 3}),
                   slot=["RB"] * 4 + ["K"] * 3 + ["BE", "D/ST", "IR"])
    box = pd.DataFrame({"season": 2030, "week": 5, "manager_key": a, "role": "starter", "order": [0, 1, 2],
                        "slot": ["RB/WR/TE", "K", "D/ST"], "player_id": [1, 2, 5], "player_name": ["S", "K", "N"],
                        "position": ["RB", "K", "D/ST"], "points": [40.0, 8.0, 62.5]})
    return ms, games, box, lu


def test_champion_runs_rules():
    ms, games, box, lu = _tiny_league()
    (run,) = champ_pub.champion_runs(ms, games, box, lu, [2030])
    assert run["runner_up_key"] == "m_00000000000b" and run["playoff_ppg"] == 110.5
    (final,) = run["rounds"]                      # the week 4 bye is not a round
    assert final["label"] == "Championship" and final["opponent_points"] == 99.25
    ppg = {p["name"]: p["ppg"] for p in final["starters"]}
    # weeks before the champion's first playoff game (the week 4 bye counts, as the page counted it);
    # K's started zero counts, D's benched zero and IR week do not; N was picked up for the final
    assert ppg == {"S": 39.75, "K": 5.0, "N": None}
    view = champ_pub.champions_view([run], {(2030, run["manager_key"]): "Team"}, lambda k: k)
    assert [p["pos"] for p in view["CHAMPS"][0]["rounds"][0]["roster"]] == ["FLEX", "K", "D/ST"]
    assert view["CHAMPS"][0]["record"] == "2-1" and view["FINALS"][0]["runner_score"] == 99.25


def test_round_names():
    assert [champ_pub.round_name(i, 5) for i in range(5)] == ["Championship", "Semifinal", "Quarterfinal",
                                                              "First Round", "Round 1"]


# ---------------------------------------------------------------- schedule_release

from engine.publish.pages import schedule as sched_pub  # noqa: E402

A, B, C = "m_00000000000a", "m_00000000000b", "m_00000000000c"


def _schedule_history():
    games = pd.DataFrame({
        "season": [2030, 2030, 2030, 2031, 2031], "week": [1, 4, 5, 2, 5],
        "week_label": ["Week 1", "Playoff Round 1", "Playoff Round 2", "Week 2", "Playoff Round 2"],
        "is_playoff": [False, True, True, False, True],
        "team_a_key": [A, A, B, B, A], "team_b_key": [B, C, A, A, B],
        "team_a_points": [100.0, 90.0, 80.0, 70.5, 99.0], "team_b_points": [95.0, 85.0, 120.0, 70.5, 98.0]})
    box = pd.DataFrame([(s, w, k, i, f"P{s}{w}{k[-1]}", "RB", pts)
                        for (s, w, k, pts) in [(2030, 1, A, 40.0), (2030, 1, B, 45.0), (2030, 5, A, 30.0),
                                               (2030, 5, B, 31.0), (2031, 2, A, 20.0), (2031, 2, B, 22.0),
                                               (2031, 5, A, 25.0), (2031, 5, B, 26.0)] for i in [1]],
                       columns=["season", "week", "manager_key", "player_id", "player_name", "position", "points"])
    box = box.assign(role="starter", order=0)
    return sched_pub.history(games, box, [2030, 2031])


def test_schedule_history_labels_and_mvp():
    h = _schedule_history()
    assert list(h["label"]) == ["Week 1", "Semifinal", "Championship", "Week 2", "Championship"]
    mvp = [None if p is None else p.player_name for p in h["mvp"]]
    assert mvp == ["P20301a", None, "P20305a", "P20312b", "P20315a"]   # the winner's best; a tie takes the higher


def test_schedule_views_rules():
    h = _schedule_history()
    sides = pd.DataFrame({"group_id": [1, 1, 2, 2, 3, 3], "season": [2030, 2030, 2031, 2031, 2032, 2032],
                          "manager_key": [A, B, A, B, A, B]})
    trades = sched_pub.trade_counts(sides, 2031)
    assert trades == {frozenset((A, B)): 2}
    pairs = pd.DataFrame({"week": [1, 2], "manager_key": [A, B], "opponent_key": [B, A]})
    model = sched_pub.schedule_model(pairs, {A: "X", B: "Y"}, {2: "Big"}, h, trades, 2032, [2030, 2031])
    assert [w["theme"] for w in model["weeks"]] == [None, "Big"] and model["weeks"][0]["matchups"][0]["interconference"]
    managers, by_week = sched_pub.schedule_views(model, lambda k: k, [A, B], {"Big": "rematch"})
    first, second = managers[A]
    assert (first["my_wins"], first["opp_wins"], first["total_games"]) == (3, 0, 4)
    assert first["game_log"] == ["win", "win", "tie", "win"] and first["week_type"] == "Standard"
    assert first["closest"]["season"] == "2031" and first["closest"]["margin"] == 0.0
    assert first["blowout"] == {"season": "2030", "week": "Playoff Round 2", "score_a": 120.0, "score_b": 80.0,
                                "winner": A, "margin": 40.0}
    assert first["most_recent"]["winner"] == A and first["rematch"] is None and first["trade_count"] is None
    assert second["rematch"] == {"season": "2031", "round": "Championship"}     # deepest, then most recent
    assert managers[B][0]["opp_wins"] == 3 and by_week[1]["week_type"] == "Big"


def test_schedule_golden_records_are_consistent():
    gold = _json("schedule_release/manager_schedule.json.gz")
    for n, entries in gold.items():
        for e in entries:
            res = ["win" if g["winner"] == n else "tie" if g["winner"] == "Tie" else "loss" for g in e["games"]]
            assert res == e["game_log"] and (e["my_wins"], e["total_games"]) == (res.count("win"), len(res))
            if e["week_type"] == "Big Game Week" and e["rematch"]:
                assert any(g["label"] == e["rematch"]["round"] and str(g["season"]) == e["rematch"]["season"]
                           for g in e["games"])


def test_schedule_without_themes_still_makes_every_card(tmp_path):
    """A newly imported league has no schedule_themes.yaml: every matchup still gets its card."""
    ctx = SimpleNamespace(league_dir=tmp_path)
    assert sched_pub.themes(ctx, 2032) == ({}, {})
    h = _schedule_history()
    pairs = pd.DataFrame({"week": [1, 2], "manager_key": [A, B], "opponent_key": [B, A]})
    model = sched_pub.schedule_model(pairs, {}, {}, h, {}, 2032, [2030, 2031])
    managers, by_week = sched_pub.schedule_views(model, lambda k: k, [A, B])
    assert [w["week_type"] for w in by_week] == ["Standard", "Standard"]
    for entries in managers.values():
        for e in entries:
            assert e["total_games"] == 4 and all(g["mvp_name"] for g in e["games"] if g["label"] != "Semifinal")
