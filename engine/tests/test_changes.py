"""The M1 change report (engine/publish/changes.py): how two versions of a legacy file are compared."""

from __future__ import annotations

import json
from pathlib import Path

from engine.publish import changes


def diff(old, new, live=2026) -> changes.Tally:
    t = changes.Tally(live, examples=50)
    changes.compare(old, new, "", t)
    return t


def test_a_reordered_list_is_not_a_change():
    old = [{"manager": "A", "season": 2024, "pf": 1.5}, {"manager": "B", "season": 2024, "pf": 2.5}]
    assert diff(old, old[::-1]).total == 0
    assert diff({"x": [3, 1, 2]}, {"x": [1, 2, 3]}).total == 0


def test_a_renamed_player_is_a_changed_value_not_two_records():
    t = diff([{"player": "Travis Etienne", "season": 2023, "pts": 20}],
             [{"player": "Travis Etienne Jr.", "season": 2023, "pts": 21}])
    assert (t.changed, t.only_engine, t.only_live) == (2, 0, 0)
    assert t.examples[0] == "[Travis Etienne, 2023]/player: Travis Etienne -> Travis Etienne Jr."


def test_kinds_of_difference():
    t = diff({"a": None, "b": 3.0, "c": 135.1, "d": 4.33, "e": 0.14, "f": 52},
             {"a": 7, "b": None, "c": 135.05, "d": 4.3, "e": 0.0, "f": 51})
    assert (t.filled, t.blanked, t.rounding, t.changed) == (1, 1, 2, 2)     # 0.14 -> 0.0 and 52 -> 51 are real
    assert t.total == 4


def test_sides_listed_the_other_way_round():
    old = [{"season": 2025, "week": 12, "team_a": "A", "team_b": "B", "score_a": 100.5, "score_b": 90.0}]
    new = [{"season": 2025, "week": 12, "team_a": "B", "team_b": "A", "score_a": 90.0, "score_b": 100.5}]
    t = diff(old, new)
    assert (t.swapped, t.total) == (1, 0)
    new[0]["score_a"] = 91.0                                                  # swapped and a changed score
    t = diff(old, new)
    assert (t.swapped, t.changed) == (1, 1)


def test_one_row_per_side_pairs_each_row_with_its_own():
    rows = [{"Team_Name": "A", "Opponent_Name": "B", "Outcome": "Win", "Team_Score": 10.0, "Opponent_Score": 9.0,
             "Season_Year": 2020, "Week": "Week 1"},
            {"Team_Name": "B", "Opponent_Name": "A", "Outcome": "Loss", "Team_Score": 9.0, "Opponent_Score": 10.0,
             "Season_Year": 2020, "Week": "Week 1"}]
    t = diff({"rows": rows}, {"rows": rows[::-1]})
    assert (t.total, t.swapped) == (0, 0)


def test_newer_records_are_counted_apart():
    t = diff({"2025": 1, "list": [{"season": 2025, "m": "A"}]},
             {"2025": 1, "2026": 2, "list": [{"season": 2025, "m": "A"}, {"season": 2026, "m": "A"}]})
    assert (t.newer, t.total) == (2, 0)
    t = diff({}, {"2027": 1}, live=None)                                    # no live season: a plain new key
    assert (t.newer, t.only_engine) == (0, 1)


def test_a_renumbered_pick_is_the_same_pick():
    t = diff([{"season": 2021, "round": 11, "pick": 160, "player": "Amon-Ra St. Brown", "surplus": 6.0}],
             [{"season": 2021, "round": 11, "pick": 154, "player": "Amon-Ra St. Brown", "surplus": 6.2}])
    assert (t.changed, t.only_engine, t.only_live) == (2, 0, 0)


def test_records_without_a_name_are_named_by_their_own_records():
    node = lambda gid, a, b, q: {"gid": gid, "season": 2020, "sp": 3, "multi": False,       # noqa: E731
                                 "managers": [{"m": a, "quad": q}, {"m": b, "quad": -q}]}
    old = [node(1, "A", "B", 0.5), node(2, "C", "D", 0.1)]
    new = [node(1, "C", "D", 0.2), node(2, "A", "B", 0.5)]
    t = diff(old, new)
    assert (t.only_engine, t.only_live) == (0, 0)
    assert t.changed == 4                                    # two gids and two quads


def _site(root: Path, js: str, page: str, rows: str) -> None:
    (root / "data").mkdir(parents=True)
    (root / "pages").mkdir()
    (root / "data" / "trade_data.js").write_text(js, encoding="utf-8")
    (root / "pages" / "champions.html").write_text(page, encoding="utf-8")
    (root / "data" / "matchup_data.csv").write_text(rows, encoding="utf-8")


def test_the_report_end_to_end(tmp_path):
    live, dist = tmp_path / "live", tmp_path / "dist"
    rows = ",Team_Name,Outcome,Team_Score,Opponent_Name,Opponent_Score,Week,Season_Year,Is_Playoff\n"
    _site(live, "var MOST_TRADED = [{\"player\": \"X\", \"count\": 2}];\n",
          "<script>\nvar CHAMPS = [{\"m\": \"A\", \"rs_ppg\": 118.7}];\nfunction f(){}\n</script>",
          rows + "0,A,Win,10.0,B,9.0,Week 1,2025,No\n1,B,Loss,9.0,A,10.0,Week 1,2025,No\n")
    _site(dist, "var MOST_TRADED = [{\"player\": \"X\", \"count\": 3}];\n",
          "<script>\nvar CHAMPS = [{\"m\": \"A\", \"rs_ppg\": 118.73}];\nfunction f(){}\n</script>",
          rows + "0,B,Loss,9.0,A,10.0,Week 1,2025,No\n1,A,Win,10.0,B,9.0,Week 1,2025,No\n"
          "2,A,Win,12.0,B,8.0,Week 1,2026,No\n3,B,Loss,8.0,A,12.0,Week 1,2026,No\n")
    files = ["data/trade_data.js", "pages/champions.html", "data/matchup_data.csv", "data/v1/index.json"]
    (dist / "build-manifest.json").write_text(json.dumps(
        {"build": {"id": "b1"}, "files": [{"path": f, "source": "generated"} for f in files]}))
    (dist / "config.json").write_text(json.dumps({"live_season": 2026}))
    (dist / "verify.json").write_text(json.dumps({"info": ["INFO  champions.html: 3 cards differ", "INFO  other"]}))

    rep = changes.write(dist, live)
    assert rep["build"]["id"] == "b1" and rep["unassigned"] == ["data/trade_data.js"]   # no page lists it
    pages = {p["id"]: p for p in rep["pages"]}
    champs = pages["champions"]
    assert champs["info"] == ["champions.html: 3 cards differ"]
    assert champs["files"][0]["rounding"] == 1 and champs["files"][0]["differences"] == 0
    csv = pages["matchups"]["files"]
    assert [(f["path"], f["differences"], f["newer"]) for f in csv] == [("data/matchup_data.csv", 0, 2)]
    page = (dist / "changes.html").read_text(encoding="utf-8")
    assert "<h2>Champions</h2>" in page and chr(0x2014) not in page
    assert json.loads((dist / "changes.json").read_text())["pages"][0]["id"] == "matchups"
    assert any(line.startswith("Champions: 0 differences") for line in changes.summary_lines(rep))


def test_the_command_line(tmp_path, capsys):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "change_report", Path(__file__).resolve().parents[2] / "tools" / "change_report.py")
    change_report = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(change_report)

    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "build-manifest.json").write_text(json.dumps({"build": {"id": "b2"}, "files": []}))
    (dist / "config.json").write_text("{}")
    assert change_report.main(["--dist", str(dist), "--site", str(tmp_path)]) == 0
    assert "Matchups: 0 differences" in capsys.readouterr().out
    assert (dist / "changes.html").is_file()
