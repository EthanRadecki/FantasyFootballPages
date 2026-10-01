"""Draft page publishers (PR A5): draft-history, draft-fingerprints,
surplus-value, draft-analysis, and managers.html's draft board map.

Each legacy view is rebuilt from its golden or from the legacy pipeline's own
outputs (CI has no canonical tables): the golden is read into engine-shaped
rows, the view builder writes it back, and the result must equal the golden.
`engine build --verify` feeds the same builders the legacy-mode analysis.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

from engine.config import excluded_manager_keys, load_config
from engine.legacy import name_to_key
from engine.publish import legacy_view as lv
from engine.publish.config_json import short_name
from engine.publish.diff import diff
from engine.publish.editorial import load_editorial
from engine.publish.legacy_view import Names
from engine.publish.pages import board_map, draft_analysis, draft_history, fingerprints, surplus

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = Path(__file__).parent / "golden"
CFG = load_config(ROOT / "leagues" / "preach" / "league.yaml")
LOOKUP = name_to_key(CFG)
HIDDEN = excluded_manager_keys(CFG)


def _json(rel):
    with gzip.open(GOLDEN / rel, "rt", encoding="utf-8") as f:
        return json.load(f)


def _ctx():
    return SimpleNamespace(cfg=CFG, config={"managers": [{"key": m["id"], "name": m["name"], "short": short_name(m["name"])}
                                                         for m in CFG["managers"]]})


def _key(name: str) -> str:
    return LOOKUP[name.strip().lower()]


# ---------------------------------------------------------------- helpers

def test_number_literals_and_typed_html():
    page = ('<script>var A = -11.61;\nvar B = 13.77;</script>\n<table class="t"><tbody><tr><td>1</td></tr></tbody></table>'
            '<script>var h = "<tbody>";</script>\n<div class="row"><div class="x">1</div><div>2</div></div>')
    assert lv.read_literal(page, "A") == -11.61 and lv.read_literal(lv.replace_literal(page, "B", 2.5), "B") == 2.5
    assert lv.read_html(page, "<tbody>", '<table class="t">') == "<tr><td>1</td></tr>"
    out = lv.replace_html(page, '<div class="row">', "<p>new</p>")
    assert '<div class="row"><p>new</p></div>' in out and 'var h = "<tbody>"' in out
    try:
        lv.read_html(page, "<tbody>")
        raise AssertionError("a tag that is not unique must need an anchor")
    except ValueError:
        pass
    assert lv.page_roundtrip("var X = [1];", {"X": [{"a": 1.5}]}) == {"X": [{"a": 1.5}]}


# ---------------------------------------------------------------- draft-history

def _board_from_page(page: dict) -> pd.DataFrame:
    rows = []
    for season, rounds in page["DRAFT"].items():
        order = page["SLOT_ORDER"][season]
        n = len(order)
        for rnd, picks in rounds.items():
            for i, p in enumerate(picks):
                rows.append({"season": int(season), "round": int(rnd), "overall_pick": (int(rnd) - 1) * n + i + 1,
                             "draft_slot": i + 1, "manager_key": _key(order[i]) if rnd == "1" else _key(order[0]),
                             "player_id": len(rows), "player_name": p["p"], "position": p["pos"],
                             "ppg": np.nan if p["ppg"] is None else p["ppg"],
                             "games": np.nan if p["g"] is None else p["g"]})
    return pd.DataFrame(rows)


def test_draft_history_view_rebuilds_the_page_data():
    gold = _json("draft/draft_board_page.json.gz")
    board = _board_from_page(gold)
    names = Names(_ctx(), [n for ms in gold["SLOT_ORDER"].values() for n in ms])
    assert draft_history.history_view(board, names) == gold
    model = draft_history.history_model(board, {2026}, HIDDEN)
    assert model["seasons"][-1] == {"season": 2026, "live": True, "rounds": 16, "teams": 14}
    assert len(model["slot_order"]["2020"]) == 15 and model["slot_order"]["2020"][13] in HIDDEN


# ---------------------------------------------------------------- draft-fingerprints

OUT = {"Win_Pct": "win_pct", "PPG": "ppg", "avg_surplus_per_pick": "surplus"}


def _profiles_from_page(page: dict) -> dict:
    seasons, career = [], []
    for name, per in page["FINGERPRINTS"].items():
        key = _key(name)
        for period, e in per.items():
            row = {OUT.get(k, k): v for k, v in e["all"].items()}
            row |= {f"norm_{d}": v for d, v in e["normalized"].items()} | {"manager_key": key, "hidden": key in HIDDEN}
            if period == "career":
                career.append(row)
            else:
                seasons.append(row | {"season": int(period), "live": period == "2026", "cluster": e["cluster"]})
    s = pd.DataFrame(seasons)
    s["cluster"] = s["cluster"].astype("Int64")
    arch = pd.DataFrame([{"cluster": a["id"], "n": a["n"], **{f"center_{d}": v for d, v in a["center"].items()},
                          "win_pct": a["outcomes"]["win_pct"], "ppg": a["outcomes"]["ppg"],
                          "surplus": a["outcomes"]["avg_surplus_per_pick"]} for a in page["ARCHETYPES"]["cluster_summary"]])
    a, st = page["ARCHETYPES"], page["ARCHETYPES"]["stats"]
    stats = {"k": a["k"], "n_observations": a["n_observations"], "n_managers": a["n_managers"],
             "n_multi_cluster": a["n_multi_cluster"], "win_pct_p": st["win_pct_p"], "ppg_p": st["ppg_p"],
             "silhouette_pca": st["silhouette_pca_k4"], "silhouette_raw": st["silhouette_raw_k4"],
             "silhouette_k3_gmm": st["silhouette_k3_gmm"], "bootstrap_mean_ari": st["bootstrap_mean_ari"],
             "bootstrap_std_ari": st["bootstrap_std_ari"], "bootstrap_p5": st["bootstrap_p5_p95"][0],
             "bootstrap_p95": st["bootstrap_p5_p95"][1], "fill_notes": ""}
    return {"draft_profile_seasons": s, "draft_profile_career": pd.DataFrame(career), "draft_archetypes": arch,
            "draft_archetype_stats": pd.DataFrame([stats])}


def test_fingerprints_view_rebuilds_the_page_data():
    gold = _json("draft/draft_fingerprints_page.json.gz")
    res = _profiles_from_page(gold)
    meta = {x["id"]: {"name": x["name"], "desc": x["desc"], "color": x["color"]}
            for x in gold["ARCHETYPES"]["cluster_summary"]}
    view = fingerprints.fingerprints_view(res, Names(_ctx(), list(gold["FINGERPRINTS"])), meta)
    for k in ("FINGERPRINTS", "ARCHETYPES", "GLOBAL_RANGES", "RADAR_DIMS", "POSDEV_DIMS"):
        assert not diff(fingerprints._keyed(view)[k] if k == "ARCHETYPES" else view[k],
                        fingerprints._keyed(gold)[k] if k == "ARCHETYPES" else gold[k]), k
    # the career scales the golden lets us rebuild (the rest come from fingerprint columns the page does not list)
    assert all(view["CAREER_RANGES"][k] == v for k, v in gold["CAREER_RANGES"].items() if k in view["CAREER_RANGES"])


def test_archetype_labels_from_editorial_file_or_generated():
    res = _profiles_from_page(_json("draft/draft_fingerprints_page.json.gz"))
    ctx = SimpleNamespace(league_dir=ROOT / "leagues" / "preach")
    meta = fingerprints.archetype_meta(res["draft_archetypes"], res["draft_profile_seasons"],
                                       load_editorial(ctx, "archetypes"))
    assert meta[0]["name"] == "Balanced Board-Followers" and meta[3]["color"] == "#a85a5a"
    gen = fingerprints.archetype_meta(res["draft_archetypes"], res["draft_profile_seasons"], None)
    assert len({m["name"] for m in gen.values()}) == 4 and all(m["name"].split()[0] in ("High", "Low") for m in gen.values())
    assert load_editorial(SimpleNamespace(league_dir=None), "archetypes") is None


def test_fingerprint_excuses_follow_the_analyze_patterns():
    known = fingerprints.known_fn({"2026"}, {("A B", "win_pct"): 0.4285})
    assert known("/FINGERPRINTS/A B/2026/all/draft_conviction", 1.0, 2.0) == fingerprints.LIVE_REASON
    assert known("/FINGERPRINTS/A B/2026/all/early_rb_pct", 1.0, 2.0) is None          # needs no ADP: checked
    assert known("/FINGERPRINTS/A B/career/all/Win_Pct", 0.428, 0.429) == fingerprints.TIE_REASON
    assert known("/ARCHETYPES/stats/bootstrap_mean_ari", 0.5, 0.53) == fingerprints.RANDOM_REASON
    assert known("/ARCHETYPES/stats/win_pct_p", 0.5, 0.53) is None


# ---------------------------------------------------------------- surplus-value and the board map

def _surplus_frame() -> pd.DataFrame:
    v2 = pd.read_csv(GOLDEN / "draft" / "draft_surplus_v2.csv.gz")
    return pd.DataFrame({"season": v2["season"], "round": v2["round"], "overall_pick": v2["overall_pick"],
                         "draft_slot": v2["draft_slot"], "manager_key": v2["manager"].map(_key),
                         "player_id": range(len(v2)), "player_name": v2["player_name"], "position": v2["position"],
                         "games": v2["games_played"], "zeroed": v2["injury_zeroed"].astype(bool),
                         "actual_prv": v2["actual_prv"], "expected_prv": v2["expected_prv"], "surplus": v2["surplus"],
                         "surplus_wtd": v2["surplus_wtd"], "hidden": False})


def _grades():
    sv = _json("draft/surplus_value_data.json.gz")
    career = pd.DataFrame([{"manager_key": _key(c["manager"]), "rank": c["rank"], "avg_surplus": c["avg_surplus"],
                            "weighted_total": c["weighted_total"], "total_picks": c["total_picks"],
                            "seasons": c["seasons"]} for c in sv["career_grades"]])
    season = pd.DataFrame([{"season": s["season"], "manager_key": _key(s["manager"]), "draft_grade": s["draft_grade"],
                            "season_rank": s["season_rank"], "total_picks": 0} for s in sv["season_grades"]])
    return career, season


def test_surplus_view_rebuilds_the_page_data():
    gold = _json("draft/surplus_value_page.json.gz")
    career, season = _grades()
    seasons = gold["SEASONS"]
    p = surplus.picks_frame(_surplus_frame(), seasons)
    view = surplus.surplus_view(p, career, season, seasons, Names(_ctx(), [r["manager"] for r in gold["CAREER_GRADES"]]),
                                HIDDEN)
    bad = [c.render() for c in surplus.compare_view(view, gold) if not c.ok]
    assert not bad, "\n".join(bad)


def test_board_map_view_rebuilds_the_page_data():
    gold = _json("draft/draft_heatmap.json.gz")
    career, _ = _grades()
    view = board_map.board_map_view(_surplus_frame(), career, list(range(2020, 2026)), HIDDEN, Names(_ctx(), list(gold)))
    assert not diff(view, gold)


# ---------------------------------------------------------------- draft-analysis

def _slot_results(page: dict) -> pd.DataFrame:
    t = pd.DataFrame(page["table"])
    return pd.DataFrame({"draft_slot": t["slot"], "seasons": t["seasons"], "playoff_rate": t["playoff_pct"] / 100,
                         "champion_rate": t["champ_pct"] / 100, "pf_per_game": t["pf_per_game"],
                         "dominance": t["dominance"], "expected_dominance": t["expected_dominance"],
                         "over_under": t["over_under"]})


def test_slot_table_html_rebuilds_the_typed_table_with_its_colors():
    gold = _json("draft/draft_analysis_page.json.gz")
    res = _slot_results(_json("manager_seasons/draft_slots_page.json.gz"))
    res = pd.concat([res, pd.DataFrame([{"draft_slot": 15, "seasons": 1, "playoff_rate": 0.0, "champion_rate": 0.0,
                                         "pf_per_game": 100.0, "dominance": 0.0, "expected_dominance": 0.0,
                                         "over_under": 0.0}])], ignore_index=True)
    assert draft_analysis.slot_table_html(res) == gold["slot_table"]          # slot 15 left out (decision 7.4)
    table, cells = draft_analysis.parse_slot_table(gold["slot_table"])
    assert len(table) == 14 and len(cells) == 14 * 8 and table["over_under"].iloc[5] == -0.66


def test_tier_cards_and_hit_rate_blocks():
    gold = _json("draft/draft_analysis_page.json.gz")
    hr = _json("draft/hit_rate_data.json.gz")
    rows = []
    for t in hr["overall"]:            # picks shaped to give each tier its hits and picks
        rnd = {"Early": 1, "Middle": 4, "Late": 8}[t["tier_short"]]
        rows += [{"round": rnd, "tier": t["tier_short"], "hit": i < t["hits"], "position": "RB"}
                 for i in range(t["total_picks"])]
    h = pd.DataFrame(rows)
    assert draft_analysis.tier_cards_html(h) == gold["tier_cards"]
    assert draft_analysis.parse_tier_cards(gold["tier_cards"])[0] == {"label": "Early Rounds (1-3)", "tier": "early",
                                                                      "rate": 76.9, "hits": 196, "picks": 255}


def test_season_steals_excuses():
    source = {"season_steals": {"2020": [{"player": "A", "slot": 9, "ppg": 14.44, "pts_above_avg": 7.31}]}}
    view = {"SEASON_STEALS": {"2020": [{"player": "A", "above": 7.31}]}, "ALL_TIME_STEALS": []}
    gold = {"SEASON_STEALS": {"2020": [{"player": "A", "above": 7.31}]}, "ALL_TIME_STEALS": []}
    known = draft_analysis.steals_source(source, view, gold)
    assert known("/SEASON_STEALS/2020[0]/slot", 9, 7) == draft_analysis.STEALS_REASON
    assert known("/SEASON_STEALS/2020[0]/slot", 8, 7) is None           # neither the page nor its source
    view2 = {"SEASON_STEALS": {"2020": [{"player": "B", "above": 7.31}]}, "ALL_TIME_STEALS": []}
    assert draft_analysis.steals_source(source, view2, gold)("/SEASON_STEALS/2020[0]/player", "B", "A") == \
        draft_analysis.TIE_REASON
