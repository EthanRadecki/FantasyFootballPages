"""Page publishers (PR A2): games and managers.

The legacy-view tests rebuild each current site file from its golden: the
golden is read into engine-shaped rows, the view builder writes it back, and
the result must equal the golden. That proves each builder reshapes faithfully;
`engine build --verify` then feeds them the real legacy-mode analysis.
"""

from __future__ import annotations

import gzip
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from engine.config import load_config
from engine.legacy import name_to_key
from engine.legacy_manager_seasons import legacy_frame
from engine.publish.config_json import short_name
from engine.publish.legacy_view import Names, spellings
from engine.publish.pages import games as games_pub
from engine.publish.pages import managers as mgr_pub

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = Path(__file__).parent / "golden"
CFG = load_config(ROOT / "leagues" / "preach" / "league.yaml")
LOOKUP = name_to_key(CFG)


def _json(rel):
    with gzip.open(GOLDEN / rel, "rt", encoding="utf-8") as f:
        return json.load(f)


def _ctx():
    return SimpleNamespace(cfg=CFG, config={"managers": [{"key": m["id"], "name": m["name"], "short": short_name(m["name"])}
                                                         for m in CFG["managers"]]})


def _regular(season: int) -> int:
    return 13 if season in (2020, 2021) else 14


SEASONS = pd.DataFrame({"season": range(2020, 2027), "regular_season_periods": [_regular(s) for s in range(2020, 2027)],
                        "final_scoring_period": 17})


# ---------------------------------------------------------------- names

def test_names_use_the_legacy_files_spelling_then_config():
    names = Names(_ctx(), ["Carmine Pittelli Jr.", "Ryan P McQuaid", "not a manager"])
    carmine, ryan, ethan = (LOOKUP[n] for n in ("carmine pittelli", "ryan mcquaid", "ethan radecki"))
    assert names(carmine) == "Carmine Pittelli Jr." and names(ryan) == "Ryan P McQuaid"
    assert names(ethan) == "Ethan Radecki" and names.short(carmine) == "Pittelli"
    assert spellings(["Carmine Pittelli", "Carmine Pittelli Jr."], CFG) == {carmine: "Carmine Pittelli"}


# ---------------------------------------------------------------- games

def _frames_from_matchups_json(data):
    games, box, pid = [], [], {}
    for i, g in enumerate(data):
        row = {"season": g["season"], "week": g["week"], "game_id": i, "week_label": g["weekLabel"],
               "is_playoff": g["isPlayoff"], "margin": g["margin"], "combined": g["combined"]}
        for s, side in (("a", "teamA"), ("b", "teamB")):
            t = g[side]
            key = LOOKUP[t["manager"].strip().lower()]
            row |= {f"team_{s}_key": key, f"team_{s}_id": 0, f"team_{s}_name": t["fantasyTeam"],
                    f"team_{s}_points": t["score"], f"team_{s}_result": {"Win": "W", "Loss": "L", "Tie": "T"}[t["outcome"]]}
            for role, players in (("starter", t["starters"]), ("bench", t["bench"])):
                for order, p in enumerate(players):
                    box.append({"season": g["season"], "week": g["week"], "manager_key": key,
                                "player_id": pid.setdefault(p["name"], len(pid) + 1), "player_name": p["name"],
                                "position": p["pos"], "slot": p["slot"], "points": p["pts"], "role": role,
                                "order": order})
        games.append(row)
    return pd.DataFrame(games), pd.DataFrame(box)


def test_matchups_view_rebuilds_the_site_file():
    gold = _json("records/matchups.json.gz")
    games, box = _frames_from_matchups_json(gold)
    names = Names(_ctx(), [g[s]["manager"] for g in gold for s in ("teamA", "teamB")])
    assert games_pub.matchups_view(games, box, names) == gold


def test_matchups_model_keys_rounds_and_superlatives():
    gold = _json("records/matchups.json.gz")
    games, box = _frames_from_matchups_json(gold)
    ctx = SimpleNamespace(cfg=CFG, config={"seasons": [{"season": s, "rounds": {"14": "The Round of 15"} if s == 2020
                                                        else {"15": "Quarterfinals"}} for s in range(2020, 2027)]})
    model = games_pub.matchups_model(ctx, games, box)["games"]
    assert len(model) == len(gold)
    first_po = next(g for g in model if g["is_playoff"] and g["season"] == 2020)
    assert first_po["round"] == "The Round of 15" and model[0]["round"] is None
    assert all(len(g["teams"]) == 2 and g["teams"][0]["manager_key"].startswith("m_") for g in model)
    flagged = [g for g in model if g["superlative_excluded"]]
    assert [(g["season"], g["week"]) for g in flagged] == [(2024, 14)]      # the forfeit, from league.yaml


def _canonical_from_matchup_data(md: pd.DataFrame) -> dict:
    p = games_pub.parse_matchup_data(md, {"seasons": SEASONS}, CFG)
    playoff_week = p["week"] > p["season"].map(_regular)
    p["tier"] = p["tier"].where(p["tier"] == "WINNERS_BRACKET",
                                playoff_week.map({True: "LOSERS_CONSOLATION_LADDER", False: "REGULAR"}))
    p["is_playoff_week"] = playoff_week
    p["game_id"] = p.groupby(["season", "week"]).cumcount() // 2
    p["team_id"] = range(len(p))
    return {"matchups": p, "seasons": SEASONS}


def test_matchup_data_view_rebuilds_the_site_file():
    gold = pd.read_csv(GOLDEN / "matchup_data.csv.gz")
    tables = _canonical_from_matchup_data(gold)
    names = Names(_ctx(), gold["Team_Name"])
    text = games_pub.matchup_data_view(tables, names)
    assert text.startswith(",Team_Name,Outcome,Team_Score,Opponent_Name,Opponent_Score,Week,Season_Year,Is_Playoff\n")
    r = games_pub.check_matchup_data_view(text, gold, tables, CFG)
    assert r.ok, r.render()
    back = pd.read_csv(io.StringIO(text))
    assert len(back) == len(gold) and back.iloc[:, 0].tolist() == list(range(1, len(gold) + 1))


# ---------------------------------------------------------------- managers: legacy views

def test_stats_view_rebuilds_the_site_file():
    gold = pd.read_csv(GOLDEN / "manager_seasons" / "preach_manager_stats.csv.gz")
    lf = legacy_frame(gold, CFG)
    ms = lf.assign(team_name=gold["Team"], ties=0, is_live=lf["season"].eq(2026), playoff_seed=lf["final_rank"],
                   final_rank=lf["final_rank"].where(~lf["season"].eq(2026)))
    names = Names(_ctx(), gold["Manager"])
    text = mgr_pub.stats_view(ms, names)
    back = pd.read_csv(io.StringIO(text))
    assert list(back.columns) == mgr_pub.STATS_COLUMNS and len(back) == len(gold)
    assert back[["Rank_Win%_Overall", "Weighted_Rank_Overall_Value"]].isna().all().all()
    cols = ["Year", "Placement_within_Year", "Manager", "Conference", "W", "L", "GP", "PF", "PA",
            "PF/G_Rank_within_Year", "PA/G_Rank_within_Year", "Luck_Rating", "Playoffs", "Champ_App", "Champ_W", "Draft_Slot"]
    key = lambda d: d.sort_values(["Year", "Manager"]).reset_index(drop=True)
    pd.testing.assert_frame_equal(key(back)[cols], key(gold)[cols], check_dtype=False)
    for c in ("W%", "PF/G", "PA/G", "LR_zscore", "Dominance_Score", "DIFF"):
        assert (key(back)[c] - key(gold)[c]).abs().max() < 1e-8, c


def _per_manager_frame(data: dict) -> pd.DataFrame:
    return pd.DataFrame([dict(r, manager_key=LOOKUP[m.strip().lower()], player_name=r["player"])
                         for m, rows in data.items() for r in rows])


def _sorted(view: dict, keys) -> dict:
    return {m: sorted(rows, key=lambda r: tuple(r[k] for k in keys)) for m, rows in view.items()}


def test_franchise_and_best_week_views_rebuild_the_site_files():
    for rel, fn, keys in (("records/franchise_leaders.json.gz", mgr_pub.franchise_view, ["season", "player", "position"]),
                          ("records/best_single_week.json.gz", mgr_pub.best_week_view, ["season", "week", "player"])):
        gold = _json(rel)
        view = fn(_per_manager_frame(gold), Names(_ctx(), gold))
        assert _sorted(view, keys) == _sorted(gold, keys), rel
    bw = mgr_pub.best_week_view(_per_manager_frame(_json("records/best_single_week.json.gz")), Names(_ctx(), []))
    pts = [r["points"] for r in next(iter(bw.values()))]
    assert pts == sorted(pts, reverse=True)


def test_roster_stint_view_rebuilds_the_site_file():
    gold = _json("waivers/roster_stints.json.gz")
    rs = pd.DataFrame([{"manager_key": LOOKUP[m.strip().lower()], "player_id": 0, "player_name": p,
                        "position": v["position"], "season": s["season"], "start": s["start"], "end": s["end"],
                        "started": ",".join(str(w) for w in s["started"]), "hidden": False}
                       for m, d in gold.items() for p, v in d.items() for s in v["stints"]])
    view = mgr_pub.roster_stint_view(rs, Names(_ctx(), gold))
    norm = lambda d: {m: {p: {"position": v["position"], "stints": sorted(v["stints"], key=lambda s: (s["season"], s["start"]))}
                          for p, v in x.items()} for m, x in d.items()}
    assert norm(view) == norm(gold)


# ---------------------------------------------------------------- managers: page model pieces

def _ms(rows):
    base = {"ties": 0, "made_playoffs": False, "champion": False, "pf_per_game": 100.0, "pa_z": 0.0, "is_live": False,
            "team_name": "T"}
    return pd.DataFrame([base | r for r in rows]).astype({"made_playoffs": "boolean", "champion": "boolean"})


def test_career_ranks_visible_managers_and_picks_seasons_stably():
    ms = _ms([
        {"manager_key": "m_a", "season": 2024, "wins": 10, "losses": 4, "champion": True, "made_playoffs": True},
        {"manager_key": "m_a", "season": 2025, "wins": 10, "losses": 4},
        {"manager_key": "m_a", "season": 2026, "wins": 1, "losses": 1, "is_live": True, "champion": None,
         "made_playoffs": None},
        {"manager_key": "m_b", "season": 2024, "wins": 4, "losses": 10, "pf_per_game": 120.0},
        {"manager_key": "m_h", "season": 2024, "wins": 14, "losses": 0},            # hidden, best record
    ])
    c = mgr_pub.career(ms, {"m_h"}).set_index("manager_key")
    assert list(c.index) == ["m_a", "m_b"]
    a = c.loc["m_a"]
    assert (a["wins"], a["losses"], a["championships"], a["playoffs"]) == (21, 9, 1, 1)
    assert a["best_season"]["season"] == 2024 and a["worst_season"]["season"] == 2026
    assert a["rank_win_pct"] == 1 and c.loc["m_b"]["rank_avg_pf_per_game"] == 1
    model = mgr_pub.index_model(None, ms, {"m_h"})
    assert model["champion"]["season"] == 2024 and model["visible_managers"] == 2


def test_rivals_break_ties_by_games_then_key():
    h = pd.DataFrame([{"opponent_key": "m_b", "wins": 2, "losses": 0, "ties": 0, "games": 2},
                      {"opponent_key": "m_c", "wins": 4, "losses": 0, "ties": 0, "games": 4},
                      {"opponent_key": "m_d", "wins": 0, "losses": 3, "ties": 0, "games": 3},
                      {"opponent_key": "m_e", "wins": 0, "losses": 3, "ties": 0, "games": 3}])
    r = mgr_pub.rivals(h)
    assert r["best"]["opponent_key"] == "m_c" and r["worst"]["opponent_key"] == "m_d"
    assert mgr_pub.rivals(h.iloc[0:0]) == {"best": None, "worst": None}


def test_flag_treats_unknown_as_no():
    s = pd.Series([True, None, False], dtype="boolean")
    assert mgr_pub.flag(s).tolist() == [True, False, False]


# ---------------------------------------------------------------- JavaScript data helpers

from engine.publish import legacy_view as lv  # noqa: E402
from engine.publish.pages import trades as trades_pub  # noqa: E402


def test_js_to_json_handles_page_literals():
    text = """{career:[{m:"Andrew Root",g:16.71,w:88},], 2020: {'k': 'it\\'s', "q": "say \\"hi\\""},
              neg: -1.5, ok: true, none: null, // a comment
              list: [1, 2, /* inline */ 3,]}"""
    assert lv.parse_js(text) == {"career": [{"m": "Andrew Root", "g": 16.71, "w": 88}],
                                 "2020": {"k": "it's", "q": 'say "hi"'}, "neg": -1.5, "ok": True, "none": None,
                                 "list": [1, 2, 3]}


def test_replace_and_read_literals_and_globals():
    page = "<script>\nvar A = {x:1, y:[1,2]};\nvar B = 'keep';\nfunction f(){ return A.x; }\n</script>"
    new = lv.replace_literal(page, "A", {"x": 2, "y": []})
    assert lv.read_literal(new, "A") == {"x": 2, "y": []}
    assert "var B = 'keep';" in new and "function f(){ return A.x; }" in new
    text = lv.js_globals({"ONE": [1, None], "TWO": {"a": 1.5}})
    assert text == 'var ONE = [1,null];\nvar TWO = {"a":1.5};\n'
    assert lv.read_js_globals(text) == {"ONE": [1, None], "TWO": {"a": 1.5}}


# ---------------------------------------------------------------- trades

def _golden_trade_inputs():
    """The legacy trade pipeline's own outputs as the views' inputs."""
    uni = pd.read_csv(GOLDEN / "trades" / "trade_universe.csv.gz")
    mf = pd.read_csv(GOLDEN / "trades" / "metrics_final.csv.gz")
    ids = uni.set_index(["group_id", "manager"])[["got_player_ids", "gave_player_ids"]]
    metrics = mf.join(ids, on=["group_id", "manager"]).assign(manager_key=lambda d: d["manager"].str.strip().str.lower().map(LOOKUP))
    names = {}
    for r in uni.itertuples():
        for i, n in ((r.got_player_ids, r.got_players), (r.gave_player_ids, r.gave_players)):
            names.update(dict(zip(json.loads(i), json.loads(n))))
    wr = pd.read_csv(GOLDEN / "weekly_rosters_bracket_only.csv.gz")
    first = wr.drop_duplicates("Player_ID").set_index("Player_ID")["Position"].to_dict()
    st = pd.read_csv(GOLDEN / "trades" / "player_stints_fixed.csv.gz")
    stints = st.assign(manager_key=st["receiving_manager"].str.strip().str.lower().map(LOOKUP))
    le = pd.read_csv(GOLDEN / "trades" / "lineup_efficiency.csv.gz")
    results = pd.DataFrame({"manager_key": le["Manager"].str.strip().str.lower().map(LOOKUP),
                            "result": le["Outcome"].map({"Win": "W", "Loss": "L", "Tie": "T"})})
    return metrics, stints, results, (lambda p, s: names.get(p, str(p))), (lambda p, s: first.get(p, "UNK"))


def test_trade_views_rebuild_the_site_files_from_legacy_outputs():
    metrics, stints, results, name_of, pos_of = _golden_trade_inputs()
    seasons = set(int(s) for s in metrics["season"].unique())
    sides = trades_pub.sides_frame(metrics, name_of, pos_of, seasons)
    g = lambda n: _json(f"trades/{n}.json.gz")
    golden = {"page_data": g("page_data"), "network": g("network_data"), "winpct": g("winpct_data"),
              "explorer": g("trade_explorer_data"), "trade_week": g("trade_week_data"),
              "most_traded": g("most_traded_data"), "totals": g("trade_value_inline")["LEADERBOARD_TOTALS"]}
    names = Names(_ctx(), list(golden["page_data"]["LEADERBOARD"]["career"])
                  + [m["m"] for n in golden["explorer"] for m in n["managers"]])
    from engine.config import excluded_manager_keys
    views = trades_pub.legacy_views(sides, stints, results, excluded_manager_keys(CFG), names, name_of, pos_of, seasons)
    checks = trades_pub.compare_views(views, golden)
    bad = [c.render() for c in checks if not c.ok]
    assert not bad, "\n".join(bad)
    assert [c.name for c in checks][-1] == "legacy view trade-value.html LEADERBOARD_TOTALS vs published"
