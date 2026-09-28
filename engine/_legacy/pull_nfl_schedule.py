"""
Pulls NFL team-vs-team matchups (who played whom, each week) from ESPN's
public scoreboard endpoint. No auth needed, unlike the fantasy league pull.

This is the missing link for defense-vs-position SOS: joined with
weekly_rosters_bracket_only.csv (which has player + position + points per
week but not their NFL opponent), it lets us compute, for every NFL team,
how many fantasy points they've allowed to each position, per week.

Usage:
    python pull_nfl_schedule.py --start 2020 --end 2026

Output: ./output/nfl_schedule_2020_2026.csv
    columns: season, week, team, opponent, is_home
    (one row per team per game, so both sides of each matchup are present)
"""

import argparse
import csv
import os
import time
import requests

BASE = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
OUTPUT_DIR = "./output"


def pull_week(season, week):
    params = {"seasontype": 2, "week": week, "dates": season}
    resp = requests.get(BASE, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    rows = []
    for event in data.get("events", []):
        comps = event.get("competitions", [])
        if not comps:
            continue
        competitors = comps[0].get("competitors", [])
        if len(competitors) != 2:
            continue
        teams = {c["homeAway"]: c["team"]["abbreviation"] for c in competitors}
        home, away = teams.get("home"), teams.get("away")
        if not home or not away:
            continue
        rows.append({"season": season, "week": week, "team": home, "opponent": away, "is_home": True})
        rows.append({"season": season, "week": week, "team": away, "opponent": home, "is_home": False})
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=2020)
    parser.add_argument("--end", type=int, default=2026)
    parser.add_argument("--max_week", type=int, default=18)
    args = parser.parse_args()

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    all_rows = []
    for season in range(args.start, args.end + 1):
        for week in range(1, args.max_week + 1):
            try:
                rows = pull_week(season, week)
                all_rows.extend(rows)
                print(f"{season} week {week}: {len(rows)//2} games")
            except Exception as e:
                print(f"{season} week {week}: failed ({e})")
            time.sleep(0.3)  # be polite to the endpoint

    out_path = f"{OUTPUT_DIR}/nfl_schedule_{args.start}_{args.end}.csv"
    with open(out_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["season", "week", "team", "opponent", "is_home"])
        w.writeheader()
        w.writerows(all_rows)
    print(f"Wrote {len(all_rows)} rows to {out_path}")


if __name__ == "__main__":
    main()
