"""
Projected Strength of Schedule (SOS) — Preach Fantasy, 2026 season.
REST-OF-SEASON VERSION: only projects weeks that haven't been played yet.

Pipeline:
  1. Pull weekly box scores for weeks START_WEEK-14 (regular season only, per
     schedule_2026.csv) via the espn_api library. Prior weeks are skipped
     entirely -- SOS reflects only what's left on the schedule, not a blend
     of past results and future projections.
  2. For each team/week, determine the "optimal" starting lineup: use the
     currently rostered starter UNLESS that player's NFL team is on a BYE
     that week, in which case substitute the highest-projected eligible
     bench player. If no eligible bench player exists at that position,
     fall back to a fixed default projection (edit FIXED_DEFAULTS below).
  3. Join against schedule_2026.csv to find each manager's opponent each
     week, and compute:
       - own_avg_proj_ppg   = average of the manager's own weekly total
       - sos_avg_opp_ppg    = average of the manager's OPPONENTS' weekly
                               totals across the remaining schedule
                               (higher = harder projected schedule)
  4. Write results to projected_sos_2026.csv and print a ranked summary.

Weekly maintenance:
    Bump START_WEEK below before each run -- set it to the current week
    (the next one that hasn't been played), so "rest of season" always
    means "from here forward." Once START_WEEK > NUM_WEEKS the regular
    season is over and this script has nothing left to project.

Setup:
    pip install espn_api pandas
    espn_auth.json must already exist in this folder from the earlier pull.
    schedule_2026.csv must be in this folder too.

Run:
    python build_projected_sos.py
"""

import json
import sys
from pathlib import Path
from collections import defaultdict

import pandas as pd
from espn_api.football import League

LEAGUE_ID = 9954376
SEASON = 2026
NUM_WEEKS = 14  # regular season only, per schedule_2026.csv

# Bump this each week to the next unplayed week. "Rest of season" starts
# here -- weeks before this are skipped entirely, not just excluded from
# the average, so a completed week never gets pulled or blended in.
START_WEEK = 3

AUTH_FILE = Path(__file__).parent / "espn_auth.json"
SCHEDULE_FILE = Path(__file__).parent / "schedule_2026.csv"
OUTPUT_FILE = Path(__file__).parent / "projected_sos_2026.csv"
WEEKLY_DETAIL_FILE = Path(__file__).parent / "projected_sos_weekly_detail.csv"

# ---------------------------------------------------------------------------
# 2026 NFL bye weeks (source: NFL.com schedule release, May 2026)
# ---------------------------------------------------------------------------
NFL_BYES = {
    5: {"CAR", "KC"},
    6: {"CIN", "DET", "MIA", "MIN"},
    7: {"BUF", "JAX", "LAC", "WSH"},
    8: {"HOU", "NO", "NYG", "SF"},
    9: {"PIT", "TEN"},
    10: {"CHI", "DEN", "PHI", "TB"},
    11: {"ATL", "CLE", "GB", "LAR", "NE", "SEA"},
    12: set(),
    13: {"BAL", "IND", "LV", "NYJ"},
    14: {"ARI", "DAL"},
}

# Fallback projection if a team has NO eligible bench player at a position
# during a bye week (e.g. no backup K/D-ST/QB/TE). Ethan: edit these as needed.
FIXED_DEFAULTS = {
    "QB": 14.0,
    "RB": 4.0,
    "WR": 8.0,
    "TE": 6.0,
    "K": 7.0,
    "D/ST": 4.0,
}

# Which roster slots count as "starters" (everything else is bench/IR)
STARTER_SLOTS = {"QB", "RB", "WR", "TE", "RB/WR/TE", "K", "D/ST", "FLEX"}

# ESPN fantasy team name -> manager (normalized to match schedule_2026.csv)
TEAM_TO_MANAGER = {
    "N.Y. Routensss": "Andrew Root",
    "Oh He Likes Cooking!": "Ethan Radecki",
    "Tee'd up": "Max Malich",
    "Leased to Jetty": "Deniz Bileydi",
    "A$AP Monke": "Ben Castaldo",
    "STATION GRITS": "Baylen Slansky",
    "Maneys miserable team": "Cole Maney",
    "Breece's Pieces": "Carmine Pittelli",
    "No Fox Gibbs'en": "Charlie Gorman",
    "The Gegwich Effect": "Quin Gegwich",
    "The Minutemen": "Brandon Hancock",
    "Rolls With Butter": "Anthony Kelly",
    "Make Fantasy Great Again": "Ryan McQuaid",
    "SheLoveQuigs": "Aidan Quigley",
}


def load_auth():
    if not AUTH_FILE.exists():
        print(f"Missing {AUTH_FILE.name} in this folder.")
        sys.exit(1)
    with open(AUTH_FILE) as f:
        auth = json.load(f)
    return auth.get("espn_s2", "").strip(), auth.get("swid", "").strip()


def eligible_for_slot(position, slot):
    """Can a bench player of `position` fill the given empty starter `slot`?"""
    if slot == position:
        return True
    if slot in ("RB/WR/TE", "FLEX") and position in ("RB", "WR", "TE"):
        return True
    return False


def compute_team_week_total(lineup, week):
    """
    Given a team's full box-score lineup for a week, return the bye-aware
    starter projected total, plus a log of any substitutions made.
    """
    starters = [p for p in lineup if p.slot_position in STARTER_SLOTS]
    bench = [p for p in lineup if p.slot_position not in STARTER_SLOTS and p.slot_position != "IR"]

    bye_teams_this_week = NFL_BYES.get(week, set())
    used_bench_ids = set()
    total = 0.0
    subs_log = []

    for p in starters:
        pro_team = getattr(p, "proTeam", None)
        on_bye = pro_team in bye_teams_this_week
        proj = p.projected_points or 0.0
        # A projected-zero starter (no games, no projection data, etc.) is
        # treated the same as a bye: skip them over and try to substitute,
        # rather than letting a bare 0.0 drag the team total down.
        needs_sub = on_bye or proj == 0.0

        if not needs_sub:
            total += proj
            continue

        reason = "BYE" if on_bye else "ZERO PROJ"

        # Find best eligible bench replacement not already used, not also on
        # bye, and not itself projected zero -- a zero-projected bench player
        # isn't a real substitution option, so skip it over too.
        candidates = [
            b for b in bench
            if b.playerId not in used_bench_ids
            and eligible_for_slot(b.position, p.slot_position)
            and getattr(b, "proTeam", None) not in bye_teams_this_week
            and (b.projected_points or 0.0) > 0.0
        ]
        if candidates:
            best = max(candidates, key=lambda b: b.projected_points or 0.0)
            used_bench_ids.add(best.playerId)
            total += best.projected_points or 0.0
            subs_log.append(
                f"W{week}: {p.name} ({reason}, {pro_team}) -> {best.name} "
                f"({best.projected_points:.1f})"
            )
        else:
            fallback = FIXED_DEFAULTS.get(p.position, 0.0)
            total += fallback
            subs_log.append(
                f"W{week}: {p.name} ({reason}, {pro_team}) -> NO BENCH OPTION, "
                f"used fixed default {fallback}"
            )

    return total, subs_log


def main():
    if START_WEEK > NUM_WEEKS:
        print(f"START_WEEK ({START_WEEK}) is past the regular season "
              f"({NUM_WEEKS} weeks) -- nothing left to project.")
        sys.exit(0)

    espn_s2, swid = load_auth()

    print(f"Loading league {LEAGUE_ID}, season {SEASON}...")
    league = League(league_id=LEAGUE_ID, year=SEASON, espn_s2=espn_s2, swid=swid)
    print(f"Loaded. {len(league.teams)} teams found.")
    print(f"Rest-of-season projection: weeks {START_WEEK}-{NUM_WEEKS}.\n")

    team_week_totals = defaultdict(dict)  # {team_name: {week: total}}
    all_subs_log = []

    for week in range(START_WEEK, NUM_WEEKS + 1):
        print(f"Pulling week {week}...")
        try:
            box_scores = league.box_scores(week)
        except Exception as e:
            print(f"  Could not pull week {week}: {e}")
            continue

        for bs in box_scores:
            for team, lineup in [
                (bs.home_team, bs.home_lineup),
                (bs.away_team, bs.away_lineup),
            ]:
                if team is None:
                    continue
                total, subs_log = compute_team_week_total(lineup, week)
                team_week_totals[team.team_name][week] = round(total, 2)
                all_subs_log.extend(subs_log)

    # Save the raw weekly detail (team x week matrix) for inspection
    detail_rows = []
    for team_name, weeks in team_week_totals.items():
        manager = TEAM_TO_MANAGER.get(team_name, team_name)
        for week, total in weeks.items():
            detail_rows.append({"manager": manager, "team_name": team_name, "week": week, "proj_ppg": total})
    detail_df = pd.DataFrame(detail_rows).sort_values(["manager", "week"])
    detail_df.to_csv(WEEKLY_DETAIL_FILE, index=False)
    print(f"\nSaved weekly detail to {WEEKLY_DETAIL_FILE.name}")

    if all_subs_log:
        print(f"\n{len(all_subs_log)} bye-week substitutions made. Sample:")
        for line in all_subs_log[:15]:
            print(f"  {line}")
        if len(all_subs_log) > 15:
            print(f"  ... and {len(all_subs_log) - 15} more (not printed)")

    # ------------------------------------------------------------------
    # Join with schedule to compute SOS (weeks >= START_WEEK only)
    # ------------------------------------------------------------------
    if not SCHEDULE_FILE.exists():
        print(f"\nMissing {SCHEDULE_FILE.name} — can't compute SOS without the schedule.")
        sys.exit(1)

    schedule = pd.read_csv(SCHEDULE_FILE)
    schedule = schedule[schedule["Week"] >= START_WEEK]

    # manager -> {week: total} lookup, keyed by manager name (not team name)
    manager_week_totals = defaultdict(dict)
    for team_name, weeks in team_week_totals.items():
        manager = TEAM_TO_MANAGER.get(team_name)
        if manager is None:
            print(f"WARNING: no manager mapping for team '{team_name}', skipping.")
            continue
        manager_week_totals[manager] = weeks

    sos_rows = []
    for manager in manager_week_totals:
        opp_totals = []
        own_totals = []
        for _, row in schedule.iterrows():
            week = row["Week"]
            if row["Team_A"] == manager:
                opponent = row["Team_B"]
            elif row["Team_B"] == manager:
                opponent = row["Team_A"]
            else:
                continue

            own = manager_week_totals.get(manager, {}).get(week)
            opp = manager_week_totals.get(opponent, {}).get(week)
            if own is not None:
                own_totals.append(own)
            if opp is not None:
                opp_totals.append(opp)

        if own_totals and opp_totals:
            sos_rows.append({
                "manager": manager,
                "own_avg_proj_ppg": round(sum(own_totals) / len(own_totals), 2),
                "sos_avg_opp_proj_ppg": round(sum(opp_totals) / len(opp_totals), 2),
                "weeks_counted": len(opp_totals),
            })

    sos_df = pd.DataFrame(sos_rows).sort_values("sos_avg_opp_proj_ppg", ascending=False)
    sos_df["sos_rank_hardest_first"] = range(1, len(sos_df) + 1)
    sos_df.to_csv(OUTPUT_FILE, index=False)

    print(f"\n=== Rest-of-Season Projected SOS (2026, weeks {START_WEEK}-{NUM_WEEKS}) ===")
    print(sos_df.to_string(index=False))
    print(f"\nSaved to {OUTPUT_FILE.name}")


if __name__ == "__main__":
    main()
