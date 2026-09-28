"""
Test pull: one week of ESPN fantasy projections using the espn_api library.

This replaces the raw-requests approach, since your old
espn_player_stats pull script proves espn_api already handles
ESPN's auth correctly for this league.

Setup:
    1. pip install espn_api pandas
    2. Create espn_auth.json in the same folder as this script:
           {
             "espn_s2": "...",
             "swid": "{...}"
           }
    3. python test_espn_api_pull.py --week 1
"""

import sys
import json
import argparse
from pathlib import Path

from espn_api.football import League

LEAGUE_ID = 9954376
SEASON = 2026

AUTH_FILE = Path(__file__).parent / "espn_auth.json"


def load_auth():
    if not AUTH_FILE.exists():
        print(f"Missing {AUTH_FILE.name} in this folder.")
        sys.exit(1)
    with open(AUTH_FILE) as f:
        auth = json.load(f)
    return auth.get("espn_s2", "").strip(), auth.get("swid", "").strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--week", type=int, default=1)
    args = parser.parse_args()

    espn_s2, swid = load_auth()

    print(f"Loading league {LEAGUE_ID}, season {SEASON}...")
    league = League(league_id=LEAGUE_ID, year=SEASON, espn_s2=espn_s2, swid=swid)
    print(f"Loaded. Teams found: {len(league.teams)}")
    for t in league.teams:
        print(f"  - {t.team_name}")

    print(f"\nPulling box scores for week {args.week}...")
    box_scores = league.box_scores(args.week)
    print(f"Box scores returned: {len(box_scores)} matchups")

    for bs in box_scores:
        for team, lineup in [
            (bs.home_team, bs.home_lineup),
            (bs.away_team, bs.away_lineup),
        ]:
            if team is None:
                continue
            print(f"\n=== {team.team_name} (Week {args.week}) ===")
            starter_proj_total = 0.0
            for player in lineup:
                is_bench = player.slot_position in ("BE", "IR")
                marker = "  (bench)" if is_bench else ""
                print(
                    f"  {player.name:<28} {player.position:<5} "
                    f"slot={player.slot_position:<6} "
                    f"proj={player.projected_points}{marker}"
                )
                if not is_bench:
                    starter_proj_total += player.projected_points or 0
            print(f"  --> starter projected total: {round(starter_proj_total, 1)}")


if __name__ == "__main__":
    main()
