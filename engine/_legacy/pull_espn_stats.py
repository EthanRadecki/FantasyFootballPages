import json as _json; _AUTH = {k.lower(): v for k, v in _json.load(open("espn_auth.json")).items()}  # credentials stay out of code
from espn_api.football import League
import pandas as pd

# =============================================================================
# Preach Fantasy — ESPN API Player Stats Pull
# Uses espn-api library to pull accurate fantasy scoring per player per season
# Full player names + ESPN player IDs — no fuzzy matching needed
# =============================================================================
# Outputs:
#   espn_player_stats_season.csv  — season totals per player
#   espn_player_stats_weekly.csv  — week by week scoring per player
# =============================================================================

LEAGUE_ID = 9954376
ESPN_S2   = _AUTH["espn_s2"]
SWID      = _AUTH["swid"]

SEASONS   = [2020, 2021, 2022, 2023, 2024, 2025]
SKILL_POS = {"QB", "RB", "WR", "TE"}

SEASON_STAT_KEY = 0  # key 0 in player.stats = full season totals

all_season_rows = []
all_weekly_rows = []

for season in SEASONS:
    print(f"\nPulling season {season}...")

    try:
        league = League(
            league_id=LEAGUE_ID,
            year=season,
            espn_s2=ESPN_S2,
            swid=SWID,
        )
    except Exception as e:
        print(f"  Could not load season {season}: {e}")
        continue

    # Collect all players from every team roster
    seen_ids = set()
    players  = []

    for team in league.teams:
        for player in team.roster:
            if player.playerId not in seen_ids:
                seen_ids.add(player.playerId)
                players.append(player)

    # Also pull free agents to capture players not rostered all season
    try:
        fas = league.free_agents(size=500)
        for player in fas:
            if player.playerId not in seen_ids:
                seen_ids.add(player.playerId)
                players.append(player)
    except Exception as e:
        print(f"  Free agents unavailable: {e}")

    print(f"  Total unique players found: {len(players)}")

    skill_count = 0
    for player in players:
        if player.position not in SKILL_POS:
            continue

        skill_count += 1

        # Season totals
        season_stats = player.stats.get(SEASON_STAT_KEY, {})
        total_pts    = season_stats.get("points", 0) or 0
        avg_pts      = season_stats.get("avg_points", 0) or 0

        if avg_pts and avg_pts > 0:
            games_played = round(total_pts / avg_pts)
        else:
            games_played = 0

        all_season_rows.append({
            "player_id":    player.playerId,
            "player_name":  player.name,
            "position":     player.position,
            "season":       season,
            "total_ppr":    round(total_pts, 2),
            "games_played": games_played,
            "ppr_per_game": round(avg_pts, 2),
        })

        # Weekly stats
        for week_key, week_stats in player.stats.items():
            if not isinstance(week_key, int) or week_key == 0:
                continue
            week_pts = week_stats.get("points", None)
            if week_pts is None:
                continue
            all_weekly_rows.append({
                "player_id":   player.playerId,
                "player_name": player.name,
                "position":    player.position,
                "season":      season,
                "week":        week_key,
                "ppr_points":  round(week_pts, 2),
            })

    print(f"  Skill position players: {skill_count}")

# Build DataFrames
df_season = pd.DataFrame(all_season_rows)
df_weekly  = pd.DataFrame(all_weekly_rows)

# Sanity check
print("\n--- Sanity check: Top 5 PPR/game per position in 2024 ---")
if len(df_season) > 0:
    bench_2024 = df_season[
        (df_season["season"] == 2024) &
        (df_season["games_played"] >= 10)
    ]
    for pos in ["QB", "RB", "WR", "TE"]:
        top = bench_2024[bench_2024["position"] == pos].nlargest(5, "ppr_per_game")
        print(f"\n{pos}:")
        print(top[["player_name", "ppr_per_game", "games_played", "total_ppr"]].to_string(index=False))

print(f"\n--- Season coverage ---")
print(df_season.groupby("season").size().to_string())

# Save
df_season.to_csv("espn_player_stats_season.csv", index=False)
df_weekly.to_csv("espn_player_stats_weekly.csv",  index=False)

print(f"\n=== Done ===")
print(f"espn_player_stats_season.csv — {len(df_season)} rows")
print(f"espn_player_stats_weekly.csv  — {len(df_weekly)} rows")


import pandas as pd
df = pd.read_csv("draft_history.csv")
print(df.columns.tolist())
print(df.head(3).to_string())
