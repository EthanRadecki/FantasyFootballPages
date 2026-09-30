import json
from datetime import date

import pytest

from engine.providers.espn import EspnProvider, matchup_period_map, weeks_to_pull
from engine.pull import parse_seasons, run_pull


class FakeClient:
    """Stands in for EspnClient: canned responses, records every request."""

    league_id = 123

    def __init__(self, active=False, weeks=3, pool=3, is_active_flag=None):
        self.requests = []
        self.pool = pool
        self.active = active
        self.weeks = weeks
        self.calls = 0
        # ESPN reports isActive true even for old seasons; completeness must not depend on it
        self.is_active_flag = True if is_active_flag is None else is_active_flag

    def get(self, season, views, scoring_period=None, fantasy_filter=None, league_level=True):
        self.calls += 1
        self.requests.append((season, tuple(views), scoring_period, json.dumps(fantasy_filter)))
        if "proTeamSchedules_wl" in views:
            assert not league_level
            return {"settings": {"proTeams": [{"id": 1, "abbrev": "ATL", "byeWeek": 2}]}}
        if "mSettings" in views:
            periods = {str(w): [w] for w in range(1, self.weeks + 1)}
            return {
                "settings": {"scheduleSettings": {"matchupPeriods": periods, "matchupPeriodCount": self.weeks}},
                # live: week 2 is under way; finished: ESPN has moved past the final week
                "status": {"finalScoringPeriod": self.weeks,
                           "latestScoringPeriod": 2 if self.active else self.weeks + 1,
                           "isActive": self.is_active_flag},
                "teams": [{"id": 1}, {"id": 2}],
                "members": [{"id": "a"}, {"id": "b"}],
            }
        if "mMatchupScore" in views:
            entries = {"entries": [{}, {}]}
            return {"schedule": [{"id": scoring_period,
                                  "home": {"rosterForCurrentScoringPeriod": entries},
                                  "away": {"rosterForCurrentScoringPeriod": entries}}]}
        if "mTransactions2" in views:
            return {"transactions": [{"id": f"t{scoring_period}"}]}
        if "mDraftDetail" in views:
            return {"draftDetail": {"picks": [{"playerId": 7}, {"playerId": 8}, {"playerId": 9}]}}
        if "kona_player_info" in views:
            offset = fantasy_filter["players"]["offset"]
            limit = fantasy_filter["players"]["limit"]
            ids = list(range(100, 100 + self.pool))[offset:offset + limit]
            return {"players": [{"id": i, "status": "FREEAGENT", "player": {"id": i}} for i in ids]}
        if "kona_playercard" in views:
            ids = fantasy_filter["players"]["filterIds"]["value"]
            return {"players": [{"player": {"id": i, "fullName": f"P{i}"}, "transactions": []} for i in ids]}
        raise AssertionError(views)


def test_matchup_period_map_handles_multiweek_periods():
    league = {"settings": {"scheduleSettings": {"matchupPeriods": {"1": [1], "15": [15, 16]}}}}
    assert matchup_period_map(league) == {1: 1, 15: 15, 16: 15}


def test_weeks_to_pull_caps_at_final_period():
    assert weeks_to_pull({"status": {"finalScoringPeriod": 17, "latestScoringPeriod": 18}}) == 17
    assert weeks_to_pull({"status": {"finalScoringPeriod": 17, "latestScoringPeriod": 4}}) == 4


def test_parse_seasons():
    today = date(2026, 9, 28)
    assert parse_seasons(None, 2020, today) == [2020, 2021, 2022, 2023, 2024, 2025, 2026]
    assert parse_seasons("2024,2026", 2020, today) == [2024, 2026]
    assert parse_seasons("2020-2022", 2020, today) == [2020, 2021, 2022]
    assert parse_seasons(None, 2020, date(2026, 5, 1))[-1] == 2025
    with pytest.raises(SystemExit):
        parse_seasons("2019", 2020, today)


def test_pull_season_writes_cache_and_summary(tmp_path):
    provider = EspnProvider(FakeClient(weeks=3))
    (season, status, summary), = run_pull(provider, 123, [2024], tmp_path)
    assert status == "pulled"
    assert summary == {"teams": 2, "members": 2, "weeks": 3, "matchups": 3, "lineup_entries": 12,
                       "transactions": 3, "draft_picks": 3, "player_cards": 3, "card_transactions": 0,
                       "pool_players": 3, "projection_weeks": 0}
    season_dir = tmp_path / "espn" / "123" / "2024"
    assert (season_dir / "week_03_boxscore.json").exists()
    manifest = json.loads((season_dir / "manifest.json").read_text())
    assert manifest["complete"] is True and "espn_s2" not in json.dumps(manifest)


def test_completed_season_is_reused_but_active_season_is_refetched(tmp_path):
    done = FakeClient(active=False)
    list(run_pull(EspnProvider(done), 123, [2024], tmp_path))
    again = FakeClient(active=False)
    (_, status, _), = run_pull(EspnProvider(again), 123, [2024], tmp_path)
    assert status == "cached" and again.calls == 0

    live = FakeClient(active=True)
    list(run_pull(EspnProvider(live), 123, [2026], tmp_path))
    live2 = FakeClient(active=True)
    (_, status, _), = run_pull(EspnProvider(live2), 123, [2026], tmp_path)
    assert status == "pulled" and live2.calls > 0


def test_boxscore_requests_filter_by_matchup_period(tmp_path):
    client = FakeClient(weeks=2)
    list(run_pull(EspnProvider(client), 123, [2024], tmp_path))
    box = [r for r in client.requests if "mMatchupScore" in r[1]]
    assert [r[2] for r in box] == [1, 2]
    assert '"value": [2]' in box[1][3]


def test_player_pool_is_paged_until_a_short_page(tmp_path):
    from engine.providers import espn

    client = FakeClient(weeks=1, pool=espn.POOL_PAGE + 20)
    list(run_pull(EspnProvider(client), 123, [2024], tmp_path))
    pool = [json.loads(r[3])["players"]["offset"] for r in client.requests if "kona_player_info" in r[1]]
    assert pool == [0, espn.POOL_PAGE]
    season_dir = tmp_path / "espn" / "123" / "2024"
    assert sorted(p.name for p in season_dir.glob("players_*.json")) == ["players_000.json", "players_001.json"]


def test_old_season_is_complete_even_when_espn_says_active(tmp_path):
    list(run_pull(EspnProvider(FakeClient(active=False, is_active_flag=True)), 123, [2020], tmp_path))
    again = FakeClient(active=False)
    (_, status, _), = run_pull(EspnProvider(again), 123, [2020], tmp_path)
    assert status == "cached" and again.calls == 0


def test_season_complete_needs_the_final_week_decided():
    from engine.providers.espn import season_complete

    league = {"status": {"finalScoringPeriod": 17, "latestScoringPeriod": 17}}
    assert not season_complete(league, {"schedule": [{"winner": "HOME"}, {"winner": "UNDECIDED"}]})
    assert season_complete(league, {"schedule": [{"winner": "HOME"}, {"winner": "TIE"}]})
    assert season_complete({"status": {"finalScoringPeriod": 17, "latestScoringPeriod": 18}}, None)
    assert not season_complete({"status": {"finalScoringPeriod": 17, "latestScoringPeriod": 4}}, None)


def test_live_season_snapshots_every_remaining_regular_week(tmp_path):
    client = FakeClient(active=True, weeks=4)
    list(run_pull(EspnProvider(client), 123, [2026], tmp_path))
    season_dir = tmp_path / "espn" / "123" / "2026"
    assert sorted(p.name for p in season_dir.glob("proj_week_*")) == [
        "proj_week_02_available.json", "proj_week_02_boxscore.json", "proj_week_03_available.json",
        "proj_week_03_boxscore.json", "proj_week_04_available.json", "proj_week_04_boxscore.json"]
    assert (season_dir / "pro_teams.json").exists()
    avail = [json.loads(r[3]) for r in client.requests if "kona_player_info" in r[1] and r[2] in (3,)]
    assert avail[0]["players"]["filterStatus"]["value"] == ["FREEAGENT", "WAIVERS"]
    manifest = json.loads((season_dir / "manifest.json").read_text())
    assert manifest["complete"] is False and manifest["projection_weeks"] == [2, 3, 4]


def test_finished_season_takes_no_projection_snapshot(tmp_path):
    list(run_pull(EspnProvider(FakeClient(weeks=2)), 123, [2024], tmp_path))
    season_dir = tmp_path / "espn" / "123" / "2024"
    assert not list(season_dir.glob("proj_week_*")) and not (season_dir / "pro_teams.json").exists()
