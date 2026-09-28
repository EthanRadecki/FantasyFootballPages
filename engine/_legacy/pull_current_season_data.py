"""
Pulls current-season (2026) roster, free-agent pool, and projection data
needed for the live trade/waiver grading tool.

Run locally, in the same place espn_auth.json already lives (same auth
pattern used for 2026_week01.json's proj_ppg pull).

Outputs (written to ./output/):
  - rosters_2026.csv        one row per rostered player, all 14 teams
  - free_agents_2026.csv    one row per unrostered player
  - faab_budget_2026.csv    seed file, $300 per manager (edit/extend as
                             the season's transactions accumulate)

NOTE ON PROJECTIONS: ESPN's public API does not expose a clean "rest of
season" projection field for individual players beyond the current/next
scoring period. What IS available per player:
  - projected_total_points   preseason full-season projection (static,
                              set before Week 1, does not update live)
  - projected_avg_points     preseason per-game projection
  - total_points / avg_points  actual points scored so far this season
  - stats[scoring_period]['projected_points']  per-week projection, but
    typically only populated for the current/upcoming week, not the full
    ROS window

This means true ROS projections (with SOS adjustment, short/medium/long
horizons) will need to be modeled in-house rather than pulled wholesale
from ESPN. This script captures everything ESPN does expose so that model
has real inputs to work with; see pipeline notes for the modeling approach.
"""

import json
import csv
import os
from espn_api.football import League

LEAGUE_ID = 9954376
YEAR = 2026
OUTPUT_DIR = "./output"

# Same normalization used everywhere else on the site.
NAME_ALIASES = {
    "Carmine Pittelli Jr.": "Carmine Pittelli",
    "Ryan P McQuaid": "Ryan McQuaid",
}


def normalize_name(name):
    return NAME_ALIASES.get(name, name)


def load_auth(path="espn_auth.json"):
    with open(path) as f:
        return json.load(f)


def get_manager_name(team):
    """espn_api exposes owners as a list, not a single 'owner' attribute.
    Shape varies by version: list of dicts (with firstName/lastName) or
    list of plain strings. Falls back to team_name if unavailable."""
    owners = getattr(team, "owners", None)
    if not owners:
        return team.team_name
    first = owners[0]
    if isinstance(first, dict):
        name = f"{first.get('firstName', '')} {first.get('lastName', '')}".strip()
        return name if name else team.team_name
    if isinstance(first, str):
        return first
    return team.team_name


def player_row(player, manager, team_name, roster_status):
    """Flatten an espn_api Player object into a CSV row."""
    return {
        "manager": normalize_name(manager) if manager else "",
        "team_name": team_name if team_name else "",
        "roster_status": roster_status,  # "rostered" or "free_agent"
        "player": player.name,
        "player_id": player.playerId,
        "position": player.position,
        "pro_team": getattr(player, "proTeam", ""),
        "lineup_slot": getattr(player, "lineupSlot", ""),
        "injury_status": getattr(player, "injuryStatus", ""),
        "percent_owned": getattr(player, "percent_owned", ""),
        "percent_started": getattr(player, "percent_started", ""),
        "total_points": getattr(player, "total_points", ""),
        "avg_points": getattr(player, "avg_points", ""),
        "projected_total_points": getattr(player, "projected_total_points", ""),
        "projected_avg_points": getattr(player, "projected_avg_points", ""),
    }


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    auth = load_auth()
    league = League(
        league_id=LEAGUE_ID,
        year=YEAR,
        espn_s2=auth["espn_s2"],
        swid=auth["swid"],
    )

    roster_rows = []
    for team in league.teams:
        manager = get_manager_name(team)
        for player in team.roster:
            roster_rows.append(
                player_row(player, manager, team.team_name, "rostered")
            )

    fa_rows = []
    free_agents = league.free_agents(size=1000)
    for player in free_agents:
        fa_rows.append(player_row(player, None, None, "free_agent"))

    fieldnames = list(roster_rows[0].keys()) if roster_rows else list(
        fa_rows[0].keys()
    )

    with open(f"{OUTPUT_DIR}/rosters_2026.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(roster_rows)

    with open(f"{OUTPUT_DIR}/free_agents_2026.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(fa_rows)

    # FAAB seed: $300 per manager, resets each season. Update this file
    # (or regenerate with real deductions) once Week 1 waivers process.
    managers = sorted({normalize_name(get_manager_name(t)) for t in league.teams})
    with open(f"{OUTPUT_DIR}/faab_budget_2026.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["manager", "season", "starting_budget", "remaining_budget"])
        w.writeheader()
        for m in managers:
            w.writerow(
                {
                    "manager": m,
                    "season": YEAR,
                    "starting_budget": 300,
                    "remaining_budget": 300,
                }
            )

    print(f"Rostered players: {len(roster_rows)}")
    print(f"Free agents: {len(fa_rows)}")
    print(f"Managers seeded for FAAB: {len(managers)}")


if __name__ == "__main__":
    main()
