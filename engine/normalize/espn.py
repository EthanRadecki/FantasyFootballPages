"""Normalize the raw ESPN cache into canonical tables.

Input:  .cache/espn/<league_id>/<season>/*.json   (written by engine pull)
Output: pandas DataFrames, one per canonical table (see docs/DATA_DICTIONARY.md)

    seasons       one row per season: team count, regular-season length, playoffs, FAAB
    managers      one row per person, keyed by hashed member key
    teams         season x team: owner, name, final rank, seed
    matchups      season x week x team: opponent, points, result, bracket tier (byes kept, flagged)
    lineups       season x week x team x player: slot, started, points (raw ESPN points)
    draft_picks   season x pick
    transactions  one row per transaction item (add, drop, trade leg, draft), every type and status
    player_seasons  season x player: name and position as ESPN lists them
    players       player id -> latest name and position

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


# ---------------------------------------------------------------- all seasons

def normalize_league(league_dir: Path) -> dict[str, pd.DataFrame]:
    """Build every canonical table from a league's cache directory."""
    seasons, managers, teams, matchups, lineups, picks, txs, people = [], [], [], [], [], [], [], []
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
        if (season_dir / "draft.json").exists():
            picks.extend(draft_rows(season, _read(season_dir / "draft.json")))

    t = pd.DataFrame(teams)
    owner = t.set_index(["season", "team_id"])["manager_key"]

    def with_owner(df: pd.DataFrame, team_col: str = "team_id", out_col: str = "manager_key") -> pd.DataFrame:
        idx = pd.MultiIndex.from_arrays([df["season"], df[team_col]])
        df[out_col] = owner.reindex(idx).to_numpy()
        return df

    m = pd.DataFrame(matchups)
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

    return {
        "seasons": pd.DataFrame(seasons),
        "managers": pd.DataFrame(managers).drop_duplicates("manager_key", keep="last").reset_index(drop=True),
        "teams": t,
        "matchups": m,
        "lineups": lu,
        "draft_picks": dp,
        "transactions": tx,
        "player_seasons": ps,
        "players": players,
    }
