"""Transaction page publishers (PR A6): waiver-value (A6a), lineup-efficiency (A6b).

Each legacy view is rebuilt from the legacy pipeline's own outputs (CI has no
canonical tables) and must equal the page's golden.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from engine.config import load_config
from engine.legacy import name_to_key
from engine.publish import legacy_view as lv
from engine.publish.config_json import short_name
from engine.publish.legacy_view import Names
from engine.publish.pages import waivers as waivers_pub

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


def _key(name: str) -> str:
    return LOOKUP[name.strip().lower()]


# ---------------------------------------------------------------- waiver-value


def test_waiver_view_rebuilds_the_page_from_the_legacy_stint_file():
    gold = _json("waivers/waiver_value_page.json.gz")
    cs = pd.read_csv(GOLDEN / "waivers" / "waiver_stints_full.csv.gz")
    names = Names(_ctx(), [r["m"] for r in gold["WAIVER_STINTS"]])
    st = pd.DataFrame({"season": cs["Season"], "manager_key": cs["Manager"].map(_key), "player_id": cs["Player_ID"],
                       "position": cs["Position"], "start_week": cs["Start_Week"], "end_week": cs["End_Week"],
                       "type": cs["Type"], "weeks_rostered": cs["Weeks_Rostered"], "total_points": cs["Total_Points"],
                       "ppw": cs["PPW"], "avg_z": cs["Avg_Z"], "total_z": cs["Total_Z"], "hidden": False})
    # the file has no player names: take each pickup's name from the page row with the same key fields
    page_name = {waivers_pub._stint_key(r): r["p"] for r in gold["WAIVER_STINTS"]}
    st["player_name"] = [page_name.get(f"{r.season}|{names(r.manager_key)}|{r.start_week}|{r.weeks_rostered}|"
                                       f"{r.position}|{waivers_pub.TYPE_CODE[r.type]}") for r in st.itertuples()]
    view = waivers_pub.waiver_view(waivers_pub.file_order(st, names), names)
    bad = [c.render() for c in waivers_pub.compare_view(view, gold) if not c.ok]
    assert not bad, "\n".join(bad)
    assert view["UPSIDE_MAX"] == 86.81 and view["POSITION_SCALE"]["ALL"]["ppwMax"] == 10.28


def test_comma_declared_constants():
    page = "var A = -1.5, B = 2.25;\nvar C = [1];"
    assert lv.read_literal(page, "B") == 2.25 and lv.read_literal(lv.replace_literal(page, "B", 3), "A") == -1.5


# ---------------------------------------------------------------- lineup-efficiency (PR A6b)

from engine.analytics import lineups as lineups_mod  # noqa: E402
from engine.publish.pages import lineup_efficiency as lineup_pub  # noqa: E402


def _legacy_lineup_inputs():
    """The legacy per-game file and rosters as engine-shaped rows (CI has no canonical tables)."""
    le = pd.read_csv(GOLDEN / "trades" / "lineup_efficiency.csv.gz")
    wr = pd.read_csv(GOLDEN / "weekly_rosters_bracket_only.csv.gz")
    lu = pd.DataFrame({"season": wr["Season"], "week": wr["Week"], "team_id": wr["Manager"],
                       "manager_key": wr["Manager"].map(_key), "player_name": wr["Player"], "position": wr["Position"],
                       "slot": wr["Slot"], "started": wr["Started"].astype(bool), "points": wr["Points"]})
    games = pd.DataFrame({"season": le["Season"], "week": le["Week"], "team_id": le["Manager"],
                          "manager_key": le["Manager"].map(_key)})
    counted = lu.merge(games[["season", "week", "team_id"]], on=["season", "week", "team_id"])
    flags = lineups_mod.neglected(counted, lineups_mod.lineup_slots(counted))
    depth = lineups_mod.bench_depth(counted)
    eff = pd.DataFrame({"season": le["Season"], "week": le["Week"], "team_id": le["Manager"],
                        "manager_key": le["Manager"].map(_key), "actual_points": le["Actual_Points"],
                        "optimal_points": le["Optimal_Points"],
                        "result": le["Outcome"].map({"Win": "W", "Loss": "L", "Tie": "T"}),
                        "missed_win": le["Missed_Win"].astype(bool), "is_playoff_week": le["Is_Playoff"].eq("Yes"),
                        "forfeited": le["Forfeited_Lineup"].astype(bool)})
    eff = eff.merge(flags, on=["season", "week", "team_id"]).merge(depth, on=["season", "week", "team_id"])
    eff["excluded"] = eff["forfeited"] | eff["neglected"]
    return eff, lu


def test_neglected_lineups_are_the_weeks_the_page_left_out():
    eff, _ = _legacy_lineup_inputs()
    got = sorted((int(r.season), int(r.week), r.team_id) for r in eff[eff["neglected"]].itertuples())
    assert got == [(2021, 10, "Carmine Pittelli Jr."), (2022, 12, "Ben Castaldo"), (2024, 14, "Ben Castaldo")]


def test_lineup_view_rebuilds_the_page_from_the_legacy_files():
    gold = _json("lineups/lineup_efficiency_page.json.gz")
    eff, lu = _legacy_lineup_inputs()
    names = Names(_ctx(), gold["HEATMAP_MANAGERS"])
    view = lineup_pub.lineup_view(eff, lu, names)
    nudged = [lineup_pub.lineup_view(eff, lu, names, nudge=e) for e in (1e-9, -1e-9)]
    bad = [c.render() for c in lineup_pub.compare_view(view, gold, nudged) if not c.ok]
    assert not bad, "\n".join(bad)
    assert view["DEPTH_BY_FILTER"]["career"][0] == {"m": "Anthony Kelly", "d": 7.57}


def test_depth_adjusted_and_role_columns():
    gap, depth = pd.Series([10.0, 12.0, 14.0, 13.0]), pd.Series([0.0, 1.0, 2.0, 0.0])
    adj = lineups_mod.depth_adjusted(gap, depth)
    assert abs(adj.sum()) < 1e-9 and adj.iloc[3] > 0                     # residuals of a least-squares line
    assert lineups_mod.depth_adjusted(gap, pd.Series([1.0] * 4)).isna().all()
    # 2020: 13 regular weeks, 4 playoff rounds; 2022: 14 regular weeks, 3 rounds
    eff = pd.DataFrame({"season": [2020] * 5 + [2022] * 4, "week": [13, 14, 15, 16, 17, 14, 15, 16, 17],
                        "is_playoff_week": [False, True, True, True, True, False, True, True, True]})
    assert lineup_pub.playoff_columns(eff, by_role=False).tolist() == [13, 14, 15, 16, 17, 14, 15, 16, 17]
    assert lineup_pub.playoff_columns(eff, by_role=True).tolist() == [13, 15, 16, 17, 18, 14, 16, 17, 18]


# ---------------------------------------------------------------- extra-analytics, matchup sections (PR A7a)

from engine.publish.pages import extra_analytics as extra_pub  # noqa: E402


def test_extra_analytics_matchup_views_rebuild_the_page():
    gold = _json("matchup_history/extra_analytics_inline.json.gz")
    names = Names(_ctx(), gold["managers"])
    h2h = pd.DataFrame([{"manager_key": _key(a), "opponent_key": _key(b), "wins": v["w"], "losses": v["l"],
                         "win_pct": v["pct"], "hidden": False} for a, row in gold["h2h"].items() for b, v in row.items()])
    assert extra_pub.h2h_view(h2h, names) == (gold["managers"], gold["h2h"])
    rows, summ = [], []
    for season, d in gold["SCHEDULE_SWAP_DATA"].items():
        for m, x in d.items():
            summ.append({"season": int(season), "manager_key": _key(m), "wins": x["actual"]["w"],
                         "losses": x["actual"]["l"], "pct": x["actual"]["pct"], "avg_alt_pct": x["avg_pct"],
                         "wins_gained": x["wins_gained"], "hidden": False})
            rows += [{"season": int(season), "manager_key": _key(m), "schedule_key": _key(o), "wins": a["w"],
                      "losses": a["l"], "games": a["games"], "pct": a["pct"], "hidden": False} for o, a in x["alt"].items()]
    assert extra_pub.swap_view(pd.DataFrame(rows), pd.DataFrame(summ), names) == gold["SCHEDULE_SWAP_DATA"]
    luck = pd.read_csv(GOLDEN / "schedule" / "schedule_luck_season.csv.gz")
    luck = luck.assign(manager_key=luck["Manager"].map(_key), hidden=False)
    view = {r["name"]: r for r in extra_pub.luck_view(luck, names)}
    page = {r["name"]: r for r in gold["luckData"]}
    differ = sorted(n for n in page if view[n] != page[n])
    assert differ == ["Charlie Gorman"]            # the page typed 38 expected wins; its own source file sums to 39


def test_closest_lists_from_the_games():
    from engine.tests.test_publish_pages import _frames_from_matchups_json
    gold = _json("matchup_history/extra_analytics_inline.json.gz")
    games, _ = _frames_from_matchups_json(_json("records/matchups.json.gz"))
    games = games[games["season"] <= 2025]
    names = Names(_ctx(), gold["managers"])
    hidden = {LOOKUP["thomas sullivan"], LOOKUP["william serafin"]}
    view = extra_pub.closest_view(games, hidden, names)
    assert view["all"] == gold["CLOSEST"]["all"]
    full = {s: extra_pub.closest_view(games, hidden, names, k=len(games))[s] for s in ("regular", "playoff")}
    for scope in ("regular", "playoff"):
        order = [(r["w"], r["l"], r["when"]) for r in full[scope]]
        pos = [order.index((r["w"], r["l"], r["when"])) for r in gold["CLOSEST"][scope]]
        assert pos == sorted(pos) and all(full[scope][p] == r for p, r in zip(pos, gold["CLOSEST"][scope]))


def test_conference_markup_round_trip():
    gold = _json("matchup_history/extra_analytics_inline.json.gz")
    want = extra_pub.parse_conference(gold)
    names = Names(_ctx(), gold["managers"])
    conf = {n: c for c, ns in want["teams"].items() for n in ns}
    managers = pd.DataFrame([{"manager_key": _key(r[0]), "conference": r[1], "wins": int(r[2].split("-")[0]),
                              "losses": int(r[2].split("-")[1]), "win_pct": float(r[3]), "pf_per_game": float(r[4]),
                              "pa_per_game": float(r[5]), "margin": float(r[6]), "hidden": False}
                             for r in want["conference_managers"][1:]])
    seasons = pd.DataFrame([{"season": int(r[0]), "conference": "REP", "wins": int(r[1].split("-")[0]),
                             "losses": int(r[1].split("-")[1]), "win_pct": float(r[2]), "games": int(r[3])}
                            for r in want["conference_seasons"][1:]])
    summary = pd.DataFrame([{"conference": c, **{col: want["conference_cards"][label][c]
                                                 for label, col, _ in extra_pub.CARDS}} for c in ("DEM", "REP")])
    riv = []
    for r in want["rivalries"][1:]:
        a, b = [x.strip() for x in r[0].split(" vs ")]
        hi, lo = (int(x) for x in r[1].split()[0].split("-"))
        lead = r[1].split()[1]
        wa, wb = (hi, lo) if lead in ("Tied", a.split()[-1]) or lead == short_name(a) else (lo, hi)
        riv.append({"manager_key": _key(a), "opponent_key": _key(b), "wins": wa, "losses": wb, "games": int(r[2]),
                    "hidden": False})
    res = {"conference_managers": managers, "conference_seasons": seasons, "conference_summary": summary,
           "rivalries": pd.DataFrame(riv)}
    cfg = {m["id"]: m for m in CFG["managers"]}
    html = extra_pub.conference_html(res, names, lambda k: short_name(cfg[k]["name"]), lambda k: cfg[k]["logo"],
                                     {"2020": "#a4969d", "2021": "#8a93ab", "2022": "#d8b28e", "2023": "#bf8f8f",
                                      "2024": "#9aadae", "2025": "#a9b88b"}, ["DEM", "REP"])
    assert extra_pub.parse_conference(html) == want
    assert conf["Ryan P McQuaid"] == "REP"


# ---------------------------------------------------------------- extra-analytics model sections

_GOLDENS = {}


def _goldens() -> dict:
    if not _GOLDENS:
        from engine.cli import load_goldens
        _GOLDENS.update(load_goldens(GOLDEN))
    return _GOLDENS


def test_attribution_view_rebuilds_the_page_from_the_published_factors():
    from engine.analytics import attribution as attr
    from engine.legacy_attribution import published_factors
    gold = _json("matchup_history/extra_analytics_inline.json.gz")
    names = Names(_ctx(), gold["managers"])
    fit = attr.fit(published_factors(_goldens(), CFG).assign(hidden=False), sample_sd=False)
    view = extra_pub.attribution_view(fit["attribution_managers"], fit["attribution_coefficients"],
                                      fit["attribution_fit"].iloc[0], gold["R2_VALS"], names)
    for k in ("DATA#1", "LEAGUE_INTERCEPT", "COEF_LABELS", "COEF_VALS", "R2_VALS"):
        assert view[k] == gold[k], k


def test_gauntlet_view_rebuilds_the_page_from_the_legacy_run():
    from engine.legacy_gauntlet import legacy_run
    gold = _json("matchup_history/extra_analytics_inline.json.gz")
    names = Names(_ctx(), gold["managers"])
    win, detail, champs, dom = legacy_run(_goldens(), CFG)
    as_name = lambda k: k if not str(k).startswith("m_") else names(k)
    pfg = {(s, m): v for s, m, v in zip(dom["season"], dom["manager_key"], dom["pf_per_game"])}
    view = extra_pub.gauntlet_view(win, detail, champs, pfg, {}, as_name)
    assert view["HARDEST"] == gold["HARDEST"] and view["EASIEST"] == gold["EASIEST"]
    assert view["CHAMPION_RANKS"]["2020_Ethan Radecki"]["sameLength"] == 4
    extra_pub._raw_dom_cards(view["CHAMPIONS"], champs, detail)
    page = {c["year"]: c for c in gold["CHAMPIONS"]}
    for c in view["CHAMPIONS"]:
        p = page[c["year"]]
        assert (c["champion"], c["n"], c["raw_dom"], c["s_dom"]) == (p["champion"], p["n"], p["raw_dom"], p["s_dom"])
        for g, h in zip(c["games"], p["games"]):
            assert [g[k] for k in ("r", "opp", "cs", "os", "m", "dom", "rppg")] == \
                   [h[k] for k in ("r", "opp", "cs", "os", "m", "dom", "rppg")]


def test_positional_and_quarterly_views():
    gold = _json("matchup_history/extra_analytics_inline.json.gz")
    names = Names(_ctx(), gold["managers"])
    pos = gold["POSITIONS"]
    career = pd.DataFrame([{"manager_key": _key(r["mgr"]), **{f"{p}_avg": r["avg"][p] for p in pos},
                            **{f"{p}_sd": r["std"][p] for p in pos}} for r in gold["DATA"]])
    wp = pd.Series({_key(r["mgr"]): r["winpct"] for r in gold["DATA"]})
    coefs = pd.DataFrame([{"position": p, "std_coef": gold["STD_COEF"][p], "p_value": gold["COEF_PVAL"][p],
                           "corr": gold["CORR_R"][p]} for p in pos])
    view = extra_pub.positional_view(career, coefs, wp, pos, names)
    assert {r["mgr"]: r for r in view["DATA"]} == {r["mgr"]: r for r in gold["DATA"]}
    assert [view[k] for k in ("POSITIONS", "STD_COEF", "COEF_PVAL", "CORR_R")] == \
           [gold[k] for k in ("POSITIONS", "STD_COEF", "COEF_PVAL", "CORR_R")]
    q = pd.DataFrame({"quarter": ["Q1", "Q4"], "weeks": ["1-3", "10-13"], "coef": [0.3864, 0.7357],
                      "corr": [0.1, 0.2], "p_value": [0.0001, 0.0004]})
    assert extra_pub.quarterly_view(q) == {"labels": ["Q1 (Wks 1-3)", "Q4 (Wks 10-13)"], "coefs": [0.386, 0.736],
                                           "corrs": [0.1, 0.2], "pvals": [0.0, 0.0]}


def test_team_names_editorial_overrides_espn_names(tmp_path):
    (tmp_path / "editorial").mkdir()
    (tmp_path / "editorial" / "team_names.yaml").write_text(
        'shown:\n  2022:\n    "Long Name": "Shown"\nshort:\n  2021:\n    "Long Name": "Short"\n', encoding="utf-8")
    teams = pd.DataFrame({"season": [2021, 2022], "manager_key": ["m_000000000001"] * 2,
                          "team_name": ["Long Name", "Long Name"]})
    ctx = SimpleNamespace(league_dir=tmp_path, tables={"teams": teams})
    from engine.publish.editorial import team_names
    assert team_names(ctx) == {(2021, "m_000000000001"): "Long Name", (2022, "m_000000000001"): "Shown"}
    assert team_names(ctx, short=True) == {(2021, "m_000000000001"): "Short", (2022, "m_000000000001"): "Shown"}


def test_champion_rank_ties_are_excused_inside_the_tied_group():
    gold = _json("matchup_history/extra_analytics_inline.json.gz")
    data = json.loads(json.dumps(gold))
    data["CHAMPION_RANKS"]["2021_Ben Castaldo"]["rank"] = 341        # the other order inside the 341-342 tie
    assert all(c.ok for c in extra_pub.compare_models(data, gold, {"2021_Ben Castaldo": (341, 342)}))
    bad = [c for c in extra_pub.compare_models(data, gold, {}) if not c.ok]
    assert len(bad) == 1 and "CHAMPION_RANKS" in bad[0].name


def test_season_filterable_pages_show_the_live_season_once_it_has_a_finished_week():
    """M1b: the season pills list every finished season and the live season's finished weeks."""
    def ctx(week):
        return SimpleNamespace(config={"finished_seasons": [2020, 2021], "live_season": 2022,
                                       "current": {"season": 2022, "last_completed_week": week}})
    assert lv.page_seasons(ctx(3), [2022, 2020, 2021, 2021]) == [2020, 2021, 2022]
    assert lv.page_seasons(ctx(0), [2020, 2021, 2022]) == [2020, 2021]           # no finished week yet
    assert lv.page_seasons(ctx(3), [2021]) == [2021]                                # only seasons with data
    page = "<script>\nvar PAGE_SEASONS = [2020, 2021];\nvar PAGE_LIVE_SEASON = null;\nvar keys = [];"
    out = lv.with_page_seasons(page, [2020, 2021, 2022], 2022)
    assert lv.read_literal(out, "PAGE_SEASONS") == [2020, 2021, 2022] and lv.read_literal(out, "PAGE_LIVE_SEASON") == 2022
    assert "PAGE_LIVE_SEASON = null;" in lv.with_page_seasons(page, [2020, 2021], 2022)    # live season not shown
    assert lv.with_page_seasons("<p>no seasons here</p>", [2020]) == "<p>no seasons here</p>"
    for rel in ("pages/waiver-value.html", "pages/trade-value.html", "pages/lineup-efficiency.html"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "var PAGE_SEASONS = [" in text and "'2025'" not in text, rel     # no hardcoded season list left
