"""The rankings editor (web/pages/rankings-editor.html): its week logic
(web/assets/js/pages/rankings-week.js, run with node when installed) against the engine's.

- serialize() writes every committed editorial file byte for byte as the engine does
- opening a week and saving it untouched changes nothing (older weeks keep their hand markup)
- problems() gives exactly engine/publish/rankings.py problems() on the same weeks
- a changed blurb is formatted, an empty synopsis takes the key sentence, ranks order the teams
"""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
from pathlib import Path

from engine.config import load_config
from engine.legacy import name_to_key
from engine.publish import rankings as R
from engine.publish.blurbs import format_blurb
from engine.publish.site import PAGES

ROOT = Path(__file__).resolve().parents[2]
LEAGUE = ROOT / "leagues" / "preach"
LOOKUP = name_to_key(load_config(LEAGUE / "league.yaml"))
VOCAB = json.loads((Path(__file__).parent / "golden" / "blurbs" / "vocab_2026.json").read_text(encoding="utf-8"))


def _node(job: dict) -> dict | None:
    node = shutil.which("node")
    if node is None:                      # CI runners and the Codespace have node
        return None
    res = subprocess.run([node, str(Path(__file__).parent / "js" / "rankings_week_run.mjs")],
                         input=json.dumps(job, ensure_ascii=False).encode("utf-8"), capture_output=True, check=True)
    return json.loads(res.stdout.decode("utf-8"))


def _week(**over):
    teams = [{"manager": "Charlie Gorman", "rank": 1, "synopsis": "s", "blurb": "b", "screenshots": []},
             {"manager": "Ethan Radecki", "rank": 2, "synopsis": "s", "blurb": "b", "screenshots": []}]
    d = {"season": 2026, "week": 6, "status": "draft", "teams": teams,
         "matchup_of_the_week": {"team_a": "Charlie Gorman", "team_b": "Ethan Radecki", "blurb": "m"}}
    d.update(over)
    return d


CHECKS = [
    (_week(), ["Charlie Gorman", "Ethan Radecki"]),
    (_week(teams=[{"manager": "Charlie Gorman", "rank": 1}, {"manager": "Ethan Radecki", "rank": 1}]), None),
    (_week(teams=[{"manager": "Charlie Gorman", "rank": 1, "blurb": "x"}, {"manager": "Ethan Radecki", "rank": 3}]),
     ["Charlie Gorman", "Ethan Radecki", "Max Malich"]),
    (_week(teams=[{"manager": "Nobody", "rank": 1, "blurb": "x"}, {"manager": "charlie gorman", "rank": 2},
                  {"manager": "Charlie Gorman", "rank": 3}]), []),
    (_week(teams=[{"manager": "Charlie Gorman", "rank": 1}, {"manager": "Ethan Radecki", "rank": 2}]), None),
    (_week(matchup_of_the_week={"team_a": "Charlie Gorman", "team_b": "CHARLIE GORMAN"}), None),
    (_week(matchup_of_the_week={"team_a": "Charlie Gorman", "team_b": "Who"}), None),
    ({k: v for k, v in _week().items() if k != "matchup_of_the_week"}, None),
    (_week(teams=[{"manager": "Charlie Gorman", "rank": 1, "blurb": "a " + chr(0x2014) + " b", "synopsis": "s"},
                  {"manager": "Ethan Radecki", "rank": 2, "blurb": "b", "synopsis": "s"}]), None),
]


def _files() -> dict[str, str]:
    """Every committed week file (the editor opens week files only; playoff previews are written by hand)."""
    return {p.name: p.read_text(encoding="utf-8") for p in sorted((LEAGUE / R.EDITORIAL_DIR).glob("*.json"))
            if R.WEEK_FILE.match(p.name)}


def test_editor_page_is_listed_but_not_in_the_nav():
    page = next(p for p in PAGES if p["id"] == "rankings-editor")
    assert page["nav"] is False and page["feature"] == "weekly_rankings"
    assert set(page["data"]) == {"data/v1/editor/vocab.json", "data/v1/editor/week.json"}
    html = (ROOT / "web" / "pages" / "rankings-editor.html").read_text(encoding="utf-8")
    assert 'name="robots" content="noindex' in html


def test_week_logic_matches_the_engine():
    files = _files()
    original = json.loads(files["2026_week05.json"])
    state = {"teams": [{"manager": t["manager"], "rank": len(original["teams"]) - t["rank"] + 1,
                        "source": "", "synopsis": ""} for t in original["teams"]],
             "motw": {"team_a": "Ben Castaldo", "team_b": "Max Malich", "source": "Big one. **Ben wins.**"}}
    state["teams"][0]["source"] = "Charlie had 150 points. More."
    job = {"lookup": LOOKUP, "files": files, "vocab": VOCAB,
           "checks": [{"ed": ed, "expected": exp} for ed, exp in CHECKS],
           "builds": [{"original": original, "state": state, "status": "draft"}]}
    out = _node(job)
    if out is None:
        return
    assert all(out["serialized"].values()), [n for n, ok in out["serialized"].items() if not ok]
    assert all(out["unchanged"].values()), [n for n, ok in out["unchanged"].items() if not ok]
    for (ed, exp), got in zip(CHECKS, out["problems"]):
        errors, warnings = R.problems(ed, exp, LOOKUP)
        assert (got["errors"], got["warnings"]) == (errors, warnings), ed["teams"]
    b = out["builds"][0]
    assert list(b)[:3] == ["season", "week", "status"] and b["status"] == "draft"
    assert [t["rank"] for t in b["teams"]] == list(range(1, len(original["teams"]) + 1))
    first = next(t for t in b["teams"] if t["manager"] == original["teams"][0]["manager"])
    html, syn = format_blurb("Charlie had 150 points. More.", VOCAB, True)
    assert first["blurb"] == html and first["synopsis"] == syn == "Charlie had 150 points."
    assert all(list(t)[:5] == ["manager", "rank", "synopsis", "blurb", "screenshots"] for t in b["teams"])
    assert b["matchup_of_the_week"]["team_a"] == "Ben Castaldo"
    assert b["matchup_of_the_week"]["blurb"] == format_blurb("Big one. **Ben wins.**", VOCAB, False)[0]


def test_editor_week_model_is_valid(tmp_path):
    """data/v1/editor/week.json on a tiny league: the week to write, the record fields, last and next games."""
    import pandas as pd
    import jsonschema
    from engine.publish.pages.editor import week_numbers

    k1, k2 = LOOKUP["charlie gorman"], LOOKUP["ethan radecki"]
    rows = [{"season": 2026, "week": w, "is_bye": False, "is_playoff_week": False, "tier": None,
             "result": r} for w in (1, 2) for r in ("W", "L")]
    rows += [{"season": 2026, "week": 3, "is_bye": False, "is_playoff_week": False, "tier": None,
              "result": "UNDECIDED"}] * 2
    games = pd.DataFrame([{"season": 2026, "week": w, "is_playoff": False, "team_a_key": k1, "team_a_points": 100.0 + w,
                           "team_a_result": "W", "team_b_key": k2, "team_b_points": 90.0, "team_b_result": "L"}
                          for w in (1, 2)])
    eff = pd.DataFrame([{"season": 2026, "week": 2, "manager_key": k, "opponent_manager_key": o, "points": p,
                         "opponent_points": q, "result": r, "optimal_points": p + 10, "efficiency_gap": 10.0}
                        for k, o, p, q, r in ((k1, k2, 102.0, 90.0, "W"), (k2, k1, 90.0, 102.0, "L"))])
    (tmp_path / R.EDITORIAL_DIR).mkdir(parents=True)
    R.write_json(tmp_path / R.EDITORIAL_DIR / "2026_week02.json",
                 {"season": 2026, "week": 2, "teams": [{"manager": "Ethan Radecki", "rank": 1},
                                                       {"manager": "Charlie Gorman", "rank": 2}]})

    class Ctx:
        cfg = load_config(LEAGUE / "league.yaml")
        league_dir = tmp_path
        tables = {"matchups": pd.DataFrame(rows),
                  "seasons": pd.DataFrame([{"season": 2026, "regular_season_periods": 14, "final_scoring_period": 17}]),
                  "draft_picks": pd.DataFrame({"season": [2026], "player_id": [1]}),
                  "teams": pd.DataFrame({"season": 2026, "manager_key": [k1, k2], "team_name": ["A", "B"]}),
                  "future_matchups": pd.DataFrame({"season": 2026, "week": 3, "manager_key": [k1, k2],
                                                   "opponent_manager_key": [k2, k1]})}
        analysis = {"games": games, "lineup_efficiency": eff,
                    "head_to_head": pd.DataFrame([{"manager_key": k1, "opponent_key": k2, "wins": 2, "losses": 0,
                                                   "ties": 0}])}

    w = week_numbers(Ctx())
    assert (w["season"], w["week"], w["file"]) == (2026, 3, "2026_week03.json")
    assert w["repo"]["editorial_dir"].endswith("editorial/rankings")
    c = next(m for m in w["managers"] if m["key"] == k1)
    assert (c["record"], c["ppg"], c["streak"], c["prev_rank"]) == ("2-0", 101.5, "W2", 2)
    assert c["last_game"]["left_on_bench"] == 10.0 and c["next_game"]["h2h"] == {"w": 2, "l": 0, "t": 0}
    schema = json.loads((ROOT / "engine" / "publish" / "schemas" / "editor-week.schema.json").read_text())
    assert not list(jsonschema.Draft202012Validator(schema).iter_errors({"meta": {}, **w}))
