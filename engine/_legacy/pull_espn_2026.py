"""
pull_espn_2026.py

Pulls the live season's weekly box scores from ESPN (espn_api) and writes:
  weekly_rosters_2026.csv  - same schema as weekly_rosters_clean.csv
  teams_2026.csv           - Manager, Fantasy_Team, Conference, Draft_Slot

Manager names are NOT guessed from ESPN owner fields. Each ESPN team is
matched to a manager by its (week, score) in matchup_data.csv, so the names
are guaranteed to be the exact strings the site already uses
("Ryan P McQuaid", "Carmine Pittelli Jr.", ...). Any team that can't be
matched stops the run.

Usage (from the repo root, next to espn_auth.json):
  python pull_espn_2026.py            # pulls weeks 1..last completed week in matchup_data.csv
  python pull_espn_2026.py 3          # pulls weeks 1..3
"""
import json
import sys
import pandas as pd
from espn_api.football import League

LEAGUE_ID = 9954376
SEASON = 2026
MATCHUP_CSV = "GitHubRepoData/matchup_data.csv"
AUTH_JSON = "espn_auth.json"
ROSTERS_OUT = f"weekly_rosters_{SEASON}.csv"
TEAMS_OUT = f"teams_{SEASON}.csv"


def load_auth():
    with open(AUTH_JSON) as f:
        auth = json.load(f)
    low = {k.lower(): v for k, v in auth.items()}
    return low.get("espn_s2"), low.get("swid")


def main():
    m = pd.read_csv(MATCHUP_CSV)
    live = m[(m["Season_Year"] == SEASON) & m["Week"].str.startswith("Week ")].copy()
    live["WeekNum"] = live["Week"].str.replace("Week ", "", regex=False).astype(int)
    last_week = int(sys.argv[1]) if len(sys.argv) > 1 else int(live["WeekNum"].max())

    espn_s2, swid = load_auth()
    league = League(league_id=LEAGUE_ID, year=SEASON, espn_s2=espn_s2, swid=swid)

    team_to_mgr = {}      # espn team_id -> manager name (site spelling)
    rows = []
    for week in range(1, last_week + 1):
        scores = live[live["WeekNum"] == week]
        for bs in league.box_scores(week):
            for team, score, lineup in ((bs.home_team, bs.home_score, bs.home_lineup),
                                        (bs.away_team, bs.away_score, bs.away_lineup)):
                if not team:          # bye / empty side
                    continue
                hit = scores[(scores["Team_Score"] - float(score)).abs() < 0.005]
                if len(hit) != 1:
                    raise SystemExit(f"Week {week}: can't match {team.team_name} "
                                     f"(score {score}) to exactly one matchup_data row")
                mgr = hit["Team_Name"].iloc[0]
                prev = team_to_mgr.setdefault(team.team_id, mgr)
                if prev != mgr:
                    raise SystemExit(f"team_id {team.team_id} matched to both {prev} and {mgr}")

                starters_total = 0.0
                for p in lineup:
                    slot = p.slot_position
                    started = slot not in ("BE", "IR")
                    pts = round(float(p.points or 0.0), 2)
                    if started:
                        starters_total += pts
                    rows.append({
                        "Season": SEASON, "Week": week, "Manager": mgr,
                        "Fantasy_Team": team.team_name, "Player": p.name,
                        "Player_ID": p.playerId, "Position": p.position, "Slot": slot,
                        "Started": started, "Points": pts,
                        "Week_Label": f"Week {week}", "Is_Playoff": "No",
                    })
                if abs(starters_total - float(score)) > 0.05:
                    print(f"  NOTE week {week} {mgr}: starters sum {starters_total:.2f} "
                          f"vs team score {float(score):.2f}")

    missing = set(live["Team_Name"]) - set(team_to_mgr.values())
    if missing:
        raise SystemExit(f"Managers never matched: {sorted(missing)}")

    pd.DataFrame(rows).to_csv(ROSTERS_OUT, index=False)
    print(f"Wrote {ROSTERS_OUT}: {len(rows)} rows, weeks 1-{last_week}")

    # Team metadata: latest fantasy team name, division (conference), round-1 draft slot
    slot_by_team = {}
    for pick in league.draft:
        if pick.round_num == 1:
            slot_by_team[pick.team.team_id] = pick.round_pick
    meta = []
    for t in league.teams:
        meta.append({
            "Manager": team_to_mgr[t.team_id],
            "Fantasy_Team": t.team_name,
            "Conference": getattr(t, "division_name", ""),
            "Draft_Slot": slot_by_team.get(t.team_id, ""),
        })
    meta = pd.DataFrame(meta).sort_values("Draft_Slot")
    meta.to_csv(TEAMS_OUT, index=False)
    print(f"Wrote {TEAMS_OUT}:")
    print(meta.to_string(index=False))


if __name__ == "__main__":
    main()
