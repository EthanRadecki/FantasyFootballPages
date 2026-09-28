import json as _json; _AUTH = {k.lower(): v for k, v in _json.load(open("espn_auth.json")).items()}  # credentials stay out of code
"""
=============================================================================
Preach Fantasy — ESPN API In-Season Data Pull
Pulls two things not previously captured:
  1. Weekly rosters/lineups (starter vs. bench, every player, every week)
  2. Transaction history (drafts, adds, drops, waivers, trades)

Requires draft_history.csv in the same folder (already used by
pull_espn_stats.py) to map fantasy_team -> manager per season.
=============================================================================
Outputs:
  weekly_rosters.csv   — Season, Week, Manager, Fantasy_Team, Player, Player_ID,
                         Position, Slot, Started, Points
  transactions.csv     — Season, Scoring_Period, Type, Manager, Fantasy_Team,
                         Player, Player_ID, Move, From_Team, To_Team,
                         Bid_Amount, Transaction_ID, Proposed_Date
=============================================================================
"""

from espn_api.football import League
import pandas as pd
import requests
import json
import time

LEAGUE_ID = 9954376
ESPN_S2   = _AUTH["espn_s2"]
SWID      = _AUTH["swid"]

SEASONS = [2020, 2021, 2022, 2023, 2024, 2025]

# Max weeks to try per season (regular season + up to 4 playoff rounds).
# 2020/2021 had 13-week regular seasons; 2022+ had 14. We try a few extra
# and just skip any week that comes back empty.
MAX_WEEK_TRY = 18

COOKIES = {"espn_s2": ESPN_S2, "swid": SWID}

# ── Load manager mapping from draft_history.csv (season, fantasy_team) -> manager ──
draft_hist = pd.read_csv("draft_history.csv")
TEAM_TO_MANAGER = {}
for _, r in draft_hist[["season", "manager", "fantasy_team"]].drop_duplicates().iterrows():
    TEAM_TO_MANAGER[(int(r["season"]), r["fantasy_team"])] = r["manager"]

# ── Manual overrides for team names that don't cleanly match draft_history.csv ──
# (mid-history renames, typos, or ESPN recording a slightly different string
# than what got captured at draft time). Confirmed by Ethan.
MANUAL_TEAM_OVERRIDES = {
    'Carmine Pittelli': 'Carmine Pittelli Jr.',
    'Ryan McQuaid': 'Ryan P McQuaid',
    '      Chi Town Murder Suicide?': 'Deniz Bileydi',
    '      Chicago We got um': 'Deniz Bileydi',
    'AnaKen skyWalker ': 'Quin Gegwich',
    'Fresh Prince  Of Helaire': 'Carmine Pittelli Jr.',
    'Goodwill  Hunting V2': 'Baylen Slansky',
    'Mike White ': 'Ryan P McQuaid',
    'Mixon a  Half Chûbb': 'Quin Gegwich',
    'Set  Pitts Free': 'Deniz Bileydi',
    'The  South Will Rise': 'Thomas Sullivan',
    'The Less  Fourtunette': 'Ben Castaldo',
    'Zay  Sutherland': 'Anthony Kelly',
}

def manager_for(season, team_name):
    if team_name in MANUAL_TEAM_OVERRIDES:
        return MANUAL_TEAM_OVERRIDES[team_name]
    return TEAM_TO_MANAGER.get((season, team_name), team_name)  # fallback to team name if unmapped

all_roster_rows = []
all_txn_rows = []
seen_txn_ids = set()

for season in SEASONS:
    print(f"\n{'='*60}\nSeason {season}\n{'='*60}")

    try:
        league = League(league_id=LEAGUE_ID, year=season, espn_s2=ESPN_S2, swid=SWID)
    except Exception as e:
        print(f"  Could not load league: {e}")
        continue

    team_id_to_name = {t.team_id: t.team_name for t in league.teams}

    # ── WEEKLY ROSTERS / LINEUPS ──
    print("Pulling weekly rosters/lineups...")
    weeks_found = 0
    prev_week_totals = None  # {fantasy_team: total_points} from the last real week we kept

    for week in range(1, MAX_WEEK_TRY + 1):
        try:
            box_scores = league.box_scores(week)
        except Exception:
            continue
        if not box_scores:
            continue

        # Collect this week's rows into a staging list first, so we can check
        # for the "phantom week" bug before committing them: ESPN's box_scores()
        # sometimes echoes the last real week's data instead of returning empty
        # once you request a week past the season's actual end.
        staged_rows = []
        this_week_totals = {}
        for bs in box_scores:
            for side_team, lineup in [(bs.home_team, bs.home_lineup), (bs.away_team, bs.away_lineup)]:
                if side_team is None or not lineup:
                    continue
                fantasy_team = side_team.team_name
                manager = manager_for(season, fantasy_team)
                team_total = 0.0
                for p in lineup:
                    started = p.slot_position not in ("BE", "IR")
                    staged_rows.append({
                        "Season": season,
                        "Week": week,
                        "Manager": manager,
                        "Fantasy_Team": fantasy_team,
                        "Player": p.name,
                        "Player_ID": p.playerId,
                        "Position": p.position,
                        "Slot": p.slot_position,
                        "Started": started,
                        "Points": p.points,
                    })
                    team_total += p.points or 0.0
                this_week_totals[fantasy_team] = round(team_total, 2)

        if not staged_rows:
            continue

        # Phantom-week check: if every team's total this week exactly matches
        # the previous kept week, ESPN is just re-serving stale data. Skip it.
        is_duplicate = (
            prev_week_totals is not None
            and this_week_totals == prev_week_totals
        )
        if is_duplicate:
            print(f"  Week {week}: SKIPPED (identical totals to prior week — phantom/stale data)")
            continue

        all_roster_rows.extend(staged_rows)
        prev_week_totals = this_week_totals
        weeks_found += 1
    print(f"  Weeks with data: {weeks_found}")

    # ── TRANSACTIONS (via kona_playercard, since recent_activity() is broken) ──
    print("Pulling transactions via kona_playercard...")

    # Get every unique player ID that touched this league this season.
    all_pids = set()
    for t in league.teams:
        for p in t.roster:
            all_pids.add(p.playerId)
    try:
        for p in league.free_agents(size=2000):
            all_pids.add(p.playerId)
    except Exception as e:
        print(f"  Free agents unavailable: {e}")

    all_pids = list(all_pids)
    print(f"  Total unique player IDs to check: {len(all_pids)}")

    url = f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{season}/segments/0/leagues/{LEAGUE_ID}"
    CHUNK = 100
    season_txns_found = 0

    for i in range(0, len(all_pids), CHUNK):
        chunk_ids = all_pids[i:i + CHUNK]
        filters = {
            "players": {
                "filterIds": {"value": chunk_ids},
                "limit": len(chunk_ids),
                "sortDraftRanks": {"sortPriority": 100, "sortAsc": True, "value": "STANDARD"}
            }
        }
        headers = {"x-fantasy-filter": json.dumps(filters)}
        params = {"view": "kona_playercard"}

        try:
            resp = requests.get(url, headers=headers, params=params, cookies=COOKIES, timeout=30)
            resp.raise_for_status()
        except Exception as e:
            print(f"  Chunk {i}-{i+CHUNK} failed: {e}")
            continue

        data = resp.json()
        players = data.get("players", [])

        for entry in players:
            txns = entry.get("transactions") or []
            player_name = entry.get("player", {}).get("fullName", "?")

            for txn in txns:
                txn_id = txn.get("id")
                if txn_id in seen_txn_ids:
                    continue
                seen_txn_ids.add(txn_id)

                txn_type = txn.get("type")
                scoring_period = txn.get("scoringPeriodId")
                bid = txn.get("bidAmount", 0)
                proposed = txn.get("proposedDate")
                initiating_team_id = txn.get("teamId")
                initiating_team_name = team_id_to_name.get(initiating_team_id, str(initiating_team_id))
                initiating_manager = manager_for(season, initiating_team_name)

                for item in txn.get("items", []):
                    move_type = item.get("type")  # DRAFT, ADD, DROP, TRADE
                    pid = item.get("playerId")
                    from_team_id = item.get("fromTeamId")
                    to_team_id = item.get("toTeamId")
                    from_team_name = team_id_to_name.get(from_team_id, str(from_team_id)) if from_team_id else "FA/None"
                    to_team_name = team_id_to_name.get(to_team_id, str(to_team_id)) if to_team_id else "FA/None"

                    all_txn_rows.append({
                        "Season": season,
                        "Scoring_Period": scoring_period,
                        "Type": txn_type,
                        "Move": move_type,
                        "Initiating_Manager": initiating_manager,
                        "Initiating_Team": initiating_team_name,
                        "Player": player_name,
                        "Player_ID": pid,
                        "From_Team": from_team_name,
                        "To_Team": to_team_name,
                        "Bid_Amount": bid,
                        "Transaction_ID": txn_id,
                        "Proposed_Date_Unix_ms": proposed,
                    })
                    season_txns_found += 1

        time.sleep(0.3)  # be polite to ESPN's servers

    print(f"  Transaction line-items found: {season_txns_found}")

# ── Save outputs ──
df_rosters = pd.DataFrame(all_roster_rows)
df_txns = pd.DataFrame(all_txn_rows)

df_rosters.to_csv("weekly_rosters.csv", index=False)
df_txns.to_csv("transactions.csv", index=False)

print(f"\n{'='*60}")
print("DONE")
print(f"{'='*60}")
print(f"weekly_rosters.csv — {len(df_rosters)} rows")
print(f"transactions.csv   — {len(df_txns)} rows")
print(f"\nTransaction type breakdown:")
if len(df_txns) > 0:
    print(df_txns["Move"].value_counts().to_string())
