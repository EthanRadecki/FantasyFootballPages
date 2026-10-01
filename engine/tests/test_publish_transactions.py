"""Transaction page publishers (PR A6): waiver-value (A6a).

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
