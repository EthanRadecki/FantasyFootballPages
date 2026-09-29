import json
from datetime import date

import pytest

from engine.providers.espn import EspnProvider, matchup_period_map, weeks_to_pull
from engine.pull import parse_seasons, run_pull


class FakeClient:
    """Stands in for EspnClient: canned responses, records every request."""

    league_id = 123

    def __init__(self, active=False, weeks=3):
        self.requests = []
        self.active = active
        self.weeks = weeks
        self.calls = 0

    def get(self, season, views, scoring_period=None, fantasy_filter=None):
        self.calls += 1
        self.requests.append((season, tuple(views), scoring_period, json.dumps(fantasy_filter)))
        if "mSettings" in views:
            return {
                "settings": {"scheduleSettings": {"matchupPeriods": {"1": [1], "2": [2], "3": [3]}}},
                "status": {"finalScoringPeriod": self.weeks, "latestScoringPeriod": self.weeks + 1,
                           "isActive": self.active},
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
                       "transactions": 3, "draft_picks": 3, "player_cards": 3, "card_transactions": 0}
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
