import json as _json; _AUTH = {k.lower(): v for k, v in _json.load(open("espn_auth.json")).items()}  # credentials stay out of code
from espn_api.football import League

LEAGUE_ID = 9954376
ESPN_S2   = _AUTH["espn_s2"]
SWID      = _AUTH["swid"]

print("Connecting to ESPN API...")
league = League(league_id=LEAGUE_ID, year=2024, espn_s2=ESPN_S2, swid=SWID)

print(f"League: {league.settings.name}")
print(f"Teams:  {len(league.teams)}")
print(f"Season: {league.year}")

# Show first few players from box scores to confirm player data is accessible
print("\nFirst team's roster:")
team = league.teams[0]
for player in team.roster[:5]:
    print(f"  {player.name} | {player.position} | {player.stats}")
