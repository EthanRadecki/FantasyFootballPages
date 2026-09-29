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
    tx = {"transactions": [{"id": "tx-1", "type": "WAIVER", "status": "EXECUTED", "teamId": 3, "bidAmount": 12,
                            "scoringPeriodId": 1, "items": [
                                {"type": "ADD", "playerId": 40, "fromTeamId": 0, "toTeamId": 3},
                                {"type": "DROP", "playerId": 30, "fromTeamId": 3, "toTeamId": 0}]}]}
    (d / "week_01_transactions.json").write_text(json.dumps(tx))
    (d / "week_02_transactions.json").write_text(json.dumps(tx))   # same transaction reported twice
    cards = {"players": [
        {"player": {"id": 99, "fullName": "Cut Before Week One", "defaultPositionId": 3}, "transactions": []},
        {"player": {"id": 10, "fullName": "QB One", "defaultPositionId": 1}, "transactions": [
            {"id": "trade-9", "type": "TRADE_ACCEPT", "teamId": 1, "scoringPeriodId": 2, "items": [
                {"type": "TRADE", "playerId": 10, "fromTeamId": 1, "toTeamId": 2}]},
            {"id": "tx-1", "type": "WAIVER", "status": "EXECUTED", "teamId": 3, "scoringPeriodId": 1, "items": [
                {"type": "ADD", "playerId": 40, "fromTeamId": 0, "toTeamId": 3}]}]}]}
    (d / "playercards_000.json").write_text(json.dumps(cards))
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
    assert set(t) == {"seasons", "managers", "teams", "matchups", "lineups", "draft_picks", "transactions",
                      "player_seasons", "players", "player_stats"}

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
    tx = t["transactions"]
    assert len(tx) == 3                                                   # deduplicated across weeks and cards
    assert tx[tx.transaction_id == "tx-1"].source.eq("league").all()      # league feed wins duplicates
    trade = tx[tx.transaction_id == "trade-9"].iloc[0]
    assert trade.source == "playercard" and trade.item_type == "TRADE"   # trade only the card knew about
    ps = t["player_seasons"]
    assert ps[ps.player_id == 99].iloc[0].player_name == "Cut Before Week One"
    assert (tx[tx.transaction_id == "tx-1"].bid_amount == 12).all()
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
        matchups=[dict(season=2020, week=4, team_id=1, is_playoff_week=False, tier="REGULAR", is_bye=False, result="W")],
        lineups=[{**row, "season": 2020, "position": "WR"}, {**row, "season": 2021, "position": "RB"}],
    )
    cfg = {"managers": [{"name": "Ann A", "id": a}]}
    good = pd.DataFrame([dict(Season=2020, Week=4, Manager="Ann A", Player_ID=15807, Player="Flex Guy",
                              Position="RB", Slot="RB", Started=True, Points=10.0)])
    r = legacy.check_rosters(t, good, cfg)
    assert r.ok and sum(r.known.values()) == 1, r.render()
    bad = good.assign(Position="TE")          # TE was never his ESPN position: a real mismatch
    assert not legacy.check_rosters(t, bad, cfg).ok


def test_executed_moves_drops_proposals_failures_and_lineup_noise():
    from engine.normalize.moves import executed_moves
    tx = pd.DataFrame([
        {"type": "WAIVER", "status": "EXECUTED"},
        {"type": "WAIVER", "status": "FAILED_ROSTERLIMIT"},
        {"type": "WAIVER", "status": "CANCELED"},
        {"type": "TRADE_PROPOSAL", "status": "PENDING"},
        {"type": "TRADE_DECLINE", "status": "EXECUTED"},
        {"type": "FUTURE_ROSTER", "status": "EXECUTED"},
        {"type": "TRADE_ACCEPT", "status": None},
        {"type": "FREEAGENT", "status": "EXECUTED"},
    ])
    tx["source"] = "league"
    tx.loc[len(tx)] = {"type": "TRADE_ACCEPT", "status": None, "source": "playercard"}
    kept = executed_moves(tx)
    assert list(kept["type"]) == ["WAIVER", "FREEAGENT", "TRADE_ACCEPT"]
    assert list(kept["source"]) == ["league", "league", "playercard"]


def test_draft_check_matches_on_pick_and_derives_draft_slot():
    a, b = "m_aaaaaaaaaaaa", "m_bbbbbbbbbbbb"
    t = {
        "draft_picks": pd.DataFrame([
            dict(season=2024, overall_pick=1, round=1, round_pick=1, team_id=1, player_id=10, manager_key=a, draft_slot=1),
            dict(season=2024, overall_pick=2, round=1, round_pick=2, team_id=2, player_id=20, manager_key=b, draft_slot=2),
            dict(season=2024, overall_pick=3, round=2, round_pick=1, team_id=2, player_id=30, manager_key=b, draft_slot=2),
        ]),
        "player_seasons": pd.DataFrame([dict(season=2024, player_id=10, player_name="P Ten", position="RB"),
                                        dict(season=2024, player_id=20, player_name="P Twenty", position="WR"),
                                        dict(season=2024, player_id=30, player_name="Bears D/ST", position="D/ST")]),
        "lineups": pd.DataFrame([dict(season=2024, player_id=10, position="RB")]),
    }
    cfg = {"managers": [{"name": "Ann A", "id": a}, {"name": "Bob B", "id": b}]}
    legacy_df = pd.DataFrame([
        dict(season=2024, round=1, draft_slot=1, overall_pick=1, pick_in_round=1, player_name="P Ten", position="RB", manager="Ann A"),
        dict(season=2024, round=1, draft_slot=2, overall_pick=2, pick_in_round=2, player_name="P Twenty", position="WR", manager="Bob B"),
        dict(season=2024, round=2, draft_slot=2, overall_pick=3, pick_in_round=1, player_name="Bears D/ST", position="D/ST", manager="Bob B"),
    ])
    r = legacy.check_draft(t, legacy_df, cfg)
    assert r.ok, r.render()


def test_draft_order_correction_renumbers_picks_and_keeps_espn_numbers():
    from engine.normalize.corrections import apply_draft_order, snake_slot
    assert [snake_slot(1, 2, 14), snake_slot(2, 1, 14), snake_slot(2, 13, 14)] == [2, 14, 2]
    # ESPN put Kelly in slot 1 and Cook's drafter in slot 2; truly it was the other way round
    picks = pd.DataFrame([
        dict(season=2021, round=1, round_pick=1, overall_pick=1, manager_key="m_kelly"),
        dict(season=2021, round=1, round_pick=2, overall_pick=2, manager_key="m_cook"),
        dict(season=2021, round=2, round_pick=1, overall_pick=3, manager_key="m_cook"),
        dict(season=2021, round=2, round_pick=2, overall_pick=4, manager_key="m_kelly"),
    ])
    out = apply_draft_order(picks, 2021, ["m_cook", "m_kelly"])
    assert list(out.manager_key) == ["m_kelly", "m_cook", "m_cook", "m_kelly"]      # managers unchanged
    assert list(out.overall_pick) == [2, 1, 4, 3] and list(out.espn_overall_pick) == [1, 2, 3, 4]


def test_pick_owner_correction_and_draft_slots():
    from engine.normalize.corrections import add_draft_slots, apply_pick_owners
    picks = pd.DataFrame([
        dict(season=2026, round=1, round_pick=1, overall_pick=1, manager_key="m_a"),
        dict(season=2026, round=1, round_pick=2, overall_pick=2, manager_key="m_b"),
        dict(season=2026, round=2, round_pick=1, overall_pick=3, manager_key="m_b"),
        dict(season=2026, round=2, round_pick=2, overall_pick=4, manager_key="m_a"),
    ])
    out = add_draft_slots(apply_pick_owners(picks, 2026, {3: "m_a", 4: "m_b"}))
    assert list(out.manager_key) == ["m_a", "m_b", "m_a", "m_b"]
    assert list(out.espn_manager_key) == ["m_a", "m_b", "m_b", "m_a"]
    assert list(out.draft_slot) == [1, 2, 1, 2]


def test_surname_ignores_suffixes_and_punctuation():
    assert legacy.surname("Aaron Jones Sr.") == legacy.surname("Aaron Jones") == "jones"
    assert legacy.surname("Gardner Minshew II") == "minshew"


def test_draft_order_correction_must_name_known_managers():
    from engine.config import validate_config
    cfg = {"league": {"name": "T", "provider": "espn", "league_id": 1, "first_season": 2020},
           "managers": [{"name": "Ann A", "id": "m_1"}],
           "corrections": {"draft_order": {2021: ["ann-a", "nobody"]}}}
    assert not validate_config(cfg).ok


def test_pool_rows_take_the_actual_season_line_and_derive_games():
    from engine.normalize.espn import pool_rows

    page = {"players": [
        {"id": 1, "status": "ONTEAM", "onTeamId": 4, "player": {
            "id": 1, "fullName": "Starter", "defaultPositionId": 2, "proTeamId": 9, "ownership": {"percentOwned": 99.5},
            "stats": [{"seasonId": 2024, "statSourceId": 1, "statSplitTypeId": 0, "scoringPeriodId": 0,
                       "appliedTotal": 225.0, "appliedAverage": 16.0},      # projection: ignored
                      {"seasonId": 2024, "statSourceId": 0, "statSplitTypeId": 0, "scoringPeriodId": 0,
                       "appliedTotal": 336.4, "appliedAverage": 19.788235294117648}]}},
        {"id": 2, "status": "FREEAGENT", "player": {"id": 2, "fullName": "Negative", "defaultPositionId": 3,
            "stats": [{"seasonId": 2024, "statSourceId": 0, "statSplitTypeId": 0, "scoringPeriodId": 0,
                       "appliedTotal": -0.3, "appliedAverage": -0.15}]}},
    ]}
    a, b = pool_rows(2024, page, start_rank=500)
    assert (a["games"], a["total_points"], a["position"], a["pool_status"], a["pool_rank"]) == (17, 336.4, "RB", "ONTEAM", 500)
    assert (b["games"], b["pool_rank"]) == (0, 501)


def test_legacy_stats_universe_is_rostered_plus_500_free_agents():
    ps = pd.DataFrame({"season": 2024, "player_id": range(600), "position": "WR",
                       "pool_status": ["ONTEAM"] * 50 + ["FREEAGENT"] * 550, "pool_rank": range(600)})
    u = legacy.legacy_stats_universe(ps)
    assert len(u) == 550 and u["player_id"].max() == 549
