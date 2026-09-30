"""ESPN fantasy football provider.

Talks to ESPN's league API directly and caches each response verbatim, one
JSON file per request, under .cache/espn/<league_id>/<season>/:

    league.json                  settings, teams, members, status
    draft.json                   draft picks
    week_NN_boxscore.json        matchups with each team's lineup and points
    week_NN_transactions.json    adds, drops, waivers, trades
    playercards_NNN.json         name, position, and full transaction history for
                                 every player seen that season (100 per file)
    players_NNN.json             the whole player pool (rostered, free agents,
                                 waivers) with season stats and ownership, most
                                 owned first, 500 per file
    manifest.json                what was pulled, when, and summary counts

Live season only, a snapshot taken at pull time for every regular-season week
from the current one on:
    proj_week_NN_boxscore.json   that week's matchups with each team's current
                                 roster and ESPN's projection for the week
    proj_week_NN_available.json  free agents and waiver players with their
                                 projection for the week, most owned first
    pro_teams.json               NFL teams with their bye weeks

A season is complete once its final scoring period is finished (ESPN keeps
status.isActive true for old seasons, so that flag is not used). Completed
seasons are pulled once and reused; the live season is always refreshed. Credentials come from the caller (environment or auth file) and are
never written to the cache.

The ESPN API is unofficial and undocumented. Everything ESPN-shaped stays in
this module and engine.normalize.espn; nothing else depends on it.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SEASON_URL = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{season}"
BASE_URL = SEASON_URL + "/segments/0/leagues/{league_id}"
RETRY_STATUSES = {429, 500, 502, 503, 504}
MANIFEST_VERSION = 4   # 2: player cards; 3: player pool; 4: completeness by final period, live projections


class EspnError(RuntimeError):
    pass


class EspnClient:
    """Thin HTTP client: one method, retries, clear errors."""

    def __init__(self, league_id: int, espn_s2: str, swid: str, session=None, pause: float = 0.3):
        if session is None:
            import requests  # imported lazily so tests and CI do not need it

            session = requests.Session()
        self.league_id = league_id
        self.session = session
        self.cookies = {"espn_s2": espn_s2, "SWID": swid}
        self.pause = pause
        self.calls = 0

    def get(self, season: int, views: list[str], scoring_period: int | None = None,
            fantasy_filter: dict | None = None, league_level: bool = True) -> dict[str, Any]:
        """league_level=False asks the season endpoint (NFL data shared by
        every league, such as pro team schedules)."""
        url = (BASE_URL if league_level else SEASON_URL).format(season=season, league_id=self.league_id)
        params = [("view", v) for v in views]
        if scoring_period is not None:
            params.append(("scoringPeriodId", scoring_period))
        headers = {"x-fantasy-filter": json.dumps(fantasy_filter)} if fantasy_filter else {}

        for attempt in range(4):
            resp = self.session.get(url, params=params, headers=headers, cookies=self.cookies, timeout=30)
            self.calls += 1
            if resp.status_code in RETRY_STATUSES:
                time.sleep(2 ** attempt)
                continue
            if resp.status_code in (401, 403):
                raise EspnError(
                    f"ESPN refused the request for {season} ({resp.status_code}). "
                    "The ESPN_S2 / SWID cookies are probably expired: copy fresh ones from your browser."
                )
            if resp.status_code != 200:
                raise EspnError(f"ESPN returned {resp.status_code} for {season} views={views}")
            try:
                data = resp.json()
            except ValueError as exc:
                raise EspnError(f"ESPN returned non-JSON for {season} views={views} (often expired cookies)") from exc
            if self.pause:
                time.sleep(self.pause)
            return data
        raise EspnError(f"ESPN kept failing for {season} views={views} after retries")


def matchup_period_map(league: dict) -> dict[int, int]:
    """Map scoring period (NFL week) -> matchup period from league settings.

    Usually identical, but leagues can set multi-week playoff matchups.
    """
    raw = (league.get("settings") or {}).get("scheduleSettings", {}).get("matchupPeriods") or {}
    mapping: dict[int, int] = {}
    for matchup_period, scoring_periods in raw.items():
        for sp in scoring_periods:
            mapping[int(sp)] = int(matchup_period)
    return mapping


def weeks_to_pull(league: dict) -> int:
    status = league.get("status") or {}
    final = status.get("finalScoringPeriod") or 17
    latest = status.get("latestScoringPeriod") or final
    return min(final, latest)


def regular_season_weeks(league: dict) -> list[int]:
    """Scoring periods that belong to regular-season matchup periods."""
    count = ((league.get("settings") or {}).get("scheduleSettings") or {}).get("matchupPeriodCount")
    if not count:
        return []
    periods = matchup_period_map(league)
    return sorted(w for w, mp in periods.items() if mp <= count) or list(range(1, count + 1))


def season_complete(league: dict, final_box: dict | None) -> bool:
    """True once the final scoring period is finished: ESPN has moved past it,
    or it is the latest period and every game in it has a winner."""
    status = league.get("status") or {}
    final = status.get("finalScoringPeriod")
    latest = status.get("latestScoringPeriod")
    if not final or not latest:
        return False
    if latest > final:
        return True
    if latest < final or not final_box:
        return False
    games = final_box.get("schedule") or []
    return bool(games) and all(g.get("winner") in ("HOME", "AWAY", "TIE") for g in games)


def available_filter(limit: int) -> dict:
    """Free agents and waiver players, most owned first."""
    return {"players": {
        "filterStatus": {"value": ["FREEAGENT", "WAIVERS"]},
        "limit": limit, "offset": 0,
        "sortPercOwned": {"sortPriority": 1, "sortAsc": False},
        "sortDraftRanks": {"sortPriority": 100, "sortAsc": True, "value": "STANDARD"},
    }}


def _write(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


CARD_CHUNK = 100
AVAILABLE_LIMIT = 300    # per week; plenty to find the best available player at every position
POOL_PAGE = 500
POOL_MAX_PAGES = 20
POOL_STATUSES = ["ONTEAM", "FREEAGENT", "WAIVERS"]


def pool_filter(offset: int) -> dict:
    """Every player, most owned first, then by ESPN's standard draft rank (the
    order ESPN's own free-agent list uses)."""
    return {"players": {
        "filterStatus": {"value": POOL_STATUSES},
        "limit": POOL_PAGE, "offset": offset,
        "sortPercOwned": {"sortPriority": 1, "sortAsc": False},
        "sortDraftRanks": {"sortPriority": 100, "sortAsc": True, "value": "STANDARD"},
    }}


def season_player_ids(season_dir: Path) -> list[int]:
    """Every player id that appears in a season's lineups, transactions, or draft."""
    ids: set[int] = set()
    for box_path in season_dir.glob("week_*_boxscore.json"):
        for game in _read(box_path).get("schedule") or []:
            for side in ("home", "away"):
                roster = (game.get(side) or {}).get("rosterForCurrentScoringPeriod") or {}
                ids.update(e.get("playerId") for e in roster.get("entries") or [])
    for tx_path in season_dir.glob("week_*_transactions.json"):
        for t in _read(tx_path).get("transactions") or []:
            ids.update(i.get("playerId") for i in t.get("items") or [])
    draft_path = season_dir / "draft.json"
    if draft_path.exists():
        ids.update(p.get("playerId") for p in ((_read(draft_path).get("draftDetail") or {}).get("picks")) or [])
    return sorted(i for i in ids if i is not None)


def summarize(season_dir: Path) -> dict:
    """Counts from the cached files; used to sanity-check a pull."""
    league = _read(season_dir / "league.json")
    matchups: set = set()
    lineup_entries = 0
    transactions = 0
    weeks = 0
    for box_path in sorted(season_dir.glob("week_*_boxscore.json")):
        weeks += 1
        for game in _read(box_path).get("schedule") or []:
            matchups.add(game.get("id"))
            for side in ("home", "away"):
                roster = (game.get(side) or {}).get("rosterForCurrentScoringPeriod") or {}
                lineup_entries += len(roster.get("entries") or [])
    for tx_path in season_dir.glob("week_*_transactions.json"):
        transactions += len(_read(tx_path).get("transactions") or [])
    draft_path = season_dir / "draft.json"
    picks = len(((_read(draft_path).get("draftDetail") or {}).get("picks")) or []) if draft_path.exists() else 0
    pool = sum(len(_read(p).get("players") or []) for p in season_dir.glob("players_*.json"))
    cards = card_tx = 0
    for card_path in season_dir.glob("playercards_*.json"):
        for entry in _read(card_path).get("players") or []:
            cards += 1
            card_tx += len(entry.get("transactions") or [])
    return {
        "teams": len(league.get("teams") or []),
        "members": len(league.get("members") or []),
        "weeks": weeks,
        "matchups": len(matchups),
        "lineup_entries": lineup_entries,
        "transactions": transactions,
        "draft_picks": picks,
        "player_cards": cards,
        "card_transactions": card_tx,
        "pool_players": pool,
        "projection_weeks": len(list(season_dir.glob("proj_week_*_boxscore.json"))),
    }


class EspnProvider:
    name = "espn"

    def __init__(self, client: EspnClient):
        self.client = client

    def is_cached(self, out_dir: Path) -> bool:
        manifest = out_dir / "manifest.json"
        if not manifest.exists():
            return False
        m = _read(manifest)
        return m.get("version") == MANIFEST_VERSION and m.get("complete") is True

    def pull_season(self, season: int, out_dir: Path) -> dict:
        out_dir.mkdir(parents=True, exist_ok=True)
        c = self.client

        league = c.get(season, ["mSettings", "mTeam", "mStatus"])
        _write(out_dir / "league.json", league)

        periods = matchup_period_map(league)
        last_week = weeks_to_pull(league)
        for week in range(1, last_week + 1):
            mp = periods.get(week, week)
            box = c.get(season, ["mMatchupScore", "mScoreboard"], scoring_period=week,
                        fantasy_filter={"schedule": {"filterMatchupPeriodIds": {"value": [mp]}}})
            _write(out_dir / f"week_{week:02d}_boxscore.json", box)
            tx = c.get(season, ["mTransactions2"], scoring_period=week)
            _write(out_dir / f"week_{week:02d}_transactions.json", tx)

        _write(out_dir / "draft.json", c.get(season, ["mDraftDetail"]))

        # Player cards: names, positions, and each player's full transaction
        # history, which includes executed trades the weekly feed leaves out.
        ids = season_player_ids(out_dir)
        for n, start in enumerate(range(0, len(ids), CARD_CHUNK)):
            chunk = ids[start:start + CARD_CHUNK]
            cards = c.get(season, ["kona_playercard"], fantasy_filter={"players": {
                "filterIds": {"value": chunk}, "limit": len(chunk),
                "sortDraftRanks": {"sortPriority": 100, "sortAsc": True, "value": "STANDARD"}}})
            _write(out_dir / f"playercards_{n:03d}.json", cards)

        # Player pool: season stats for every NFL player, rostered or not.
        # Draft value needs players who never touched this league (position
        # baselines, hit-rate cutoffs).
        seen: set = set()
        for n in range(POOL_MAX_PAGES):
            page = c.get(season, ["kona_player_info"], scoring_period=last_week,
                         fantasy_filter=pool_filter(n * POOL_PAGE))
            players = page.get("players") or []
            ids = {p.get("id") for p in players}
            if not players or ids <= seen:
                break
            seen |= ids
            _write(out_dir / f"players_{n:03d}.json", page)
            if len(players) < POOL_PAGE:
                break

        final_path = out_dir / f"week_{last_week:02d}_boxscore.json"
        complete = season_complete(league, _read(final_path) if final_path.exists() else None)
        for old in list(out_dir.glob("proj_week_*.json")) + list(out_dir.glob("pro_teams.json")):
            old.unlink()
        proj_weeks = [] if complete else self.pull_projections(season, league, out_dir)

        summary = summarize(out_dir)
        _write(out_dir / "manifest.json", {
            "version": MANIFEST_VERSION,
            "provider": self.name,
            "league_id": c.league_id,
            "season": season,
            "pulled_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "complete": complete,
            "projection_weeks": proj_weeks,
            "summary": summary,
        })
        return summary

    def pull_projections(self, season: int, league: dict, out_dir: Path) -> list[int]:
        """Live season: every regular-season week from the current one on, as
        it stands now (rosters, projections, who is available), plus NFL byes."""
        c = self.client
        latest = (league.get("status") or {}).get("latestScoringPeriod") or 1
        weeks = [w for w in regular_season_weeks(league) if w >= latest]
        if not weeks:
            return []
        periods = matchup_period_map(league)
        for week in weeks:
            mp = periods.get(week, week)
            box = c.get(season, ["mMatchupScore", "mScoreboard"], scoring_period=week,
                        fantasy_filter={"schedule": {"filterMatchupPeriodIds": {"value": [mp]}}})
            _write(out_dir / f"proj_week_{week:02d}_boxscore.json", box)
            avail = c.get(season, ["kona_player_info"], scoring_period=week,
                          fantasy_filter=available_filter(AVAILABLE_LIMIT))
            _write(out_dir / f"proj_week_{week:02d}_available.json", avail)
        _write(out_dir / "pro_teams.json", c.get(season, ["proTeamSchedules_wl"], league_level=False))
        return weeks
