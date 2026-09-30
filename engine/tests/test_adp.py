import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from engine.config import validate_config
from engine.normalize.adp import (LIBRARY_ROOT, SNAPSHOT_SOURCE, build_adp, clean_name, library_file,
                                  load_library, match_key, match_players, position_order, read_export,
                                  snapshot_age_days, usable_snapshot)
from engine.normalize.espn import read_adp_snapshots
from engine.providers.espn import ADP_SNAPSHOT, EspnProvider, adp_snapshot, draft_date, draft_finished
from engine.tests.test_pull import FakeClient

GOLDEN = Path(__file__).resolve().parent / "golden"

# ---------------------------------------------------------------- export files

TAB_TITLED = ("Average Draft Position (ADP) - PPR Leagues 2021 | FantasyPros\nRank\nPlayer Team (Bye)\nPOS\n"
              "ESPN\nSleeper\nAVG\n"
              "1\tChristian McCaffrey CAR (13) \tRB1\t1\t1\t1.0\n"
              "2\tSan Francisco 49ers DST (6) \tDST1\t90\t88\t89.0\n"
              "3\tOdell Beckham Jr. CLE (13) \tWR1\t\t30\t30.0\n"          # no ESPN ADP: dropped
              "4\tTom Brady \tQB1\t50\t60\t55.0\n")                           # free agent, no team
TAB_ONE_LINE = ("\nRank\tPlayer Team (Bye)\tPOS\tESPN\tMFL\tAVG\n"
                "1\tSaquon Barkley NYG (11) \tRB1\t1\t1\t1.0\n"
                "2\tWashington Football Team DST (8) \tDST1\t140\t150\t145.0\n")
CSV_NEW = ("Rank,Player (Bye),POS,ESPN,Sleeper,AVG,Real-Time\n"
           "1,Jahmyr Gibbs   DET (6),RB1,1,1,1.0,1\n"
           "2,Houston Texans DST   (8),DST1,84,95,89.5,90  -1\n"
           "3,Tyreek Hill,WR1,229,232,230.5,237  +9\n"
           "4,Tyrone Tracy Jr.   NYG (8),RB2,,173,173.0,182\n")


def write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_reads_tab_export_with_one_header_name_per_line(tmp_path):
    df = read_export(write(tmp_path, "2021.txt", TAB_TITLED), 2021, "ESPN")
    assert df["player_name"].tolist() == ["Christian McCaffrey", "San Francisco 49ers", "Tom Brady"]
    assert df["position"].tolist() == ["RB", "D/ST", "QB"]
    assert df["adp"].tolist() == [1.0, 90.0, 50.0]
    assert df["pro_team"].iloc[0] == "CAR" and df["pro_team"].iloc[1:].isna().all()
    assert df["rank"].tolist() == [1, 2, 4]


def test_reads_tab_export_with_single_header_line_and_other_columns(tmp_path):
    p = write(tmp_path, "2020.txt", TAB_ONE_LINE)
    assert read_export(p, 2020, "ESPN")["adp"].tolist() == [1.0, 140.0]
    assert read_export(p, 2020, "MFL")["adp"].tolist() == [1.0, 150.0]


def test_reads_new_csv_export(tmp_path):
    df = read_export(write(tmp_path, "2026.csv", CSV_NEW), 2026, "ESPN")
    assert df["player_name"].tolist() == ["Jahmyr Gibbs", "Houston Texans", "Tyreek Hill"]
    assert df["position"].tolist() == ["RB", "D/ST", "WR"]
    assert df["adp"].tolist() == [1.0, 84.0, 229.0]


def test_missing_column_is_an_error(tmp_path):
    p = write(tmp_path, "2020.txt", TAB_ONE_LINE)
    try:
        read_export(p, 2020, "Yahoo")
    except ValueError as e:
        assert "Yahoo" in str(e)
    else:
        raise AssertionError("expected ValueError")


def test_shipped_library_parses_every_season():
    counts = {2018: 193, 2019: 590, 2020: 488, 2021: 231, 2022: 227, 2023: 498, 2024: 487, 2025: 493, 2026: 494}
    lib = load_library("fantasypros_ppr", list(counts), "espn")
    assert lib.groupby("season").size().to_dict() == counts
    assert library_file("fantasypros_ppr", 2017) is None
    assert (LIBRARY_ROOT / "fantasypros_ppr").is_dir()


# ---------------------------------------------------------------- names and matching

def test_name_keys():
    assert clean_name("Christian McCaffrey   CAR (13) ") == "Christian McCaffrey"
    assert match_key("Odell Beckham Jr.", "WR") == match_key("Odell Beckham", "WR") == "odell beckham"
    assert match_key("D.J. Moore", "WR") == match_key("DJ Moore", "WR")
    assert match_key("San Francisco 49ers", "D/ST") == match_key("49ers D/ST", "D/ST") == "49ers"
    assert match_key("Washington Football Team", "D/ST") == match_key("Commanders D/ST", "D/ST")


def test_match_needs_one_player_with_same_season_position_and_name():
    pool = pd.DataFrame({"season": [2024] * 4, "player_id": [1, 2, 3, 4],
                         "player_name": ["DJ Moore", "Mike Williams", "Mike Williams", "Texans D/ST"],
                         "position": ["WR", "WR", "WR", "D/ST"]})
    adp = pd.DataFrame({"season": [2024, 2024, 2024, 2024, 2023],
                        "player_name": ["D.J. Moore", "Mike Williams", "Houston Texans", "DJ Moore", "DJ Moore"],
                        "position": ["WR", "WR", "D/ST", "RB", "WR"]})
    ids, ambiguous = match_players(adp, pool)
    assert ids.iloc[0] == 1 and pd.isna(ids.iloc[1]) and ids.iloc[2] == 4   # the two Mike Williams stay unmatched
    assert ids.iloc[3:].isna().all()                  # wrong position, wrong season
    assert ambiguous["key"].tolist() == ["mike williams"]


def test_position_order_ranks_within_season_and_position_ties_by_source_order():
    adp = pd.DataFrame({"season": [2024] * 4 + [2025], "position": ["RB", "WR", "RB", "RB", "RB"],
                        "adp": [5.0, 1.0, 2.0, 5.0, 9.0]})
    assert position_order(adp).tolist() == [2.0, 1.0, 1.0, 3.0, 1.0]


# ---------------------------------------------------------------- snapshots and source choice

def tables(seasons=(2024, 2025)):
    ps = pd.DataFrame({"season": [s for s in seasons for _ in range(2)], "player_id": [10, 11] * len(seasons),
                       "player_name": ["Christian McCaffrey", "Tom Brady"] * len(seasons),
                       "position": ["RB", "QB"] * len(seasons)})
    dp = pd.DataFrame({"season": [s for s in seasons for _ in range(2)], "player_id": [10, 11] * len(seasons),
                       "overall_pick": [1, 2] * len(seasons)})
    return {"player_seasons": ps, "draft_picks": dp}


def cfg(**adp):
    return {"league": {"provider": "espn"}, "analysis": {"adp": adp} if adp else {}}


def snap(pulled, drafted):
    return {"pulled_at": pulled, "draft_date": drafted,
            "rows": [{"player_id": 11, "player_name": "Tom Brady", "position": "QB", "adp": 40.0},
                     {"player_id": 10, "player_name": "Christian McCaffrey", "position": "RB", "adp": 2.5}]}


def test_snapshot_age():
    assert snapshot_age_days(snap("2025-09-03T00:00:00+00:00", "2025-09-01T00:00:00+00:00")) == 2
    assert snapshot_age_days(snap("2025-09-03T00:00:00+00:00", None)) is None
    assert usable_snapshot(snap("2025-09-03T00:00:00+00:00", "2025-09-01T00:00:00+00:00"), 3)
    assert not usable_snapshot(snap("2025-10-01T00:00:00+00:00", "2025-09-01T00:00:00+00:00"), 3)
    assert not usable_snapshot(snap("2025-08-30T00:00:00+00:00", "2025-09-01T00:00:00+00:00"), 3)


def test_fresh_snapshot_wins_else_library(tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "2024.txt").write_text(TAB_TITLED, encoding="utf-8")
    (lib / "2025.txt").write_text(TAB_TITLED, encoding="utf-8")
    snaps = {2025: snap("2025-09-02T12:00:00+00:00", "2025-09-01T00:00:00+00:00")}
    adp, rep = build_adp(tables(), snaps, cfg(library="lib"), root=tmp_path)
    by = rep.set_index("season")
    assert by.loc[2024, "source"] == "lib" and by.loc[2025, "source"] == SNAPSHOT_SOURCE
    assert by.loc[2024, "picks_with_adp"] == 2 and by.loc[2025, "picks_with_adp"] == 2
    s25 = adp[adp["season"] == 2025]
    assert s25["player_id"].tolist() == [10, 11] and s25["rank"].tolist() == [1, 2]

    late = {2025: snap("2025-11-01T00:00:00+00:00", "2025-09-01T00:00:00+00:00")}
    adp, rep = build_adp(tables(), late, cfg(library="lib"), root=tmp_path)
    assert set(adp["source"]) == {"lib"}
    assert "too late" in rep.set_index("season").loc[2025, "snapshot"]


def test_season_with_no_source_gets_no_rows(tmp_path):
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "2024.txt").write_text(TAB_TITLED, encoding="utf-8")
    adp, rep = build_adp(tables(), {}, cfg(library="lib"), root=tmp_path)
    assert set(adp["season"]) == {2024}
    assert rep.set_index("season").loc[2025, "source"] == "none"


def test_no_library_and_no_snapshot_gives_an_empty_table(tmp_path):
    (tmp_path / "lib").mkdir()
    adp, rep = build_adp(tables(), {}, cfg(library="lib"), root=tmp_path)
    assert len(adp) == 0 and list(rep["picks_with_adp"]) == [0, 0]


# ---------------------------------------------------------------- the ESPN side

class DraftClient(FakeClient):
    def get(self, season, views, scoring_period=None, fantasy_filter=None, league_level=True):
        data = super().get(season, views, scoring_period, fantasy_filter, league_level)
        if "mSettings" in views:
            data["settings"]["draftSettings"] = {"date": 1756684800000}   # 2025-09-01 00:00 UTC
        if "mDraftDetail" in views:
            data["draftDetail"]["drafted"] = True
        if "kona_player_info" in views:
            for p in data["players"]:
                p["player"].update({"fullName": f"P{p['id']}", "defaultPositionId": 2,
                                    "ownership": {"averageDraftPosition": p["id"] / 10}})
        return data


def test_draft_state_and_date():
    assert draft_finished({"draftDetail": {"drafted": True}})
    assert not draft_finished({"draftDetail": {"drafted": False, "picks": [1]}})
    assert draft_finished({"draftDetail": {"picks": [1]}})
    assert not draft_finished({"draftDetail": {"picks": [1], "inProgress": True}})
    assert draft_date({}, {"draftDetail": {"completeDate": 1756684800000}}) == (
        "2025-09-01T00:00:00+00:00", "draftDetail.completeDate")
    assert draft_date({"settings": {"draftSettings": {"date": 1756684800000}}}, {})[1] == "settings.draftSettings.date"
    assert draft_date({}, {}) == (None, None)


def test_live_pull_saves_adp_once_and_normalize_reads_it(tmp_path):
    out = tmp_path / "123" / "2025"
    EspnProvider(DraftClient(active=True, pool=3)).pull_season(2025, out)
    raw = json.loads((out / ADP_SNAPSHOT).read_text())
    assert raw["draft_date"] == "2025-09-01T00:00:00+00:00"
    assert [r["adp"] for r in raw["players"]] == [10.0, 10.1, 10.2]

    (out / ADP_SNAPSHOT).write_text(json.dumps({**raw, "pulled_at": "2025-09-02T00:00:00+00:00"}))
    EspnProvider(DraftClient(active=True, pool=3)).pull_season(2025, out)       # later pull: kept as is
    kept = json.loads((out / ADP_SNAPSHOT).read_text())
    assert kept["pulled_at"] == "2025-09-02T00:00:00+00:00"

    snaps = read_adp_snapshots(tmp_path / "123")
    assert snaps[2025]["rows"][0] == {"player_id": 100, "player_name": "P100", "position": "RB", "adp": 10.0}
    assert usable_snapshot(snaps[2025], 3)


def test_finished_season_pull_saves_no_adp(tmp_path):
    out = tmp_path / "2024"
    EspnProvider(DraftClient(active=False)).pull_season(2024, out)
    assert not (out / ADP_SNAPSHOT).exists()


def test_snapshot_reads_the_cached_pool(tmp_path):
    (tmp_path / "players_000.json").write_text(json.dumps({"players": [
        {"id": 1, "player": {"id": 1, "fullName": "A", "defaultPositionId": 3, "ownership": {"averageDraftPosition": 4.5}}},
        {"id": 2, "player": {"id": 2, "fullName": "B", "defaultPositionId": 3, "ownership": {}}}]}))
    s = adp_snapshot(tmp_path, {}, {"draftDetail": {"completeDate": 1756684800000}},
                     now=datetime(2025, 9, 2, tzinfo=timezone.utc))
    assert s["players"] == [{"player_id": 1, "player_name": "A", "position_id": 3, "adp": 4.5}]
    assert s["pulled_at"] == "2025-09-02T00:00:00+00:00"


# ---------------------------------------------------------------- config

def test_adp_config_is_checked():
    base = {"league": {"name": "T", "provider": "espn", "league_id": 1, "first_season": 2020},
            "managers": [{"name": "A", "id": "x1", "colors": {"dark": "#112233", "light": "#445566"}}]}
    assert validate_config({**base, "analysis": {"adp": {"library": "fantasypros_ppr", "snapshot_max_days": 3}}}).ok
    assert not validate_config({**base, "analysis": {"adp": {"library": "nope"}}}).ok
    assert not validate_config({**base, "analysis": {"adp": {"snapshot_max_days": -1}}}).ok


# ---------------------------------------------------------------- legacy golden (runs in CI)

def test_reproduces_legacy_draft_adp_from_the_legacy_draft_file():
    """draft_fingerprint.py joined the FantasyPros ESPN column to the draft by
    name. Rebuild canonical-shaped tables from its own draft file (one id per
    season, name and position) and the engine must give every pick the same
    ADP and position order."""
    hist = pd.read_csv(GOLDEN / "draft" / "draft_history_with_adp.csv.gz")
    hist["position"] = hist["position"].replace({"DST": "D/ST"})
    ids = {k: i for i, k in enumerate(sorted(set(zip(hist["season"], hist["player_name"], hist["position"]))))}
    hist["player_id"] = [ids[k] for k in zip(hist["season"], hist["player_name"], hist["position"])]
    t = {"player_seasons": hist[["season", "player_id", "player_name", "position"]].drop_duplicates(),
         "draft_picks": hist[["season", "overall_pick", "player_id"]]}
    adp, _ = build_adp(t, {}, cfg(library="fantasypros_ppr"))
    adp["position_order"] = position_order(adp)
    got = hist.merge(adp.dropna(subset=["player_id"])[["season", "player_id", "adp", "position_order"]],
                     on=["season", "player_id"], how="left", suffixes=("_legacy", ""))
    assert got["adp"].isna().equals(got["adp_legacy"].isna())
    both = got["adp"].notna()
    assert (got.loc[both, "adp"] == got.loc[both, "adp_legacy"]).all()
    assert (got.loc[both, "position_order"] == got.loc[both, "position_order_legacy"]).all()
    assert both.sum() == 1186


# ---------------------------------------------------------------- engine normalize, end to end

def test_normalize_command_builds_the_adp_table(tmp_path):
    import engine.store as store
    from engine import cli
    from engine.tests.test_normalize import write_league

    raw = tmp_path / "cache" / "espn" / "1"
    raw.mkdir(parents=True)
    season_dir = write_league(raw) / "2024"
    cfg_path = tmp_path / "league.yaml"
    cfg_path.write_text("league: {name: T, provider: espn, league_id: 1, first_season: 2024}\n"
                        "managers: []\n", encoding="utf-8")
    written = {}
    original = store.write_tables
    store.write_tables = lambda tables, out: written.update(tables)
    try:
        assert cli.main(["normalize", str(cfg_path), "--cache", str(tmp_path / "cache")]) == 0
        assert set(written["adp"]["source"]) == {"fantasypros_ppr"}      # no draft-day copy: the library

        pid = int(written["draft_picks"]["player_id"].iloc[0])
        (season_dir / ADP_SNAPSHOT).write_text(json.dumps({
            "pulled_at": "2024-09-02T00:00:00+00:00", "draft_date": "2024-09-01T00:00:00+00:00",
            "players": [{"player_id": pid, "player_name": "X", "position_id": 2, "adp": 3.5}]}))
        assert cli.main(["normalize", str(cfg_path), "--cache", str(tmp_path / "cache")]) == 0
        adp = written["adp"]
        assert set(adp["source"]) == {SNAPSHOT_SOURCE} and adp["player_id"].tolist() == [pid]
    finally:
        store.write_tables = original
