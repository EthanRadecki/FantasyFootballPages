"""Weekly rankings (PR A8b): editorial files, frozen snapshots and derived fields (decision 7.9).

CI has no canonical tables, so the derived fields are rebuilt from the
`records/matchups.json` golden (every game 2020 through 2026 week 2) and the
published files from the `rankings/rankings_files.json` golden (every rankings
file as of 2026-10-05).
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pandas as pd

from engine.config import load_config
from engine.legacy import name_to_key
from engine.publish import rankings as R
from engine.publish.diff import diff
from engine.publish.pages import rankings as pub

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = Path(__file__).parent / "golden"
CFG = load_config(ROOT / "leagues" / "preach" / "league.yaml")
LOOKUP = name_to_key(CFG)
SCHEMAS = ROOT / "engine" / "publish" / "schemas"


def _json(rel):
    with gzip.open(GOLDEN / rel, "rt", encoding="utf-8") as f:
        return json.load(f)


FILES = _json("rankings/rankings_files.json.gz")
WEEKS = {n: d for n, d in FILES.items() if R.WEEK_FILE.match(n)}


def _games_from_golden() -> pd.DataFrame:
    """records/matchups.json as the engine's `games` table (the columns the rankings use)."""
    res = {"Win": "W", "Loss": "L", "Tie": "T"}
    rows = []
    for g in _json("records/matchups.json.gz"):
        a, b = g["teamA"], g["teamB"]
        rows.append({"season": g["season"], "week": g["week"], "is_playoff": g["isPlayoff"],
                     "team_a_key": LOOKUP[a["manager"].lower()], "team_a_points": a["score"],
                     "team_a_result": res[a["outcome"]], "team_b_key": LOOKUP[b["manager"].lower()],
                     "team_b_points": b["score"], "team_b_result": res[b["outcome"]]})
    return pd.DataFrame(rows)


def test_split_and_merge_are_lossless():
    for name, f in WEEKS.items():
        ed, snap = R.split(f)
        derived = {LOOKUP[t["manager"].lower()]: {k: t[k] for k in R.DERIVED_TEAM if k in t} for t in f["teams"]}
        assert diff(R.merge(ed, snap, derived, LOOKUP), f) == [], name
        assert not any(k in R.DERIVED_TEAM for t in ed["teams"] for k in t)
        if snap is None:
            assert f["season"] < 2026     # only the live season's files carry computed fields
        else:
            assert set(snap) - {"season", "week"} and all("rank" not in t for t in snap.get("teams", []))


def test_derived_fields_rebuild_every_published_week():
    """record, PPG, last score, streak, prev_rank, rank_change and avg_rank from the games and the
    editorial ranks: every value matches or is one of the known legacy differences."""
    games = _games_from_golden()
    covered = {n: d for n, d in WEEKS.items() if d["season"] < 2026 or d["week"] <= 3}
    editorial = {n: R.split(d)[0] for n, d in covered.items()}
    weeks = {k: ed for k, (_, ed) in R.week_files(editorial).items()}
    der = R.derived_fields(weeks, R.results_from_games(games, CFG), LOOKUP)
    regular = {2021: 13, 2022: 14, 2023: 14, 2024: 14, 2025: 14, 2026: 14}
    known = pub.known_fn(FILES, regular)
    reasons: dict = {}
    for name, d in covered.items():
        ed, snap = R.split(d)
        view = R.merge(ed, snap, der[(d["season"], d["week"])], LOOKUP)
        for path, eng, leg in diff(view, d, f"/{name}"):
            why = known(path, eng, leg)
            assert why, f"{path}: legacy={leg!r} engine={eng!r}"
            reasons[why] = reasons.get(why, 0) + 1
    assert len(covered) == 52 and sum(reasons.values()) > 0
    # the 2026 rule itself: running average including the week, blank in week 1
    w3 = der[(2026, 3)][LOOKUP["charlie gorman"]]
    assert w3["avg_rank"] == round((1 + 1 + 3) / 3, 1) and der[(2026, 1)][LOOKUP["charlie gorman"]]["avg_rank"] is None


def test_record_fields_rules():
    res = pd.DataFrame({"week": [1, 2, 3, 4], "points": [100.0, 90.0, 0.0, 120.555],
                        "result": ["W", "L", "L", "T"], "counts_ppg": [True, True, False, True]})
    out = R.record_fields(res)
    assert out == {"ppg_to_date": round((100 + 90 + 120.555) / 3, 2), "record_to_date": "1-2-1",
                   "last_score": 120.555, "streak": "T1"}
    assert R.record_fields(res.iloc[:3])["streak"] == "L2"
    assert R.record_fields(res.iloc[0:0]) == {"ppg_to_date": None, "record_to_date": "0-0", "last_score": None,
                                              "streak": None}


def test_manifest_is_generated_from_the_editorial_files():
    editorial = {n: R.split(d)[0] if n in WEEKS else d for n, d in FILES.items() if n != "manifest.json"}
    assert R.manifest(editorial) == FILES["manifest.json"]


def test_week_one_draft_measures_reproduce_the_published_file():
    w1 = FILES["2026_week01.json"]
    for t in w1["teams"]:
        assert R.adp_value(t["draft_picks"]) == t["adp_value"], t["manager"]
        assert R.position_spend(t["draft_picks"]) == t["position_spend"], t["manager"]
    assert R.position_spend([{"pos": "K", "round": 1}]) is None
    assert R.capital(3) == 0.5 and R.capital(6) == 0.25


def test_committed_editorial_and_snapshot_files_are_valid():
    import jsonschema

    base = ROOT / "leagues" / "preach"
    ed_v = jsonschema.Draft202012Validator(json.loads((SCHEMAS / "rankings-editorial.schema.json").read_text()))
    sn_v = jsonschema.Draft202012Validator(json.loads((SCHEMAS / "rankings-snapshot.schema.json").read_text()))
    editorial = R.load_folder(base, R.EDITORIAL_DIR)
    snaps = R.load_folder(base, R.SNAPSHOT_DIR)
    assert len(R.week_files(editorial)) >= 53 and len(snaps) >= 4
    for name, (_, d) in {k: v for k, v in R.week_files(editorial).items()}.items():
        assert not list(ed_v.iter_errors(d)), name
    for name, d in snaps.items():
        assert not list(sn_v.iter_errors(d)), name
        assert name in editorial, f"snapshot {name} has no editorial file"
    for name, d in editorial.items():
        for t in d.get("teams") or []:
            assert t["manager"].strip().lower() in LOOKUP, f"{name}: unknown manager {t['manager']}"


def test_week_model_keys_managers_and_drops_hidden():
    view = {"season": 2026, "week": 4, "teams": [{"manager": "Charlie Gorman", "rank": 1, "record_to_date": "2-1"},
                                                  {"manager": "Thomas Sullivan", "rank": 2, "record_to_date": "0-3"}],
            "undrafted_players": [{"player": "A", "pos": "QB", "manager": "Tee'd up"}, {"player": "B", "pos": "RB"}]}
    hidden = {LOOKUP["thomas sullivan"]}
    m = pub.week_model(view, LOOKUP, hidden, {"tee'd up": LOOKUP["charlie gorman"]})
    assert [t["manager_key"] for t in m["teams"]] == [LOOKUP["charlie gorman"]]
    assert m["undrafted_players"] == [{"manager_key": LOOKUP["charlie gorman"], "player": "A", "pos": "QB", "player_id": None},
                                      {"player": "B", "pos": "RB", "player_id": None}]


def test_week_model_names_players_by_id_and_paths_from_the_site_root():
    """Stage B pages find headshots by player id and images from the site root (B4)."""
    ids = {("Qb One", "QB"): 1, ("Rb Two", "RB"): 2, ("Wr Free", "WR"): 3}
    view = {"season": 2026, "week": 4,
            "teams": [{"manager": "Charlie Gorman", "rank": 1, "record_to_date": "2-1",
                       "draft_picks": [{"player": "Qb One", "pos": "QB", "round": 1, "pick_in_round": 1, "overall": 1},
                                       {"player": "Nobody", "pos": "TE", "round": 2, "pick_in_round": 1, "overall": 2}],
                       "screenshots": [{"id": "a", "file": "../images/rankings/week_04/a.png", "caption": ""},
                                       {"id": "b"}]}],
            "matchup_of_the_week": {"blurb": "x",
                                    "team_a": {"manager": "Charlie Gorman", "starters": [{"player": "Rb Two", "pos": "RB",
                                                                                           "slot": "RB"}]},
                                    "team_b": {"manager": "Ethan Radecki"}},
            "undrafted_players": [{"player": "Wr Free", "pos": "WR"}]}
    m = pub.week_model(view, LOOKUP, set(), None, lambda name, pos: ids.get((name, pos)))
    picks = m["teams"][0]["draft_picks"]
    assert [p["player_id"] for p in picks] == [1, None]
    assert m["teams"][0]["screenshots"] == [{"id": "a", "file": "images/rankings/week_04/a.png", "caption": ""}, {"id": "b"}]
    assert m["matchup_of_the_week"]["team_a"]["starters"][0]["player_id"] == 2
    assert m["matchup_of_the_week"]["team_b"] == {"manager_key": LOOKUP["ethan radecki"]}
    assert m["undrafted_players"] == [{"player": "Wr Free", "pos": "WR", "player_id": 3}]
    assert pub.site_path("../images/x.png") == "images/x.png" and pub.site_path("/images/x.png") == "images/x.png"


def test_player_id_resolver_matches_spellings():
    from engine.publish.pages.headshots import id_resolver
    names = pd.DataFrame({"player_id": [1, 2, 3, 4, 5],
                          "player_name": ["Kenneth Walker III", "Amon-Ra St. Brown", "Josh Allen", "Josh Allen", "Taysom Hill"],
                          "position": ["RB", "WR", "QB", "QB", "TE"], "season": [2025, 2025, 2019, 2025, 2025]})
    resolve = id_resolver(names)
    assert resolve("Kenneth Walker", "RB") == 1          # suffix dropped
    assert resolve("Amon-Ra St Brown", "WR") == 2        # punctuation ignored
    assert resolve("Josh Allen", "QB") == 4              # a shared name: the latest season's player
    assert resolve("Taysom Hill", "QB") == 5             # listed at another position, one player by that name
    assert resolve("Josh Allen", "LB") is None           # two players by that name, neither at this position
    assert resolve("Nobody", "QB") is None and resolve(None, "QB") is None


def _tiny_tables():
    k1, k2 = LOOKUP["charlie gorman"], LOOKUP["ethan radecki"]
    players = pd.DataFrame({"player_id": [1, 2, 3, 4, 5], "player_name": ["Qb One", "Rb Two", "Wr Free", "Rb Moved",
                                                                         "K Kick"],
                            "position": ["QB", "RB", "WR", "RB", "K"]})
    stats = pd.DataFrame({"season": 2026, "player_id": [1, 2, 3, 4, 5], "pro_team_id": [10, 11, 10, 11, 10],
                          "total_points": [50.0, 30.0, 12.5, 20.0, 9.0], "position": ["QB", "RB", "WR", "RB", "K"]})
    picks = pd.DataFrame({"season": 2026, "overall_pick": [1, 2, 3, 4], "round": [1, 1, 2, 2],
                          "round_pick": [1, 2, 2, 1], "player_id": [1, 2, 4, 5], "manager_key": [k1, k2, k1, k2]})
    proj = pd.DataFrame({"season": 2026, "week": 5, "source": "roster", "player_id": [1, 2, 4],
                         "pro_team_id": [10, 11, 11], "manager_key": [k1, k2, k2]})
    pro_teams = pd.DataFrame({"season": 2026, "pro_team_id": [10, 11], "abbrev": ["KC", "BUF"], "bye_week": [9, 7]})
    pro_games = pd.DataFrame({"season": 2026, "week": 5, "pro_team_id": [10, 11], "opponent_pro_team_id": [11, 10],
                              "home": [True, False]})
    adp = pd.DataFrame({"season": 2026, "source": "espn", "player_id": pd.array([1, 2, 4], "Int64"),
                        "adp": [2.0, 1.0, 6.0]})
    return {"players": players, "player_stats": stats, "draft_picks": picks, "projections": proj,
            "pro_teams": pro_teams, "pro_games": pro_games, "adp": adp, "lineups": pd.DataFrame()}, k1, k2


def test_snapshot_rosters_totals_and_opponents():
    t, k1, k2 = _tiny_tables()
    names = lambda k: {k1: "Charlie Gorman", k2: "Ethan Radecki"}[k]
    picks = R.draft_record(t, {}, 2026, names)
    assert [(p["player"], p["overall"], p["espn_adp"], p["adp_deviation"], p["nfl_team"]) for p in picks[k1]] == [
        ("Qb One", 1, 2.0, 1.0, "KC"), ("Rb Moved", 3, 6.0, 3.0, "BUF")]
    totals, undrafted = R.rosters_and_totals(t, 2026, picks, names)
    # Rb Moved was drafted by k1 and is on k2's roster now; Wr Free was never drafted and is a free agent
    assert undrafted == [{"player": "Rb Moved", "pos": "RB", "nfl_team": "BUF", "manager": "Ethan Radecki"},
                         {"player": "Wr Free", "pos": "WR", "nfl_team": "KC"}]
    assert totals == {"Qb One|QB": 50.0, "Rb Moved|RB": 20.0, "Rb Two|RB": 30.0, "Wr Free|WR": 12.5}
    assert R._opponents(t, 2026, 5, {10: "KC", 11: "BUF"}) == {10: "BUF", 11: "@KC"}
    assert R._opponents({**t, "pro_games": pd.DataFrame()}, 2026, 5, {}) == {}


def test_split_tool_imports_and_is_idempotent(tmp_path):
    import importlib.util

    site = tmp_path / "site"
    (site / "data" / "rankings").mkdir(parents=True)
    for n in ("2026_week04.json", "2025_week14.json", "2025_playoff_quarterfinals.json", "manifest.json"):
        (site / "data" / "rankings" / n).write_text(json.dumps(FILES[n]), encoding="utf-8")
    league = tmp_path / "league"
    league.mkdir()
    (league / "league.yaml").write_text("x: 1\n")
    spec = importlib.util.spec_from_file_location("split_rankings", ROOT / "tools" / "split_rankings.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.main([str(league / "league.yaml"), "--site", str(site)]) == 0
    ed = R.load_folder(league, R.EDITORIAL_DIR)
    assert set(ed) == {"2026_week04.json", "2025_week14.json", "2025_playoff_quarterfinals.json"}
    assert set(R.load_folder(league, R.SNAPSHOT_DIR)) == {"2026_week04.json"}
    before = {p: p.stat().st_mtime_ns for p in league.rglob("*.json")}
    assert mod.main([str(league / "league.yaml"), "--site", str(site)]) == 0
    assert before == {p: p.stat().st_mtime_ns for p in league.rglob("*.json")}


def test_index_model_lists_weeks_and_previews():
    editorial = {n: R.split(d)[0] if n in WEEKS else d for n, d in FILES.items() if n != "manifest.json"}
    idx = pub.index_model(editorial)
    first = idx["seasons"][0]
    assert first["season"] == 2026 and [w["file"] for w in first["weeks"]][:2] == ["2026-w01.json", "2026-w02.json"]
    s2025 = next(s for s in idx["seasons"] if s["season"] == 2025)
    assert s2025["previews"] == [{"round": "quarterfinals", "file": "2025-playoff-quarterfinals.json"}]
    s2023 = next(s for s in idx["seasons"] if s["season"] == 2023)
    assert s2023["weeks"][-1] == {"week": 15, "label": "End of Season", "file": "2023-w15.json"}


def test_rankings_page_lists_its_data():
    from engine.publish.site import PAGES

    page = next(p for p in PAGES if p["id"] == "weekly-rankings")
    assert "data/v1/weekly-rankings/index.json" in page["data"]


# ---------------------------------------------------------------- draft weeks (automatic Tuesday start)

def _draft(**over):
    teams = [{"manager": "Charlie Gorman", "rank": 1, "synopsis": "s", "blurb": "b"},
             {"manager": "Ethan Radecki", "rank": 2, "synopsis": "s", "blurb": "b"}]
    d = {"season": 2026, "week": 6, "status": "draft", "teams": teams,
         "matchup_of_the_week": {"team_a": "Charlie Gorman", "team_b": "Ethan Radecki", "blurb": "m"}}
    d.update(over)
    return d


def test_draft_weeks_stay_off_the_site():
    files = {"2026_week05.json": {"season": 2026, "week": 5, "teams": []},
             "2026_week06.json": _draft(),
             "2026_week04.json": {"season": 2026, "week": 4, "status": "published", "teams": []}}
    assert set(R.published(files)) == {"2026_week04.json", "2026_week05.json"}
    assert set(R.drafts(files)) == {"2026_week06.json"}
    assert [s["weeks"] for s in R.manifest(R.published(files))] == [[4, 5]]
    # the status never reaches the published week file
    assert "status" not in R.merge(files["2026_week04.json"], None, {}, LOOKUP)


def test_publish_problems():
    expected = ["Charlie Gorman", "Ethan Radecki"]
    assert R.problems(_draft(), expected, LOOKUP) == ([], [])
    dup = _draft(teams=[{**t, "rank": 1} for t in _draft()["teams"]])
    assert R.problems(dup, expected, LOOKUP)[0] == ["rank 1 given to Charlie Gorman, Ethan Radecki"]
    gap = _draft(teams=[{**t, "rank": r} for t, r in zip(_draft()["teams"], (1, 3))])
    assert R.problems(gap, expected, LOOKUP)[0] == ["ranks must be 1 to 2, once each"]
    errs, _ = R.problems(_draft(), expected + ["Max Malich"], LOOKUP)
    assert errs == ["not ranked: Max Malich"]
    empty = _draft(teams=[{**t, "blurb": "", "synopsis": ""} for t in _draft()["teams"]])
    errs, warns = R.problems(empty, expected, LOOKUP)
    assert errs == ["no blurbs written yet"] and len(warns) == 4
    same = _draft(matchup_of_the_week={"team_a": "Charlie Gorman", "team_b": "charlie gorman", "blurb": "x"})
    assert R.problems(same, expected, LOOKUP)[0] == ["matchup of the week names the same manager twice"]
    dash = _draft(teams=[{**_draft()["teams"][0], "blurb": "a " + chr(0x2014) + " b"}, _draft()["teams"][1]])
    assert R.problems(dash, expected, LOOKUP)[1] == ["contains an em dash"]
    nomotw = {k: v for k, v in _draft().items() if k != "matchup_of_the_week"}
    assert R.problems(nomotw, expected, LOOKUP) == ([], ["no matchup of the week"])


def test_publish_week_flips_the_status(tmp_path):
    ed = tmp_path / R.EDITORIAL_DIR
    R.write_json(ed / "2026_week06.json", _draft(teams=[{**t, "rank": 1} for t in _draft()["teams"]]))
    R.write_json(tmp_path / R.SNAPSHOT_DIR / "2026_week06.json",
                 {"season": 2026, "week": 6, "teams": [{"manager": "Charlie Gorman"}, {"manager": "Ethan Radecki"}]})
    path, errors, _ = pub.publish_week(tmp_path, None, 6, LOOKUP)
    assert errors and R.is_draft(R.read_json(path))          # refused, file untouched
    R.write_json(path, _draft())
    path, errors, warnings = pub.publish_week(tmp_path, 2026, 6, LOOKUP)
    out = R.read_json(path)
    assert errors == [] and list(out)[:3] == ["season", "week", "status"] and out["status"] == "published"
    assert not R.is_draft(out) and set(R.published(R.load_folder(tmp_path, R.EDITORIAL_DIR))) == {"2026_week06.json"}


def _season_tables(finished_weeks: int, regular: int = 14, drafted: bool = True) -> dict:
    rows = []
    for w in range(1, regular + 4):
        for tid in (1, 2):
            rows.append({"season": 2026, "week": w, "is_bye": False, "is_playoff_week": w > regular,
                         "tier": "WINNERS_BRACKET" if w > regular else None,
                         "result": ("W" if tid == 1 else "L") if w <= finished_weeks else "UNDECIDED"})
    seasons = pd.DataFrame([{"season": 2026, "regular_season_periods": regular, "final_scoring_period": regular + 3}])
    picks = pd.DataFrame({"season": [2026], "player_id": [1 if drafted else None]})
    return {"matchups": pd.DataFrame(rows), "seasons": seasons, "draft_picks": picks}


def test_next_week_to_start():
    assert R.next_week(_season_tables(5)) == ((2026, 6), "")
    assert R.next_week(_season_tables(0)) == ((2026, 1), "")
    assert R.next_week(_season_tables(0, drafted=False))[0] is None
    assert R.next_week(_season_tables(14))[0] is None              # playoffs: previews are written by hand
    assert R.next_week(_season_tables(17)) == (None, "no live season")


def test_start_week_is_safe_to_repeat(tmp_path):
    class Ctx:
        tables = _season_tables(5)
        league_dir = tmp_path
    assert pub.start_week(Ctx()) == ([], "this league writes no weekly rankings (no editorial/rankings folder)")
    (tmp_path / R.EDITORIAL_DIR).mkdir(parents=True)
    R.write_json(tmp_path / R.SNAPSHOT_DIR / "2026_week06.json", {"season": 2026, "week": 6})
    assert pub.start_week(Ctx()) == ([], "2026 week 6 is already started")


def test_deploy_runs_tuesday_5am_new_york_and_starts_the_week():
    import yaml
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8"))
    crons = [c["cron"] for c in wf[True]["schedule"]]          # yaml reads the key `on` as True
    assert {"7 9 * * 2", "7 10 * * 2"} <= set(crons)
    gate = wf["jobs"]["gate"]["steps"][0]["run"]
    assert all(c in gate for c in crons if c != "23 13 * * 5")
    steps = wf["jobs"]["engine"]["steps"]
    start = next(s for s in steps if "rankings start" in s.get("run", ""))
    assert start["continue-on-error"] is True and "start_week" in start["if"]
    assert wf["jobs"]["engine"]["permissions"]["contents"] == "write"


def test_publish_formats_plain_text_blurbs(tmp_path):
    vocab = json.loads((GOLDEN / "blurbs" / "vocab_2026.json").read_text(encoding="utf-8"))
    d = _draft()
    d["teams"][0].update(blurb="Charlie scored 150 points. Next week is harder.", synopsis="")
    d["teams"][1].update(blurb='<mark class="hl-player">Kept</mark> as written.', synopsis="Mine.")
    d["matchup_of_the_week"]["blurb"] = "Both are 3-1. **Charlie wins.**"
    R.write_json(tmp_path / R.EDITORIAL_DIR / "2026_week06.json", d)
    path, errors, _ = pub.publish_week(tmp_path, 2026, 6, LOOKUP, vocab=vocab)
    out = R.read_json(path)
    a, b = out["teams"]
    assert errors == [] and a["synopsis"] == "Charlie scored 150 points."
    assert a["blurb"].startswith('<strong class="hl-key"><mark class="hl-manager"') and 'hl-stat">150<' in a["blurb"]
    assert b == d["teams"][1]
    assert out["matchup_of_the_week"]["blurb"].endswith('<strong class="hl-key"><mark class="hl-manager" '
                                                        'style="color:#28843a;">Charlie</mark> wins.</strong>')
