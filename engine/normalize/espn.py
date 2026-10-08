"""Normalize the raw ESPN cache into canonical tables.

Input:  .cache/espn/<league_id>/<season>/*.json   (written by engine pull)
Output: pandas DataFrames, one per canonical table (see docs/DATA_DICTIONARY.md)

    seasons       one row per season: team count, regular-season length, playoffs, FAAB
    managers      one row per person, keyed by hashed member key
    teams         season x team: owner, name, final rank, seed, division
    matchups      season x week x team: opponent, points, result, bracket tier (byes kept, flagged)
    lineups       season x week x team x player: slot, started, points (raw ESPN points)
    draft_picks   season x pick
    transactions  one row per transaction item (add, drop, trade leg, draft), every type and status
    player_seasons  season x player: name and position as ESPN lists them
    players       player id -> latest name and position
    player_stats  season x player, whole NFL player pool: season fantasy points,
                  average, games, pool status and ownership (pool order kept)

Live season only (a snapshot from the last pull, for the weeks still to play):
    future_matchups  season x week x team: the scheduled opponent
    projections      season x week x player: ESPN's projection for the week, for
                     every rostered player (source "roster", with team and slot)
                     and every free agent or waiver player (source "available")
    pro_teams        season x NFL team: abbreviation and bye week
    pro_games        season x week x NFL team: that week's NFL opponent and whether
                     the team is at home (no row in its bye week)

Raw ESPN values are kept as-is (for example negative D/ST scores). Any league
rule that adjusts values belongs in analytics, never here, so the canonical
tables always match what ESPN recorded.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from engine.identity import member_key

# ESPN lineup slot ids -> slot label. Labels for the standard football slots
# match the site's existing data ("RB/WR/TE" is the flex).
SLOTS = {
    0: "QB", 1: "TQB", 2: "RB", 3: "RB/WR", 4: "WR", 5: "WR/TE", 6: "TE", 7: "OP",
    8: "DT", 9: "DE", 10: "LB", 11: "DL", 12: "CB", 13: "S", 14: "DB", 15: "DP",
    16: "D/ST", 17: "K", 18: "P", 19: "HC", 20: "BE", 21: "IR", 23: "RB/WR/TE", 24: "ER",
}
NON_STARTING_SLOTS = {"BE", "IR"}

# ESPN defaultPositionId -> position.
POSITIONS = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 7: "P", 9: "DT", 10: "DE",
             11: "LB", 12: "CB", 13: "S", 14: "HC", 16: "D/ST"}

PROJECTION_COLUMNS = ["season", "week", "source", "team_id", "player_id", "player_name", "position",
                      "pro_team_id", "slot", "pool_status", "percent_owned", "projected_points"]
FUTURE_MATCHUP_COLUMNS = ["season", "week", "matchup_period", "game_id", "team_id", "opponent_team_id"]
PRO_TEAM_COLUMNS = ["season", "pro_team_id", "abbrev", "bye_week"]
PRO_GAME_COLUMNS = ["season", "week", "pro_team_id", "opponent_pro_team_id", "home"]

PLAYER_STATS_COLUMNS = ["season", "player_id", "player_name", "position", "pro_team_id", "pool_status",
                        "on_team_id", "percent_owned", "pool_rank", "total_points", "avg_points", "games"]

REGULAR = "REGULAR"
WINNERS_BRACKET = "WINNERS_BRACKET"


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _key(raw_member_id: str | None) -> str | None:
    """Hash a raw ESPN member id; values already hashed (m_...) pass through."""
    if not raw_member_id:
        return None
    return raw_member_id if raw_member_id.startswith("m_") else member_key(raw_member_id)


def slot_label(slot_id: int) -> str:
    return SLOTS.get(slot_id, f"SLOT_{slot_id}")


def position_label(position_id: int | None) -> str:
    return POSITIONS.get(position_id, f"POS_{position_id}")


def entry_points(entry: dict, season: int, week: int) -> float:
    """Actual fantasy points for one roster entry in one week.

    ESPN attaches several stat lines to each player (actuals and projections,
    week and season). The week's actual line has statSourceId 0 and the week's
    scoringPeriodId. Falls back to the entry's appliedStatTotal.
    """
    ppe = entry.get("playerPoolEntry") or {}
    for stat in (ppe.get("player") or {}).get("stats") or []:
        if (stat.get("statSourceId") == 0 and stat.get("scoringPeriodId") == week
                and stat.get("seasonId", season) == season):
            return round(float(stat.get("appliedTotal") or 0.0), 2)
    return round(float(ppe.get("appliedStatTotal") or 0.0), 2)


def projected_points(player: dict, season: int, week: int) -> float | None:
    """ESPN's projection for one week: the stat line with statSourceId 1 and
    that scoringPeriodId. None when ESPN has no projection (for example a
    player on bye)."""
    for stat in player.get("stats") or []:
        if (stat.get("statSourceId") == 1 and stat.get("scoringPeriodId") == week
                and stat.get("seasonId", season) == season):
            return round(float(stat.get("appliedTotal") or 0.0), 2)
    return None


def projection_rows(season: int, week: int, box: dict, available: dict | None) -> tuple[list[dict], list[dict]]:
    """A live-season projection snapshot for one week -> (future matchup rows,
    projection rows). Rosters are each team's roster at pull time; available
    players are free agents and waiver players."""
    games, rows = [], []
    for game in box.get("schedule") or []:
        home, away = game.get("home") or {}, game.get("away")
        sides = [(home, away), (away, home)] if away else [(home, None)]
        for side, opp in sides:
            games.append({"season": season, "week": week, "matchup_period": game.get("matchupPeriodId"),
                          "game_id": game.get("id"), "team_id": side.get("teamId"),
                          "opponent_team_id": opp.get("teamId") if opp else None})
            for entry in (side.get("rosterForCurrentScoringPeriod") or {}).get("entries") or []:
                player = (entry.get("playerPoolEntry") or {}).get("player") or {}
                rows.append({"season": season, "week": week, "source": "roster", "team_id": side.get("teamId"),
                             "player_id": entry.get("playerId", player.get("id")),
                             "player_name": player.get("fullName"),
                             "position": position_label(player.get("defaultPositionId")),
                             "pro_team_id": player.get("proTeamId"), "slot": slot_label(entry.get("lineupSlotId")),
                             "pool_status": "ONTEAM",
                             "percent_owned": (player.get("ownership") or {}).get("percentOwned"),
                             "projected_points": projected_points(player, season, week)})
    for entry in (available or {}).get("players") or []:
        player = entry.get("player") or {}
        rows.append({"season": season, "week": week, "source": "available", "team_id": None,
                     "player_id": player.get("id", entry.get("id")), "player_name": player.get("fullName"),
                     "position": position_label(player.get("defaultPositionId")),
                     "pro_team_id": player.get("proTeamId"), "slot": None, "pool_status": entry.get("status"),
                     "percent_owned": (player.get("ownership") or {}).get("percentOwned"),
                     "projected_points": projected_points(player, season, week)})
    return games, rows


def pro_team_rows(season: int, data: dict) -> list[dict]:
    return [{"season": season, "pro_team_id": t.get("id"), "abbrev": t.get("abbrev"), "bye_week": t.get("byeWeek")}
            for t in ((data.get("settings") or {}).get("proTeams") or [])]


def pro_game_rows(season: int, data: dict) -> list[dict]:
    """One row per NFL team and scoring period it plays in (ESPN's proGamesByScoringPeriod)."""
    rows = []
    for t in (data.get("settings") or {}).get("proTeams") or []:
        tid = t.get("id")
        for period, games in (t.get("proGamesByScoringPeriod") or {}).items():
            for g in games or []:
                home, away = g.get("homeProTeamId"), g.get("awayProTeamId")
                if tid not in (home, away):
                    continue
                rows.append({"season": season, "week": int(period), "pro_team_id": tid,
                             "opponent_pro_team_id": away if tid == home else home, "home": tid == home})
    return rows


# ---------------------------------------------------------------- per season

def season_row(season: int, league: dict) -> dict:
    settings = league.get("settings") or {}
    sched = settings.get("scheduleSettings") or {}
    acq = settings.get("acquisitionSettings") or {}
    status = league.get("status") or {}
    return {
        "season": season,
        "team_count": len(league.get("teams") or []),
        "regular_season_periods": sched.get("matchupPeriodCount"),
        "playoff_team_count": sched.get("playoffTeamCount"),
        "final_scoring_period": status.get("finalScoringPeriod"),
        "faab_enabled": bool(acq.get("isUsingAcquisitionBudget")),
        "faab_budget": acq.get("acquisitionBudget") if acq.get("isUsingAcquisitionBudget") else None,
        "is_active": bool(status.get("isActive")),
    }


def manager_rows(league: dict) -> Iterable[dict]:
    for m in league.get("members") or []:
        yield {
            "manager_key": _key(m.get("id")),
            "espn_name": f"{m.get('firstName', '')} {m.get('lastName', '')}".strip(),
        }


def team_rows(season: int, league: dict) -> Iterable[dict]:
    divisions = {d.get("id"): d.get("name") for d in
                 ((league.get("settings") or {}).get("scheduleSettings") or {}).get("divisions") or []}
    for t in league.get("teams") or []:
        owners = [o for o in (t.get("owners") or []) if o]
        primary = t.get("primaryOwner") or (owners[0] if owners else None)
        name = t.get("name") or f"{t.get('location', '')} {t.get('nickname', '')}".strip()
        yield {
            "season": season,
            "team_id": t.get("id"),
            "manager_key": _key(primary),
            "co_owner_keys": ",".join(_key(o) for o in owners if o != primary) or None,
            "team_name": name,
            "abbrev": t.get("abbrev"),
            "logo_url": t.get("logo"),
            "final_rank": t.get("rankCalculatedFinal"),
            "playoff_seed": t.get("playoffSeed"),
            "division_id": t.get("divisionId"),
            "division_name": divisions.get(t.get("divisionId")),
        }


def game_rows(season: int, week: int, box: dict, regular_periods: int | None) -> tuple[list[dict], list[dict]]:
    """One boxscore file -> (matchup rows, lineup rows)."""
    matchups: list[dict] = []
    lineups: list[dict] = []
    for game in box.get("schedule") or []:
        period = game.get("matchupPeriodId")
        tier_raw = game.get("playoffTierType") or "NONE"
        tier = REGULAR if tier_raw == "NONE" else tier_raw
        is_playoff_week = bool(regular_periods) and period is not None and period > regular_periods
        home, away = game.get("home") or {}, game.get("away")
        winner = game.get("winner")
        sides = [("home", home, away), ("away", away, home)] if away else [("home", home, None)]
        for side_name, side, opp in sides:
            if side_name == "home":
                result = {"HOME": "W", "AWAY": "L", "TIE": "T"}.get(winner)
            else:
                result = {"AWAY": "W", "HOME": "L", "TIE": "T"}.get(winner)
            matchups.append({
                "season": season,
                "week": week,
                "matchup_period": period,
                "game_id": game.get("id"),
                "team_id": side.get("teamId"),
                "opponent_team_id": opp.get("teamId") if opp else None,
                "points": round(float(side.get("totalPoints") or 0.0), 2),
                "opponent_points": round(float(opp.get("totalPoints") or 0.0), 2) if opp else None,
                "result": "BYE" if opp is None else result,
                "score_tied": opp is not None and round(float(side.get("totalPoints") or 0.0), 2)
                              == round(float(opp.get("totalPoints") or 0.0), 2),
                "tier": tier,
                "is_bye": opp is None,
                "is_playoff_week": is_playoff_week,
            })
            roster = side.get("rosterForCurrentScoringPeriod") or {}
            for entry in roster.get("entries") or []:
                player = (entry.get("playerPoolEntry") or {}).get("player") or {}
                slot = slot_label(entry.get("lineupSlotId"))
                lineups.append({
                    "season": season,
                    "week": week,
                    "team_id": side.get("teamId"),
                    "player_id": entry.get("playerId"),
                    "player_name": player.get("fullName"),
                    "position": position_label(player.get("defaultPositionId")),
                    "slot": slot,
                    "started": slot not in NON_STARTING_SLOTS,
                    "points": entry_points(entry, season, week),
                })
    return matchups, lineups


def transaction_rows(season: int, tx: dict, source: str = "league") -> Iterable[dict]:
    """Every item of every transaction, with the transaction's type and status.

    ESPN logs far more than completed moves (proposals, declines, vetoes, failed
    and cancelled waiver bids, lineup changes). Nothing is filtered here;
    engine.normalize.moves.executed_moves defines what counts as a real move.

    Two sources feed this table: the weekly league feed ("league") and each
    player's card ("playercard"), which also carries executed trades the weekly
    feed leaves out.
    """
    for t in tx.get("transactions") or []:
        for i, item in enumerate(t.get("items") or []):
            yield {
                "season": season,
                "scoring_period": t.get("scoringPeriodId"),
                "transaction_id": t.get("id"),
                "item_index": i,
                "type": t.get("type"),
                "status": t.get("status"),
                "item_type": item.get("type"),
                "player_id": item.get("playerId"),
                "from_team_id": item.get("fromTeamId"),
                "to_team_id": item.get("toTeamId"),
                "team_id": t.get("teamId"),
                "bid_amount": t.get("bidAmount") or 0,
                "proposed_at_ms": t.get("proposedDate"),
                "related_transaction_id": t.get("relatedTransactionId"),
                "source": source,
            }


def card_rows(season: int, cards: dict) -> tuple[list[dict], list[dict]]:
    """One player-cards file -> (player-season rows, transaction rows)."""
    people: list[dict] = []
    txs: list[dict] = []
    for entry in cards.get("players") or []:
        player = entry.get("player") or {}
        people.append({
            "season": season,
            "player_id": player.get("id", entry.get("id")),
            "player_name": player.get("fullName"),
            "position": position_label(player.get("defaultPositionId")),
        })
        txs.extend(transaction_rows(season, {"transactions": entry.get("transactions") or []}, "playercard"))
    return people, txs


def season_totals(player: dict, season: int) -> tuple[float, float]:
    """(total, average) of the player's actual fantasy points for the season:
    ESPN's stat line with statSourceId 0 (actual), split 0, scoring period 0."""
    for stat in player.get("stats") or []:
        if (stat.get("statSourceId") == 0 and stat.get("statSplitTypeId") == 0
                and stat.get("scoringPeriodId") == 0 and stat.get("seasonId", season) == season):
            return float(stat.get("appliedTotal") or 0.0), float(stat.get("appliedAverage") or 0.0)
    return 0.0, 0.0


def pool_rows(season: int, page: dict, start_rank: int) -> list[dict]:
    """One player-pool file -> player_stats rows. Games are total / average,
    rounded, and 0 when the average is not positive (as ESPN's own client does)."""
    rows = []
    for i, entry in enumerate(page.get("players") or []):
        player = entry.get("player") or {}
        total, avg = season_totals(player, season)
        rows.append({
            "season": season,
            "player_id": player.get("id", entry.get("id")),
            "player_name": player.get("fullName"),
            "position": position_label(player.get("defaultPositionId")),
            "pro_team_id": player.get("proTeamId"),
            "pool_status": entry.get("status"),
            "on_team_id": entry.get("onTeamId"),
            "percent_owned": ((player.get("ownership") or {}).get("percentOwned")),
            "pool_rank": start_rank + i,
            "total_points": round(total, 2),
            "avg_points": avg,
            "games": int(round(total / avg)) if avg > 0 else 0,
        })
    return rows


def draft_rows(season: int, draft: dict) -> Iterable[dict]:
    for p in ((draft.get("draftDetail") or {}).get("picks")) or []:
        yield {
            "season": season,
            "overall_pick": p.get("overallPickNumber"),
            "round": p.get("roundId"),
            "round_pick": p.get("roundPickNumber"),
            "team_id": p.get("teamId"),
            "player_id": p.get("playerId"),
            "keeper": bool(p.get("keeper")),
            "bid_amount": p.get("bidAmount") or 0,
        }


def read_adp_snapshots(league_dir: Path) -> dict[int, dict]:
    """{season: snapshot} for every season with an adp_snapshot.json (see
    engine.providers.espn), rows shaped for engine.normalize.adp."""
    out: dict[int, dict] = {}
    for season_dir in sorted(p for p in league_dir.iterdir() if p.is_dir() and p.name.isdigit()):
        path = season_dir / "adp_snapshot.json"
        if not path.exists():
            continue
        raw = _read(path)
        out[int(season_dir.name)] = {
            "pulled_at": raw.get("pulled_at"), "draft_date": raw.get("draft_date"),
            "rows": [{"player_id": r.get("player_id"), "player_name": r.get("player_name"),
                      "position": position_label(r.get("position_id")), "adp": r.get("adp")}
                     for r in raw.get("players") or []],
        }
    return out


# ---------------------------------------------------------------- all seasons

def collapse_multiweek(m: pd.DataFrame) -> pd.DataFrame:
    """One row per team per matchup period. ESPN lists a matchup period that spans several scoring weeks
    (a two-week playoff round) in each week's box score, every time with the period's full total, which
    made it two games with doubled scores. Kept: the row of the period's last week (when the result is
    decided), with
        period_weeks    the scoring weeks the period spans (1 for an ordinary game)
        first_week      its first week (week stays the last)
        points_total, opponent_points_total   ESPN's totals for the whole period
        points, opponent_points               the per-week average (total / period_weeks), so every
                                              score-based stat compares like with like (Ethan, 2026-10-08,
                                              option 1); the result is ESPN's, decided on the totals."""
    if "period_weeks" in m:                       # already collapsed (safe to call twice)
        return m
    if not len(m):
        return m.assign(period_weeks=pd.Series(dtype=int), first_week=pd.Series(dtype=int),
                        points_total=pd.Series(dtype=float), opponent_points_total=pd.Series(dtype=float))
    period = m["matchup_period"].fillna(m["week"])
    g = m.assign(_period=period).groupby(["season", "_period", "team_id"])["week"]
    m = m.assign(period_weeks=g.transform("nunique").astype(int), first_week=g.transform("min").astype(int),
                 _last=g.transform("max"), _period=period)
    m = m[m["week"] == m["_last"]].drop_duplicates(["season", "_period", "team_id"], keep="last")
    m = m.assign(points_total=m["points"], opponent_points_total=m["opponent_points"])
    multi = m["period_weeks"] > 1
    m.loc[multi, "points"] = (m.loc[multi, "points_total"] / m.loc[multi, "period_weeks"]).round(2)
    m.loc[multi, "opponent_points"] = (m.loc[multi, "opponent_points_total"].astype(float)
                                       / m.loc[multi, "period_weeks"]).round(2)
    # ESPN's row order is kept: a game's first row is its home team (records.games reads it so)
    return m.drop(columns=["_last", "_period"]).reset_index(drop=True)


def normalize_league(league_dir: Path) -> dict[str, pd.DataFrame]:
    """Build every canonical table from a league's cache directory."""
    seasons, managers, teams, matchups, lineups, picks, txs, people, pool = [], [], [], [], [], [], [], [], []
    future, projections, pro_teams, pro_games = [], [], [], []
    for season_dir in sorted(p for p in league_dir.iterdir() if p.is_dir() and p.name.isdigit()):
        season = int(season_dir.name)
        league = _read(season_dir / "league.json")
        srow = season_row(season, league)
        seasons.append(srow)
        managers.extend(manager_rows(league))
        teams.extend(team_rows(season, league))
        for box_path in sorted(season_dir.glob("week_*_boxscore.json")):
            week = int(box_path.name.split("_")[1])
            m, l = game_rows(season, week, _read(box_path), srow["regular_season_periods"])
            matchups.extend(m)
            lineups.extend(l)
        for tx_path in sorted(season_dir.glob("week_*_transactions.json")):
            txs.extend(transaction_rows(season, _read(tx_path)))
        for card_path in sorted(season_dir.glob("playercards_*.json")):
            p_rows, t_rows = card_rows(season, _read(card_path))
            people.extend(p_rows)
            txs.extend(t_rows)
        rank = 0
        for pool_path in sorted(season_dir.glob("players_*.json")):
            rows = pool_rows(season, _read(pool_path), rank)
            pool.extend(rows)
            rank += len(rows)
        if (season_dir / "draft.json").exists():
            picks.extend(draft_rows(season, _read(season_dir / "draft.json")))
        for box_path in sorted(season_dir.glob("proj_week_*_boxscore.json")):
            week = int(box_path.name.split("_")[2])
            avail_path = season_dir / f"proj_week_{week:02d}_available.json"
            g, r = projection_rows(season, week, _read(box_path), _read(avail_path) if avail_path.exists() else None)
            future.extend(g)
            projections.extend(r)
        if (season_dir / "pro_teams.json").exists():
            pro_data = _read(season_dir / "pro_teams.json")
            pro_teams.extend(pro_team_rows(season, pro_data))
            pro_games.extend(pro_game_rows(season, pro_data))

    t = pd.DataFrame(teams)
    owner = t.set_index(["season", "team_id"])["manager_key"]

    def with_owner(df: pd.DataFrame, team_col: str = "team_id", out_col: str = "manager_key") -> pd.DataFrame:
        idx = pd.MultiIndex.from_arrays([df["season"], df[team_col]])
        df[out_col] = owner.reindex(idx).to_numpy()
        return df

    m = collapse_multiweek(pd.DataFrame(matchups))
    m["opponent_team_id"] = m["opponent_team_id"].astype("Int64")
    m = with_owner(m)
    m = with_owner(m, "opponent_team_id", "opponent_manager_key")
    lu = with_owner(pd.DataFrame(lineups))
    dp = with_owner(pd.DataFrame(picks))
    tx = pd.DataFrame(txs)
    if len(tx):
        # The same item can arrive from several weekly responses and several
        # player cards. Keep one copy, preferring the league feed (it has status).
        tx["_pref"] = (tx["source"] != "league").astype(int)
        tx = (tx.sort_values(["_pref"], kind="stable")
                .drop_duplicates(["transaction_id", "player_id", "item_type", "from_team_id", "to_team_id"])
                .drop(columns="_pref").sort_values(["season", "scoring_period", "proposed_at_ms"], kind="stable")
                .reset_index(drop=True))
        tx = with_owner(tx)

    ps = pd.DataFrame(people, columns=["season", "player_id", "player_name", "position"])
    ps = ps.dropna(subset=["player_id"]).drop_duplicates(["season", "player_id"], keep="last")

    # Names: player cards cover everyone (including players drafted and cut before
    # ever appearing in a lineup); lineups fill in anything the cards missed.
    from_lineups = lu[["season", "player_id", "player_name", "position"]].drop_duplicates(["season", "player_id"], keep="last")
    ps = (pd.concat([ps, from_lineups[~from_lineups.set_index(["season", "player_id"]).index.isin(
                        ps.set_index(["season", "player_id"]).index)]])
            .sort_values(["season", "player_id"]).reset_index(drop=True))
    ps["player_id"] = ps["player_id"].astype(int)
    players = (ps.groupby("player_id", as_index=False)
                 .agg(player_name=("player_name", "last"), position=("position", "last")))

    fm = pd.DataFrame(future, columns=FUTURE_MATCHUP_COLUMNS)
    fm["opponent_team_id"] = fm["opponent_team_id"].astype("Int64")
    fm = with_owner(with_owner(fm), "opponent_team_id", "opponent_manager_key")
    pr = pd.DataFrame(projections, columns=PROJECTION_COLUMNS)
    pr["team_id"] = pr["team_id"].astype("Int64")
    pr = with_owner(pr)

    return {
        "future_matchups": fm,
        "projections": pr,
        "pro_teams": pd.DataFrame(pro_teams, columns=PRO_TEAM_COLUMNS),
        "pro_games": pd.DataFrame(pro_games, columns=PRO_GAME_COLUMNS).drop_duplicates(
            ["season", "week", "pro_team_id"]).reset_index(drop=True),
        "seasons": pd.DataFrame(seasons),
        "managers": pd.DataFrame(managers).drop_duplicates("manager_key", keep="last").reset_index(drop=True),
        "teams": t,
        "matchups": m,
        "lineups": lu,
        "draft_picks": dp,
        "transactions": tx,
        "player_seasons": ps,
        "players": players,
        "player_stats": pd.DataFrame(pool, columns=PLAYER_STATS_COLUMNS).drop_duplicates(
            ["season", "player_id"], keep="first").reset_index(drop=True),
    }
