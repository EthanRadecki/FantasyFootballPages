"""
=============================================================================
Preach Fantasy — ESPN API Player Stats Pull (2026 only)

Adapted from pull_espn_stats.py, scoped to season 2026 only. Uses the same
roster + free-agents enumeration as the original -- together these cover
every player currently on a team OR currently unrostered, which is the
complete player universe regardless of mid-season adds/drops. This avoids
the gap in the weekly-rosters approach (which only sees whoever was
rostered at game time each week and misses anyone since dropped).

Reads each player's own season-to-date stat object (key 0 in player.stats),
not a box-score reconstruction, so it reflects current season totals
directly from ESPN.

Merges into the existing espn_player_stats_season.csv / _weekly.csv in
place: any prior season=2026 rows are dropped first, then this run's rows
are appended, so re-running weekly as the season progresses just refreshes
2026 without touching 2020-2025 or creating duplicates.

Also captures, per player: nfl_team (proTeam) and current_manager (the
manager who currently rosters them, None if they're a true free agent).
current_manager is what lets the site tell "never drafted, still
unowned" apart from "never drafted, but someone picked them up off
waivers since" -- both look the same in draft_history_all_positions.csv,
but only the first one should actually be labeled "Free Agent" anywhere
on the site. Existing 2020-2025 rows won't have these two columns
populated (left as NaN after the merge) since ownership wasn't tracked
retroactively -- only new 2026 rows carry them.
=============================================================================
Outputs (merged into the existing files, 2020-2025 rows untouched):
  espn_player_stats_season.csv  — season-to-date totals per player
  espn_player_stats_weekly.csv  — week by week scoring per player

Setup:
    pip install espn_api pandas
    espn_auth.json must already exist in this folder.
    espn_player_stats_season.csv / espn_player_stats_weekly.csv (the
    existing 2020-2025 files) must be in this folder to merge into.

Run (re-run each week to refresh 2026):
    python pull_espn_stats_2026.py
=============================================================================
"""

import json
from pathlib import Path

from espn_api.football import League
import pandas as pd

LEAGUE_ID = 9954376
SEASON = 2026
SKILL_POS = {"QB", "RB", "WR", "TE"}

SEASON_STAT_KEY = 0  # key 0 in player.stats = season-to-date totals

AUTH_FILE = Path(__file__).parent / "espn_auth.json"
SEASON_FILE = Path(__file__).parent / "espn_player_stats_season.csv"
WEEKLY_FILE = Path(__file__).parent / "espn_player_stats_weekly.csv"

# 2026 ESPN fantasy team name -> manager (same mapping used in
# build_projected_sos.py -- confirmed correct for this season).
TEAM_TO_MANAGER = {
    "N.Y. Routensss": "Andrew Root",
    "Oh He Likes Cooking!": "Ethan Radecki",
    "(Dan wash)Burn": "Max Malich",
    "Leased to Jetty": "Deniz Bileydi",
    "A$AP Monke": "Ben Castaldo",
    "STATION GRITS": "Baylen Slansky",
    "Shakir to death": "Cole Maney",
    "LaPorta Potty": "Carmine Pittelli",
    "No Fox Gibbs'en": "Charlie Gorman",
    "The Gegwich Effect": "Quin Gegwich",
    "The Minutemen": "Brandon Hancock",
    "Rolls With Butter": "Anthony Kelly",
    "Make Fantasy Great Again": "Ryan McQuaid",
    "Quigley FC": "Aidan Quigley",
}


def load_auth():
    if not AUTH_FILE.exists():
        raise SystemExit(f"Missing {AUTH_FILE.name} in this folder.")
    with open(AUTH_FILE) as f:
        auth = json.load(f)
    return auth.get("espn_s2", "").strip(), auth.get("swid", "").strip()


def main():
    espn_s2, swid = load_auth()

    print(f"Pulling season {SEASON}...")
    try:
        league = League(league_id=LEAGUE_ID, year=SEASON, espn_s2=espn_s2, swid=swid)
    except Exception as e:
        raise SystemExit(f"Could not load season {SEASON}: {e}")

    # Collect all players from every team roster, and separately track
    # who currently owns each one -- this is what lets us tell a true
    # free agent apart from a waiver pickup nobody drafted (both show up
    # as "not in draft_history", but only one of them is actually
    # unowned right now).
    seen_ids = set()
    players = []
    current_owner = {}  # player_id -> manager, for anyone rostered right now
    for team in league.teams:
        manager = TEAM_TO_MANAGER.get(team.team_name, team.team_name)
        for player in team.roster:
            current_owner[player.playerId] = manager
            if player.playerId not in seen_ids:
                seen_ids.add(player.playerId)
                players.append(player)

    # Also pull free agents to capture players not currently rostered.
    # Anyone NOT in current_owner after this loop is genuinely unowned.
    try:
        fas = league.free_agents(size=500)
        for player in fas:
            if player.playerId not in seen_ids:
                seen_ids.add(player.playerId)
                players.append(player)
    except Exception as e:
        print(f"  Free agents unavailable: {e}")

    print(f"  Total unique players found: {len(players)}")

    season_rows = []
    weekly_rows = []
    skill_count = 0

    for player in players:
        if player.position not in SKILL_POS:
            continue
        skill_count += 1

        season_stats = player.stats.get(SEASON_STAT_KEY, {})
        total_pts = season_stats.get("points", 0) or 0
        avg_pts = season_stats.get("avg_points", 0) or 0
        games_played = round(total_pts / avg_pts) if avg_pts and avg_pts > 0 else 0

        season_rows.append({
            "player_id": player.playerId,
            "player_name": player.name,
            "position": player.position,
            "nfl_team": getattr(player, "proTeam", None),
            "season": SEASON,
            "total_ppr": round(total_pts, 2),
            "games_played": games_played,
            "ppr_per_game": round(avg_pts, 2),
            "current_manager": current_owner.get(player.playerId),  # None = true free agent
        })

        for week_key, week_stats in player.stats.items():
            if not isinstance(week_key, int) or week_key == 0:
                continue
            week_pts = week_stats.get("points", None)
            if week_pts is None:
                continue
            weekly_rows.append({
                "player_id": player.playerId,
                "player_name": player.name,
                "position": player.position,
                "season": SEASON,
                "week": week_key,
                "ppr_points": round(week_pts, 2),
            })

    print(f"  Skill position players: {skill_count}")

    df_season_new = pd.DataFrame(season_rows)
    df_weekly_new = pd.DataFrame(weekly_rows)

    # ── Merge into existing files: drop any prior season=2026 rows first ──
    if SEASON_FILE.exists():
        df_season_existing = pd.read_csv(SEASON_FILE)
        df_season_existing = df_season_existing[df_season_existing["season"] != SEASON]
        df_season = pd.concat([df_season_existing, df_season_new], ignore_index=True)
    else:
        print(f"  {SEASON_FILE.name} not found -- creating new (2020-2025 data won't be included).")
        df_season = df_season_new

    if WEEKLY_FILE.exists():
        df_weekly_existing = pd.read_csv(WEEKLY_FILE)
        df_weekly_existing = df_weekly_existing[df_weekly_existing["season"] != SEASON]
        df_weekly = pd.concat([df_weekly_existing, df_weekly_new], ignore_index=True)
    else:
        print(f"  {WEEKLY_FILE.name} not found -- creating new (2020-2025 data won't be included).")
        df_weekly = df_weekly_new

    df_season = df_season.sort_values(["season", "player_name"]).reset_index(drop=True)
    df_weekly = df_weekly.sort_values(["season", "player_name", "week"]).reset_index(drop=True)

    df_season.to_csv(SEASON_FILE, index=False)
    df_weekly.to_csv(WEEKLY_FILE, index=False)

    print(f"\n--- 2026 sanity check: top 5 PPR/game per position so far ---")
    for pos in ["QB", "RB", "WR", "TE"]:
        top = df_season_new[df_season_new["position"] == pos].nlargest(5, "ppr_per_game")
        print(f"\n{pos}:")
        print(top[["player_name", "ppr_per_game", "games_played", "total_ppr"]].to_string(index=False))

    print(f"\n=== Done ===")
    print(f"{SEASON_FILE.name} — {len(df_season)} total rows ({len(df_season_new)} from 2026)")
    print(f"{WEEKLY_FILE.name} — {len(df_weekly)} total rows ({len(df_weekly_new)} from 2026)")


if __name__ == "__main__":
    main()
