import json

import pandas as pd

from engine import legacy
from engine.identity import member_key
from engine.normalize.espn import entry_points, game_rows, normalize_league, slot_label

RAW_A = "{AAAAAAAA-0000-0000-0000-000000000001}"
RAW_B = "{BBBBBBBB-0000-0000-0000-000000000002}"
RAW_C = "{CCCCCCCC-0000-0000-0000-000000000003}"


def entry(pid, name, pos_id, slot_id, week, pts, proj=99.0):
    return {"playerId": pid, "lineupSlotId": slot_id, "playerPoolEntry": {
        "appliedStatTotal": pts,
        "player": {"fullName": name, "defaultPositionId": pos_id, "stats": [
            {"statSourceId": 1, "scoringPeriodId": week, "seasonId": 2024, "appliedTotal": proj},   # projection
            {"statSourceId": 0, "scoringPeriodId": 0, "seasonId": 2024, "appliedTotal": 250.0},    # season total
            {"statSourceId": 0, "scoringPeriodId": week, "seasonId": 2024, "appliedTotal": pts},    # the week
        ]}}}


def side(team_id, total, entries):
    return {"teamId": team_id, "totalPoints": total, "rosterForCurrentScoringPeriod": {"entries": entries}}


def box(week, games):
    return {"schedule": games}


def write_league(tmp_path):
    d = tmp_path / "2024"
    d.mkdir()
    league = {
        "settings": {"scheduleSettings": {"matchupPeriodCount": 1, "playoffTeamCount": 2},
                     "acquisitionSettings": {"isUsingAcquisitionBudget": True, "acquisitionBudget": 300}},
        "status": {"finalScoringPeriod": 2, "isActive": False},
        "members": [{"id": RAW_A, "firstName": "Ann", "lastName": "A"},
                    {"id": RAW_B, "firstName": "Bob", "lastName": "B"},
                    {"id": RAW_C, "firstName": "Cy", "lastName": "C"}],
        "teams": [{"id": 1, "name": "Aces", "owners": [RAW_A], "primaryOwner": RAW_A},
                  {"id": 2, "name": "Bees", "owners": [RAW_B], "primaryOwner": RAW_B},
                  {"id": 3, "name": "Cats", "owners": [RAW_C], "primaryOwner": RAW_C}],
    }
    (d / "league.json").write_text(json.dumps(league))
    week1 = box(1, [
        {"id": 1, "matchupPeriodId": 1, "playoffTierType": "NONE", "winner": "AWAY",
         "home": side(1, 90.0, [entry(10, "QB One", 1, 0, 1, 20.0), entry(11, "Bench Guy", 2, 20, 1, 7.5)]),
         "away": side(2, 110.5, [entry(20, "D/ST Two", 16, 16, 1, -3.0)])},
        {"id": 2, "matchupPeriodId": 1, "playoffTierType": "NONE", "winner": "UNDECIDED",
         "home": side(3, 88.0, [entry(30, "Bye Guy", 3, 4, 1, 12.0)])},
    ])
    week2 = box(2, [
        {"id": 3, "matchupPeriodId": 2, "playoffTierType": "WINNERS_BRACKET", "winner": "HOME",
         "home": side(2, 101.0, [entry(20, "D/ST Two", 16, 16, 2, 5.0)]),
         "away": side(1, 99.0, [entry(10, "QB One", 1, 0, 2, 18.0)])},
        {"id": 4, "matchupPeriodId": 2, "playoffTierType": "LOSERS_CONSOLATION_LADDER", "winner": "UNDECIDED",
         "home": side(3, 70.0, [entry(30, "Bye Guy", 3, 4, 2, 9.0)])},
    ])
    (d / "week_01_boxscore.json").write_text(json.dumps(week1))
    (d / "week_02_boxscore.json").write_text(json.dumps(week2))
    (d / "draft.json").write_text(json.dumps({"draftDetail": {"picks": [
        {"overallPickNumber": 1, "roundId": 1, "roundPickNumber": 1, "teamId": 2, "playerId": 20}]}}))
    return tmp_path


def test_entry_points_uses_the_weeks_actual_line():
    assert entry_points(entry(1, "X", 1, 0, 3, 17.25), 2024, 3) == 17.25


def test_slot_labels_match_site_conventions():
    assert [slot_label(i) for i in (0, 23, 16, 20, 21)] == ["QB", "RB/WR/TE", "D/ST", "BE", "IR"]
    assert slot_label(99) == "SLOT_99"


def test_game_rows_results_byes_and_tiers():
    m, lu = game_rows(2024, 1, json.loads(json.dumps(box(1, [
        {"id": 1, "matchupPeriodId": 1, "playoffTierType": "NONE", "winner": "HOME",
         "home": side(1, 100.0, []), "away": side(2, 90.0, [])},
        {"id": 2, "matchupPeriodId": 1, "playoffTierType": "NONE", "winner": "UNDECIDED",
         "home": side(3, 80.0, [])}]))), regular_periods=13)
    assert [(r["team_id"], r["result"], r["is_bye"]) for r in m] == [(1, "W", False), (2, "L", False), (3, "BYE", True)]
    assert all(r["tier"] == "REGULAR" and not r["is_playoff_week"] for r in m)
    assert [r["score_tied"] for r in m] == [False, False, False]
    tied, _ = game_rows(2024, 15, {"schedule": [
        {"id": 9, "matchupPeriodId": 15, "playoffTierType": "WINNERS_CONSOLATION_LADDER", "winner": "HOME",
         "home": side(1, 101.3, []), "away": side(2, 101.3, [])}]}, regular_periods=14)
    assert [(r["result"], r["score_tied"], r["tier"]) for r in tied] == [
        ("W", True, "WINNERS_CONSOLATION_LADDER"), ("L", True, "WINNERS_CONSOLATION_LADDER")]


def test_normalize_league_end_to_end(tmp_path):
    t = normalize_league(write_league(tmp_path))
    assert set(t) == {"seasons", "managers", "teams", "matchups", "lineups", "draft_picks", "players"}

    s = t["seasons"].iloc[0]
    assert s["team_count"] == 3 and s["regular_season_periods"] == 1 and s["faab_budget"] == 300

    m = t["matchups"]
    ann = member_key(RAW_A)
    row = m[(m.week == 1) & (m.team_id == 1)].iloc[0]
    assert row.manager_key == ann and row.opponent_manager_key == member_key(RAW_B) and row.result == "L"
    assert m[(m.week == 2) & (m.team_id == 2)].iloc[0].is_playoff_week

    lu = t["lineups"]
    dst = lu[(lu.week == 1) & (lu.player_id == 20)].iloc[0]
    assert dst.points == -3.0 and dst.position == "D/ST"          # raw ESPN points, no floor
    assert not lu[lu.player_id == 11].iloc[0].started              # bench
    assert t["draft_picks"].iloc[0].manager_key == member_key(RAW_B)
    assert not any("{" in str(v) for v in t["managers"]["manager_key"])  # no raw ids anywhere


def test_rosters_check_keeps_bye_team_in_regular_season_and_bracket_only_in_playoffs(tmp_path):
    t = normalize_league(write_league(tmp_path))
    cfg = {"managers": [{"name": "Ann A", "id": member_key(RAW_A)}, {"name": "Bob B", "id": member_key(RAW_B)},
                        {"name": "Cy C", "id": member_key(RAW_C)}]}
    legacy_rosters = pd.DataFrame([
        # week 1: all teams, including Cy on a bye
        (2024, 1, "Ann A", 10, "QB One", "QB", "QB", True, 20.0),
        (2024, 1, "Ann A", 11, "Bench Guy", "RB", "BE", False, 7.5),
        (2024, 1, "Bob B", 20, "D/ST Two", "D/ST", "D/ST", True, -3.0),
        (2024, 1, "Cy C", 30, "Bye Guy", "WR", "WR", True, 12.0),
        # week 2 (playoffs): winners bracket only, so no Cy
        (2024, 2, "Bob B", 20, "D/ST Two", "D/ST", "D/ST", True, 5.0),
        (2024, 2, "Ann A", 10, "QB One", "QB", "QB", True, 18.0),
    ], columns=["Season", "Week", "Manager", "Player_ID", "Player", "Position", "Slot", "Started", "Points"])
    result = legacy.check_rosters(t, legacy_rosters, cfg)
    assert result.ok, result.render()


def test_compare_reports_value_mismatch():
    exp = pd.DataFrame({"k": [1, 2], "v": [1.0, 2.0]})
    act = pd.DataFrame({"k": [1, 2], "v": [1.0, 2.5]})
    r = legacy.compare("t", exp, act, keys=["k"], values=["v"])
    assert not r.ok and r.mismatched["v"] == 1


def test_legacy_week_labels():
    labels = pd.Series(["Week 3", "Playoff Round 1", "Playoff Round 3"])
    seasons = pd.Series([2021, 2021, 2023])
    assert legacy.legacy_week(labels, seasons, {2021: 13, 2023: 14}).tolist() == [3, 14, 17]


def _tables(matchups=None, lineups=None, seasons=None):
    return {
        "matchups": pd.DataFrame(matchups or []),
        "lineups": pd.DataFrame(lineups or []),
        "seasons": pd.DataFrame(seasons or [{"season": 2020, "regular_season_periods": 13}]),
    }


def test_tiebreak_game_where_legacy_gave_both_teams_a_loss_is_excused_not_hidden():
    a, b = "m_aaaaaaaaaaaa", "m_bbbbbbbbbbbb"
    game = dict(season=2020, week=15, matchup_period=15, is_bye=False, tier="WINNERS_BRACKET",
                points=100.0, opponent_points=100.0)
    t = _tables(matchups=[
        {**game, "manager_key": a, "opponent_manager_key": b, "result": "W"},
        {**game, "manager_key": b, "opponent_manager_key": a, "result": "L"},
    ])
    cfg = {"managers": [{"name": "Ann A", "id": a}, {"name": "Bob B", "id": b}]}
    rows = [("Ann A", "Bob B", "Loss"), ("Bob B", "Ann A", "Loss")]
    legacy_df = pd.DataFrame([dict(Team_Name=x, Opponent_Name=y, Outcome=o, Team_Score=100.0, Opponent_Score=100.0,
                                   Week="Playoff Round 2", Season_Year=2020, Is_Playoff="Yes") for x, y, o in rows])
    r = legacy.check_matchups(t, legacy_df, cfg)
    assert r.ok and sum(r.known.values()) == 1, r.render()


def test_real_result_mismatch_still_fails():
    a, b = "m_aaaaaaaaaaaa", "m_bbbbbbbbbbbb"
    game = dict(season=2020, week=3, matchup_period=3, is_bye=False, tier="REGULAR",
                points=100.0, opponent_points=90.0)
    t = _tables(matchups=[
        {**game, "manager_key": a, "opponent_manager_key": b, "result": "L"},   # wrong on purpose
        {**game, "manager_key": b, "opponent_manager_key": a, "result": "W"},
    ])
    cfg = {"managers": [{"name": "Ann A", "id": a}, {"name": "Bob B", "id": b}]}
    rows = [("Ann A", "Bob B", "Win"), ("Bob B", "Ann A", "Loss")]
    legacy_df = pd.DataFrame([dict(Team_Name=x, Opponent_Name=y, Outcome=o, Team_Score=100.0, Opponent_Score=90.0,
                                   Week="Week 3", Season_Year=2020, Is_Playoff="No") for x, y, o in rows])
    assert not legacy.check_matchups(t, legacy_df, cfg).ok


def test_reclassified_player_position_is_excused_only_when_espn_used_it_another_season():
    a = "m_aaaaaaaaaaaa"
    row = dict(week=4, team_id=1, manager_key=a, player_id=15807, player_name="Flex Guy",
               slot="RB", started=True, points=10.0)
    t = _tables(
        matchups=[dict(season=2020, week=4, team_id=1, is_playoff_week=False, tier="REGULAR", is_bye=False)],
        lineups=[{**row, "season": 2020, "position": "WR"}, {**row, "season": 2021, "position": "RB"}],
    )
    cfg = {"managers": [{"name": "Ann A", "id": a}]}
    good = pd.DataFrame([dict(Season=2020, Week=4, Manager="Ann A", Player_ID=15807, Player="Flex Guy",
                              Position="RB", Slot="RB", Started=True, Points=10.0)])
    r = legacy.check_rosters(t, good, cfg)
    assert r.ok and sum(r.known.values()) == 1, r.render()
    bad = good.assign(Position="TE")          # TE was never his ESPN position: a real mismatch
    assert not legacy.check_rosters(t, bad, cfg).ok
