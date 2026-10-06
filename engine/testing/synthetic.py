"""A deterministic synthetic ESPN league, for end-to-end tests of the engine on a league that is not Preach.

    python tools/synthetic_league.py --cache .cache-synthetic      # writes the raw ESPN cache
    python -m engine.cli normalize leagues/synthetic/league.yaml --cache .cache-synthetic
    ... analyze, build --verify

The league writes the same files `engine pull` caches for ESPN (league.json, week
box scores, transactions, player cards, the player pool, the draft, ADP
snapshots, and the live season's projection snapshot with the NFL schedule), so
everything from normalize on runs exactly as for a real league. Nothing is
random at run time: one seed, fixed rules, the same bytes every run.

What it varies on purpose (the things Preach never exercises):
    seasons      2021-2024; 2024 is live (weeks 1-5 final, week 6 in progress)
    size         10 teams in 2021-2022, 12 from 2023 (two new managers, one leaves)
    divisions    two divisions in 2021 and 2023, none in 2022 and 2024
    lineups      no D/ST slot ever; a kicker until 2022; a superflex (OP) slot from 2023
    playoffs     4 teams (2 rounds) at 10 teams; 6 teams with first-round byes (3 rounds) at 12
    season       13 regular-season weeks in 2021, 14 after
    events       waivers every week, two trades a season, one forfeit (a lineup of zeros),
                 one tie game, IR stints, player names with suffixes and accents
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from engine.identity import member_key

LEAGUE_ID = 101
SEED = 20261006
SEASONS = [2021, 2022, 2023, 2024]
LIVE_SEASON = 2024
LIVE_FINAL_WEEKS = 5            # weeks 1-5 final in the live season, week 6 in progress
POS_ID = {"QB": 1, "RB": 2, "WR": 3, "TE": 4, "K": 5}
SLOT_ID = {"QB": 0, "RB": 2, "WR": 4, "TE": 6, "OP": 7, "K": 17, "RB/WR/TE": 23, "BE": 20, "IR": 21}
POOL = {"QB": 40, "RB": 80, "WR": 100, "TE": 40, "K": 32}
MEAN = {"QB": 17.0, "RB": 10.0, "WR": 10.0, "TE": 7.0, "K": 8.0}
SPREAD = {"QB": 4.0, "RB": 5.0, "WR": 5.0, "TE": 3.5, "K": 1.5}
PRO_TEAMS = [("ARI", 22), ("ATL", 1), ("BAL", 33), ("BUF", 2), ("CAR", 29), ("CHI", 3), ("CIN", 4), ("CLE", 5),
             ("DAL", 6), ("DEN", 7), ("DET", 8), ("GB", 9), ("HOU", 34), ("IND", 11), ("JAX", 30), ("KC", 12),
             ("LV", 13), ("LAC", 24), ("LAR", 14), ("MIA", 15), ("MIN", 16), ("NE", 17), ("NO", 18), ("NYG", 19),
             ("NYJ", 20), ("PHI", 21), ("PIT", 23), ("SF", 25), ("SEA", 26), ("TB", 27), ("TEN", 10), ("WSH", 28)]
FIRST = ["Avery", "Blake", "Cameron", "Dakota", "Emerson", "Finley", "Gray", "Harper", "Indigo", "Jordan",
         "Kendall", "Logan", "Morgan", "Noel", "Oakley", "Parker", "Quinn", "Reese", "Sawyer", "Taylor"]
LAST = ["Abbott", "Brennan", "Castillo", "Dorsey", "Ellison", "Fairbanks", "Galloway", "Hollis", "Iverson",
        "Jaramillo", "Kincaid", "Lockhart", "Merriweather", "Northcutt", "Okafor", "Pemberton", "Quintero",
        "Rutledge", "Stanton", "Thibodeaux", "Underwood", "Vasquez", "Whitfield", "Yancey", "Zamora"]
MANAGERS = [("Alex Rivera", "Night Owls"), ("Bailey Chen", "Bailey's Comets"), ("Casey Novak", "Novak Djokovibes"),
            ("Devon Price", "Price Is Right"), ("Elliot Shaw", "Shaw Shank"), ("Frankie Ortiz", "Ortiz Express"),
            ("Gale Park", "Park It Here"), ("Harley Quinto", "Quinto Brothers"), ("Izzy Mbeki", "Mbeki Machine"),
            ("Jules Fontaine", "Fontaine of Youth"), ("Kai Lindqvist", "Lindqvist Legion"),
            ("Lane Okoro", "Okoro Outlaws"), ("Micah Stroud", "Stroud Storm")]
# manager index per season, in team-id order (team id = position + 1)
ROSTERS = {2021: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9], 2022: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
           2023: [0, 1, 2, 3, 4, 5, 6, 7, 8, 10, 11, 12], 2024: [0, 1, 2, 3, 4, 5, 6, 7, 8, 10, 11, 12]}


def raw_member(i: int) -> str:
    return "{%08X-5E5E-4000-8000-%012X}" % (0x5EED0000 + i, i + 1)


def manager_key(i: int) -> str:
    return member_key(raw_member(i))


def slots(season: int) -> list[str]:
    base = ["QB", "RB", "RB", "WR", "WR", "TE", "RB/WR/TE"]
    return base + (["K"] if season <= 2022 else ["OP"])


def regular_weeks(season: int) -> int:
    return 13 if season == 2021 else 14


def playoff_teams(n_teams: int) -> int:
    return 4 if n_teams <= 10 else 6


def playoff_rounds(n_teams: int) -> int:
    return 2 if playoff_teams(n_teams) == 4 else 3


def divisions(season: int, n: int) -> list[dict]:
    if season not in (2021, 2023):
        return []
    return [{"id": 0, "name": "North", "size": n // 2}, {"id": 1, "name": "South", "size": n - n // 2}]


# ---------------------------------------------------------------- players

@dataclass
class Player:
    pid: int
    name: str
    pos: str
    team: int                 # pro team id
    skill: float              # mean weekly points
    out_weeks: set = field(default_factory=set)


def make_players(rng: np.random.Generator) -> list[Player]:
    players, used = [], set()
    pid = 4000000
    for pos, n in POOL.items():
        for k in range(n):
            while True:
                name = f"{FIRST[rng.integers(len(FIRST))]} {LAST[rng.integers(len(LAST))]}"
                if name not in used:
                    break
            used.add(name)
            if k % 17 == 3:
                name += " Jr."
            elif k % 29 == 5:
                name += " III"
            skill = max(MEAN[pos] + SPREAD[pos] * (1.6 - 3.2 * k / n) + rng.normal(0, 1.0), 1.0)
            players.append(Player(pid, name, pos, PRO_TEAMS[int(rng.integers(32))][1], round(float(skill), 2)))
            pid += 1
    players[7].name = "Renée Duchamp"          # an accent, as ESPN writes some names
    return players


def byes(rng: np.random.Generator, season: int) -> dict[int, int]:
    weeks = list(range(5, 15))
    return {tid: weeks[i % len(weeks)] for i, (_, tid) in enumerate(PRO_TEAMS)}


def pro_schedule(season: int, bye: dict[int, int], weeks: int) -> dict[int, list[tuple[int, int]]]:
    """week -> [(home, away)] for the NFL teams, a fixed rotation with each team's bye."""
    ids = [t for _, t in PRO_TEAMS]
    out = {}
    for w in range(1, weeks + 1):
        playing = [t for t in ids if bye[t] != w]
        rot = playing[w % len(playing):] + playing[:w % len(playing)]
        half = len(rot) // 2
        out[w] = [(rot[i], rot[-1 - i]) if (w + i) % 2 else (rot[-1 - i], rot[i]) for i in range(half)]
    return out


def weekly_points(rng: np.random.Generator, p: Player, week: int, bye: dict[int, int]) -> float:
    if bye.get(p.team) == week or week in p.out_weeks:
        return 0.0
    if p.pos == "K":
        return float(round(max(rng.normal(p.skill, 3.0), 0) * 1.0))
    return round(float(max(rng.normal(p.skill, p.skill * 0.45 + 1.5), -2.0)), 1)


# ---------------------------------------------------------------- one season

def snake_order(n: int, rounds: int) -> list[int]:
    out = []
    for r in range(rounds):
        order = list(range(n)) if r % 2 == 0 else list(range(n - 1, -1, -1))
        out += order
    return out


def schedule(n: int, weeks: int, season: int) -> dict[int, list[tuple[int, int]]]:
    """week -> [(home team index, away team index)]: a round robin, repeated."""
    idx = list(range(n))
    out = {}
    for w in range(1, weeks + 1):
        r = (w - 1 + season) % (n - 1)
        rot = [idx[0]] + idx[1:][r:] + idx[1:][:r]
        out[w] = [(rot[i], rot[n - 1 - i]) if w % 2 else (rot[n - 1 - i], rot[i]) for i in range(n // 2)]
    return out


def _stats_lines(season: int, week: int, pts: float | None, proj: float | None, total: float | None = None,
                 games: int | None = None) -> list[dict]:
    lines = []
    if proj is not None:
        lines.append({"statSourceId": 1, "statSplitTypeId": 1, "scoringPeriodId": week, "seasonId": season,
                      "appliedTotal": proj})
    if pts is not None:
        lines.append({"statSourceId": 0, "statSplitTypeId": 1, "scoringPeriodId": week, "seasonId": season,
                      "appliedTotal": pts})
    if total is not None:
        avg = total / games if games else 0.0
        lines.append({"statSourceId": 0, "statSplitTypeId": 0, "scoringPeriodId": 0, "seasonId": season,
                      "appliedTotal": round(total, 2), "appliedAverage": avg})
    return lines


def _entry(p: Player, slot: str, season: int, week: int, pts: float | None, proj: float | None) -> dict:
    return {"playerId": p.pid, "lineupSlotId": SLOT_ID[slot], "playerPoolEntry": {
        "appliedStatTotal": pts or 0.0,
        "player": {"id": p.pid, "fullName": p.name, "defaultPositionId": POS_ID[p.pos], "proTeamId": p.team,
                   "ownership": {"percentOwned": 90.0}, "stats": _stats_lines(season, week, pts, proj)}}}


def set_lineup(roster: list[Player], season: int, week: int, bye: dict[int, int]) -> dict[int, str]:
    """player id -> slot: the best available player by skill in each slot (fixed slots first), the
    rest on the bench; injured players on IR."""
    out = {}
    healthy = []
    for p in roster:
        if week in p.out_weeks:
            out[p.pid] = "IR"
        else:
            healthy.append(p)
    ranked = sorted(healthy, key=lambda p: (-(0 if bye.get(p.team) == week else p.skill), p.pid))
    for slot in sorted(slots(season), key=lambda s: (s in ("RB/WR/TE", "OP"), s == "OP")):
        ok = {"RB/WR/TE": {"RB", "WR", "TE"}, "OP": {"QB", "RB", "WR", "TE"}}.get(slot, {slot})
        for p in ranked:
            if p.pid not in out and p.pos in ok:
                out[p.pid] = slot
                break
    for p in healthy:
        out.setdefault(p.pid, "BE")
    return out


def write_season(base: Path, season: int, players: list[Player], rng: np.random.Generator) -> None:
    d = base / str(season)
    d.mkdir(parents=True, exist_ok=True)
    mgrs = ROSTERS[season]
    n = len(mgrs)
    reg = regular_weeks(season)
    rounds = playoff_rounds(n)
    final = reg + rounds
    live = season == LIVE_SEASON
    bye = byes(rng, season)
    pro = pro_schedule(season, bye, final)
    for p in players:
        p.out_weeks = set()
    for p in rng.choice(players, size=12, replace=False):
        start = int(rng.integers(2, reg))
        p.out_weeks = set(range(start, start + int(rng.integers(1, 4))))

    # draft: snake, 15 rounds, each team takes the best player left by skill with noise
    rounds_draft = 15
    order = snake_order(n, rounds_draft)
    avail = sorted(players, key=lambda p: -p.skill - (6.0 if p.pos == "QB" else 0) + (4.0 if p.pos == "K" else 0))
    rosters: list[list[Player]] = [[] for _ in range(n)]
    picks = []
    noise = {p.pid: float(rng.normal(0, 2.0)) for p in players}
    for i, t in enumerate(order):
        need_k = season <= 2022 and i >= n * (rounds_draft - 1) and not any(q.pos == "K" for q in rosters[t])
        cands = [p for p in avail if (p.pos == "K") == need_k or not need_k]
        cands = [p for p in cands if p.pos != "K" or season <= 2022]
        cands = [p for p in cands if not (p.pos == "QB" and sum(q.pos == "QB" for q in rosters[t]) >= 3)]
        best = max(cands[:25], key=lambda p: p.skill + noise[p.pid] + (2.0 if p.pos == "QB" and season >= 2023 else 0))
        avail.remove(best)
        rosters[t].append(best)
        picks.append({"overallPickNumber": i + 1, "roundId": i // n + 1, "roundPickNumber": i % n + 1,
                      "teamId": t + 1, "playerId": best.pid, "keeper": False, "bidAmount": 0})
    _write(d / "draft.json", {"draftDetail": {"drafted": True, "picks": picks,
                                              "completeDate": _ms(datetime(season, 9, 1, tzinfo=timezone.utc))}})
    # ESPN ADP saved the day after the draft
    adp_rows = [{"player_id": p.pid, "player_name": p.name, "position_id": POS_ID[p.pos],
                 "adp": round(i + 1 + float(rng.normal(0, 3.0)), 1)}
                for i, p in enumerate(sorted(players, key=lambda p: -(p.skill + noise[p.pid])))]
    _write(d / "adp_snapshot.json", {"pulled_at": f"{season}-09-02T12:00:00+00:00",
                                     "draft_date": f"{season}-09-01T00:00:00+00:00",
                                     "draft_date_source": "draftDetail.completeDate", "players": adp_rows})

    sched = schedule(n, reg, season)
    totals = {p.pid: 0.0 for p in players}
    games = {p.pid: 0 for p in players}
    owner = {p.pid: t for t, r in enumerate(rosters) for p in r}
    tx_id = 0
    cards: dict[int, list] = {p.pid: [] for p in players}
    standings = {t: [0.0, 0.0] for t in range(n)}     # wins, points
    played_weeks = LIVE_FINAL_WEEKS + 1 if live else final
    seeds: list[int] = []
    alive: list[int] = []
    finish: list[int] = []
    week_pts: dict = {}
    for week in range(1, played_weeks + 1):
        in_progress = live and week == played_weeks
        for p in players:
            pts = weekly_points(rng, p, week, bye)
            week_pts[(week, p.pid)] = 0.0 if in_progress else pts
            if not in_progress:
                totals[p.pid] += pts
                games[p.pid] += int(bye.get(p.team) != week and week not in p.out_weeks)
        if week <= reg:
            pairs = [(h, a, "NONE") for h, a in sched[week]]
            byes_teams = []
        else:
            if week == reg + 1:
                seeds = sorted(range(n), key=lambda t: (-standings[t][0], -standings[t][1], t))
                alive = seeds[:playoff_teams(n)]
            pairs, byes_teams = [], []
            field_ = list(alive)
            if len(field_) == 6:
                byes_teams = field_[:2]
                field_ = field_[2:]
                pairs = [(field_[0], field_[3], "WINNERS_BRACKET"), (field_[1], field_[2], "WINNERS_BRACKET")]
            else:
                pairs = [(field_[i], field_[-1 - i], "WINNERS_BRACKET") for i in range(len(field_) // 2)]
            out_ = [t for t in seeds if t not in alive]
            pairs += [(out_[i], out_[-1 - i], "LOSERS_CONSOLATION_LADDER") for i in range(len(out_) // 2)]
            if len(out_) % 2:
                byes_teams.append(out_[len(out_) // 2])
        schedule_json = []
        winners = []
        for gid, (h, a, tier) in enumerate(pairs, start=1):
            sides = {}
            for t in (h, a):
                lineup = set_lineup(rosters[t], season, week, bye)
                forfeit = season == 2022 and week == 5 and t == 3
                entries, total = [], 0.0
                for p in rosters[t]:
                    pts = 0.0 if forfeit else week_pts[(week, p.pid)]
                    entries.append(_entry(p, lineup[p.pid], season, week, pts, round(p.skill, 1)))
                    if lineup[p.pid] not in ("BE", "IR"):
                        total += pts
                sides[t] = {"teamId": t + 1, "totalPoints": round(total, 2),
                            "rosterForCurrentScoringPeriod": {"entries": entries}}
            if season == 2023 and week == 7 and gid == 1:          # one tie game
                sides[a]["totalPoints"] = sides[h]["totalPoints"]
            hp, ap = sides[h]["totalPoints"], sides[a]["totalPoints"]
            winner = "UNDECIDED" if in_progress else ("HOME" if hp > ap else "AWAY" if ap > hp else "TIE")
            schedule_json.append({"id": week * 100 + gid, "matchupPeriodId": week, "playoffTierType": tier,
                                  "winner": winner, "home": sides[h], "away": sides[a]})
            if not in_progress and week <= reg:
                for t, me, opp in ((h, hp, ap), (a, ap, hp)):
                    standings[t][0] += 1.0 if me > opp else 0.5 if me == opp else 0.0
                    standings[t][1] += me
            if tier == "WINNERS_BRACKET":
                winners.append(h if hp >= ap else a)
        for gid, t in enumerate(byes_teams, start=len(pairs) + 1):
            lineup = set_lineup(rosters[t], season, week, bye)
            entries = [_entry(p, lineup[p.pid], season, week, week_pts[(week, p.pid)], round(p.skill, 1))
                       for p in rosters[t]]
            total = sum(week_pts[(week, p.pid)] for p in rosters[t] if lineup[p.pid] not in ("BE", "IR"))
            schedule_json.append({"id": week * 100 + gid, "matchupPeriodId": week,
                                  "playoffTierType": "WINNERS_BRACKET" if t in alive else "LOSERS_CONSOLATION_LADDER",
                                  "winner": "UNDECIDED",
                                  "home": {"teamId": t + 1, "totalPoints": round(total, 2),
                                           "rosterForCurrentScoringPeriod": {"entries": entries}}})
        if week > reg:
            if week == final and not in_progress:
                final_game = next(g for g in schedule_json if g["playoffTierType"] == "WINNERS_BRACKET"
                                  and g.get("away"))
                h_, a_ = final_game["home"]["teamId"] - 1, final_game["away"]["teamId"] - 1
                champ = winners[0]
                finish = [champ, a_ if champ == h_ else h_]
            alive = [t for t in alive if t in winners or t in byes_teams[:2]]
        _write(d / f"week_{week:02d}_boxscore.json", {"schedule": schedule_json})

        # waivers: two pickups a week; two trades a season (weeks 4 and 9)
        txs = []
        if not in_progress and week < final:
            free = [p for p in players if p.pid not in owner]
            for k in range(2):
                t = int(rng.integers(n))
                add = max(free, key=lambda p: totals[p.pid] + float(rng.normal(0, 4)))
                drop = min((p for p in rosters[t] if p.pos == add.pos), key=lambda p: p.skill, default=None)
                if drop is None:
                    continue
                free.remove(add)
                tx_id += 1
                rec = {"id": f"tx-{season}-{tx_id}", "type": "WAIVER" if k == 0 else "FREEAGENT",
                       "status": "EXECUTED", "teamId": t + 1, "bidAmount": int(rng.integers(0, 40)) if k == 0 else 0,
                       "scoringPeriodId": week + 1, "proposedDate": _ms(datetime(season, 9, 10, tzinfo=timezone.utc)
                                                                        + timedelta(days=7 * week, minutes=k)),
                       "items": [{"type": "ADD", "playerId": add.pid, "fromTeamId": 0, "toTeamId": t + 1},
                                 {"type": "DROP", "playerId": drop.pid, "fromTeamId": t + 1, "toTeamId": 0}]}
                txs.append(rec)
                rosters[t].remove(drop)
                rosters[t].append(add)
                owner.pop(drop.pid, None)
                owner[add.pid] = t
                cards[add.pid].append(rec)
                cards[drop.pid].append(rec)
            if week in (4, 9) and week < reg:
                a, b = (week % n, (week + 3) % n)
                pa = max((p for p in rosters[a] if p.pos in ("RB", "WR")), key=lambda p: p.skill)
                pb = max((p for p in rosters[b] if p.pos == pa.pos), key=lambda p: p.skill)
                tx_id += 1
                rec = {"id": f"tr-{season}-{tx_id}", "type": "TRADE_ACCEPT", "status": "EXECUTED", "teamId": a + 1,
                       "scoringPeriodId": week + 1, "bidAmount": 0,
                       "proposedDate": _ms(datetime(season, 9, 12, tzinfo=timezone.utc) + timedelta(days=7 * week)),
                       "items": [{"type": "TRADE", "playerId": pa.pid, "fromTeamId": a + 1, "toTeamId": b + 1},
                                 {"type": "TRADE", "playerId": pb.pid, "fromTeamId": b + 1, "toTeamId": a + 1}]}
                txs.append(rec)
                rosters[a].remove(pa)
                rosters[b].remove(pb)
                rosters[a].append(pb)
                rosters[b].append(pa)
                owner[pa.pid], owner[pb.pid] = b, a
                cards[pa.pid].append(rec)
                cards[pb.pid].append(rec)
        _write(d / f"week_{week:02d}_transactions.json", {"transactions": txs})

    # player cards (every player seen: drafted, rostered or moved), 100 per file
    seen = sorted({p.pid for p in players if cards[p.pid] or any(p.pid == x["playerId"] for x in picks)}
                  | {p.pid for r in rosters for p in r})
    by_id = {p.pid: p for p in players}
    for i in range(0, len(seen), 100):
        _write(d / f"playercards_{i // 100:03d}.json", {"players": [
            {"player": {"id": pid, "fullName": by_id[pid].name, "defaultPositionId": POS_ID[by_id[pid].pos]},
             "transactions": cards[pid]} for pid in seen[i:i + 100]]})
    # the player pool with season totals, most owned first
    pool = sorted(players, key=lambda p: (-totals[p.pid], p.pid))
    _write(d / "players_000.json", {"players": [
        {"id": p.pid, "status": "ONTEAM" if p.pid in owner else "FREEAGENT",
         "onTeamId": owner[p.pid] + 1 if p.pid in owner else 0,
         "player": {"id": p.pid, "fullName": p.name, "defaultPositionId": POS_ID[p.pos], "proTeamId": p.team,
                    "ownership": {"percentOwned": round(max(99.0 - k * 0.4, 0.01), 2)},
                    "stats": _stats_lines(season, 0, None, None, totals[p.pid], games[p.pid])}}
        for k, p in enumerate(pool)]})

    teams = []
    for t, mi in enumerate(mgrs):
        name, team_name = MANAGERS[mi]
        teams.append({"id": t + 1, "name": team_name if season != 2023 else f"{team_name} {season}",
                      "abbrev": name.split()[1][:4].upper(), "owners": [raw_member(mi)], "primaryOwner": raw_member(mi),
                      "divisionId": (t % 2) if divisions(season, n) else 0,
                      "rankCalculatedFinal": 0 if live else ([*finish, *[x for x in seeds if x not in finish]]
                                                             .index(t) + 1),
                      "playoffSeed": (seeds.index(t) + 1) if seeds else 0})
    league = {"settings": {"scheduleSettings": {"matchupPeriodCount": reg, "playoffTeamCount": playoff_teams(n),
                                                "divisions": divisions(season, n) or [{"id": 0, "name": "League",
                                                                                         "size": n}]},
                           "acquisitionSettings": {"isUsingAcquisitionBudget": True, "acquisitionBudget": 100}},
              "status": {"finalScoringPeriod": final, "isActive": live,
                         "currentMatchupPeriod": played_weeks if live else final},
              "members": [{"id": raw_member(mi), "firstName": MANAGERS[mi][0].split()[0],
                           "lastName": MANAGERS[mi][0].split()[1]} for mi in mgrs],
              "teams": teams}
    _write(d / "league.json", league)

    if live:
        _write_live(d, season, players, rosters, sched, reg, played_weeks, bye, pro, owner)


def _write_live(d: Path, season: int, players, rosters, sched, reg: int, current: int, bye, pro, owner) -> None:
    """The live season's projection snapshot: each remaining regular-season week with the current
    rosters and projections, the free agents, and the NFL teams with their byes and games."""
    for week in range(current, reg + 1):
        games = []
        for gid, (h, a) in enumerate(sched[week], start=1):
            sides = []
            for t in (h, a):
                lineup = set_lineup(rosters[t], season, week, bye)
                sides.append({"teamId": t + 1, "totalPoints": 0.0, "rosterForCurrentScoringPeriod": {"entries": [
                    _entry(p, lineup[p.pid], season, week, None,
                           None if bye.get(p.team) == week else round(p.skill, 1)) for p in rosters[t]]}})
            games.append({"id": week * 100 + gid, "matchupPeriodId": week, "playoffTierType": "NONE",
                          "winner": "UNDECIDED", "home": sides[0], "away": sides[1]})
        _write(d / f"proj_week_{week:02d}_boxscore.json", {"schedule": games})
        _write(d / f"proj_week_{week:02d}_available.json", {"players": [
            {"id": p.pid, "status": "FREEAGENT", "player": {
                "id": p.pid, "fullName": p.name, "defaultPositionId": POS_ID[p.pos], "proTeamId": p.team,
                "ownership": {"percentOwned": 1.0},
                "stats": _stats_lines(season, week, None, None if bye.get(p.team) == week else round(p.skill, 1))}}
            for p in sorted(players, key=lambda p: -p.skill) if p.pid not in owner][:150]})
    _write(d / "pro_teams.json", {"settings": {"proTeams": [
        {"id": tid, "abbrev": ab, "byeWeek": bye[tid], "proGamesByScoringPeriod": {
            str(w): [{"id": w * 1000 + i, "homeProTeamId": h, "awayProTeamId": a}
                     for i, (h, a) in enumerate(g) if tid in (h, a)] for w, g in pro.items()}}
        for ab, tid in PRO_TEAMS]}})


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _write(path: Path, data) -> None:
    path.write_text(json.dumps(data, sort_keys=True, separators=(",", ":")), encoding="utf-8", newline="\n")


def write_league(cache: Path) -> Path:
    """Write the raw ESPN cache for the synthetic league under `cache`; returns the league folder."""
    base = Path(cache) / "espn" / str(LEAGUE_ID)
    rng = np.random.default_rng(SEED)
    players = make_players(rng)
    for season in SEASONS:
        write_season(base, season, players, np.random.default_rng(SEED + season))
    return base


def league_yaml() -> str:
    """leagues/synthetic/league.yaml: the config a commissioner would write for this league."""
    used = sorted({mi for s in SEASONS for mi in ROSTERS[s]})
    palette = ["#2f6f8f", "#8f4f2f", "#4f8f2f", "#6f2f8f", "#8f2f4f", "#2f8f6f", "#8f7f2f", "#2f3f8f",
               "#5f5f5f", "#8f2f2f", "#2f8f2f", "#2f2f8f", "#7f5f3f"]
    lines = ["# Synthetic test league (F1): generated by tools/synthetic_league.py, not a real league.",
             "# Regenerate with: python tools/synthetic_league.py --yaml leagues/synthetic/league.yaml",
             "", "league:", "  name: Synthetic League", "  provider: espn", f"  league_id: {LEAGUE_ID}",
             f"  first_season: {SEASONS[0]}", "", "rules:", "  regular_season_weeks:", "    default: 14",
             "    2021: 13", "", "managers:"]
    for mi in used:
        name = MANAGERS[mi][0]
        lines += [f"  - name: {name}", f"    id: {manager_key(mi)}",
                  f"    colors: {{ dark: \"{palette[mi]}\", light: \"{palette[mi]}\" }}"]
    leaver = MANAGERS[9][0].lower().replace(" ", "-")
    lines += ["", "analysis:", "  record_games: [regular_season, winners_bracket]",
              f"  exclude_managers: [{leaver}]   # left after 2022: counted everywhere, hidden from view",
              "  playoff_odds:", "    cutoff: 4", "", "features:", "  weekly_rankings: false",
              "  champions_gallery: true", ""]
    return "\n".join(lines)
