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
