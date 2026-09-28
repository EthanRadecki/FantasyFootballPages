"""
Pulls each player's per-game NFL opponent from ESPN's public (no-auth)
athlete gamelog endpoint, for every (Player_ID, Season) pair present in
weekly_rosters_bracket_only.csv.

Why this instead of tracking NFL team-per-week: gamelog is already scoped
to individual games, so it's immune to mid-season trades/team changes
that would otherwise silently corrupt a team-affiliation join.

Usage:
    python pull_player_opponents.py --input weekly_rosters_bracket_only.csv

Output: ./output/player_opponents.csv
    columns: player_id, player_name, season, week, opponent
Resumable: re-running skips (player_id, season) pairs already in the
output file, so it's safe to stop and restart if it gets interrupted.
"""

import argparse
import csv
import os
import time
import requests

BASE = "https://site.web.api.espn.com/apis/common/v3/sports/football/nfl/athletes"
OUTPUT_DIR = "./output"
OUTPUT_FILE = f"{OUTPUT_DIR}/player_opponents.csv"


def load_pairs(input_path):
    pairs = {}
    with open(input_path, encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            key = (row["Player_ID"], row["Season"])
            pairs[key] = row["Player"]
    return pairs


def load_done_pairs():
    done = set()
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, encoding="utf-8") as f:
            r = csv.DictReader(f)
            for row in r:
                done.add((row["player_id"], row["season"]))
    return done


TEAM_NICKNAME_TO_ABBR = {
    "Cardinals": "ARI", "Falcons": "ATL", "Ravens": "BAL", "Bills": "BUF",
    "Panthers": "CAR", "Bears": "CHI", "Bengals": "CIN", "Browns": "CLE",
    "Cowboys": "DAL", "Broncos": "DEN", "Lions": "DET", "Packers": "GB",
    "Texans": "HOU", "Colts": "IND", "Jaguars": "JAX", "Chiefs": "KC",
    "Raiders": "LV", "Chargers": "LAC", "Rams": "LAR", "Dolphins": "MIA",
    "Vikings": "MIN", "Patriots": "NE", "Saints": "NO", "Giants": "NYG",
    "Jets": "NYJ", "Eagles": "PHI", "Steelers": "PIT", "Seahawks": "SEA",
    "49ers": "SF", "Buccaneers": "TB", "Titans": "TEN", "Commanders": "WSH",
    "Football Team": "WSH", "Redskins": "WSH", "Washington": "WSH",
}

# Fallback for players whose gamelog call returns a broken stub response
# (HTTP 200, but only {"filters": [...]}, no events -- confirmed happening
# for several long-career/high-profile players, cause unconfirmed but not
# fixable by changing the request). Routes them through the same
# schedule-lookup trick used for D/ST instead of the athlete endpoint.
# Format: (player_name, season) -> [(start_week, end_week, team_abbr), ...]
# inclusive week ranges. Filled in from public record for known mid-season
# trades; single-team seasons filled from general knowledge -- spot-check
# any that look off, this is a manual table, not pulled from an API.
PLAYER_TEAM_OVERRIDE = {
    ("Travis Kelce", "2020"): [(1, 17, "KC")],
    ("Travis Kelce", "2021"): [(1, 17, "KC")],
    ("Travis Kelce", "2022"): [(1, 18, "KC")],
    ("Travis Kelce", "2023"): [(1, 18, "KC")],
    ("Travis Kelce", "2024"): [(1, 18, "KC")],
    ("Travis Kelce", "2025"): [(1, 18, "KC")],
    ("Davante Adams", "2020"): [(1, 17, "GB")],
    ("Davante Adams", "2021"): [(1, 17, "GB")],
    ("Davante Adams", "2022"): [(1, 18, "LV")],
    ("Davante Adams", "2023"): [(1, 18, "LV")],
    ("Davante Adams", "2024"): [(1, 6, "LV"), (7, 18, "NYJ")],  # traded ~Oct 15, 2024
    ("Davante Adams", "2025"): [(1, 18, "LAR")],
    ("Zach Ertz", "2020"): [(1, 17, "PHI")],
    ("Zach Ertz", "2021"): [(1, 6, "PHI"), (7, 18, "ARI")],  # traded Oct 15, 2021
    ("Zach Ertz", "2022"): [(1, 18, "ARI")],
    ("Zach Ertz", "2023"): [(1, 18, "ARI")],
    ("Zach Ertz", "2024"): [(1, 18, "WSH")],
    ("Zach Ertz", "2025"): [(1, 18, "WSH")],
    ("Justin Tucker", "2020"): [(1, 17, "BAL")],
    ("Justin Tucker", "2021"): [(1, 18, "BAL")],
    ("Justin Tucker", "2022"): [(1, 18, "BAL")],
    ("Justin Tucker", "2023"): [(1, 18, "BAL")],
    ("Justin Tucker", "2024"): [(1, 18, "BAL")],
    ("Jarvis Landry", "2020"): [(1, 17, "CLE")],
    ("Jarvis Landry", "2021"): [(1, 18, "CLE")],
    ("Jarvis Landry", "2022"): [(1, 18, "NO")],
    ("T.Y. Hilton", "2020"): [(1, 17, "IND")],
    ("T.Y. Hilton", "2021"): [(1, 18, "IND")],
    ("Michael Thomas", "2021"): [(1, 18, "NO")],
    ("Calvin Ridley", "2022"): [(1, 18, "ATL")],  # suspended all season for gambling -- verify this row has real points
    ("Odell Beckham Jr.", "2022"): [(1, 18, "LAR")],  # recovering from Super Bowl ACL tear -- may not have played; verify
    ("Joe Mixon", "2025"): [(1, 18, "HOU")],
    ("Brandon Aiyuk", "2025"): [(1, 18, "SF")],
    ("MarShawn Lloyd", "2025"): [(1, 18, "GB")],
    ("Jason Sanders", "2025"): [(1, 18, "MIA")],
    ("A.J. Green", "2020"): [(1, 17, "CIN")],
    ("A.J. Green", "2021"): [(1, 18, "CIN")],
    ("A.J. Green", "2022"): [(1, 18, "ARI")],
    ("Giovani Bernard", "2020"): [(1, 17, "CIN")],
    ("Giovani Bernard", "2021"): [(1, 18, "TB")],
    ("John Brown", "2020"): [(1, 17, "BUF")],
    ("Jimmy Garoppolo", "2020"): [(1, 17, "SF")],
    ("Jimmy Garoppolo", "2021"): [(1, 18, "SF")],
    ("Jimmy Garoppolo", "2022"): [(1, 18, "SF")],
    ("Jimmy Garoppolo", "2023"): [(1, 18, "LV")],
    ("Teddy Bridgewater", "2020"): [(1, 17, "CAR")],
    ("Teddy Bridgewater", "2021"): [(1, 18, "DEN")],
    ("Teddy Bridgewater", "2022"): [(1, 18, "MIA")],
    ("Latavius Murray", "2020"): [(1, 17, "NO")],
    ("Latavius Murray", "2021"): [(1, 18, "NO")],
    ("Latavius Murray", "2022"): [(1, 18, "DEN")],
    ("Latavius Murray", "2023"): [(1, 18, "BUF")],  # lower confidence, verify
    ("James White", "2020"): [(1, 17, "NE")],
    ("James White", "2021"): [(1, 18, "NE")],
    ("James White", "2022"): [(1, 18, "NE")],
    ("Allen Robinson II", "2020"): [(1, 17, "CHI")],
    ("Allen Robinson II", "2021"): [(1, 18, "CHI")],
    ("Allen Robinson II", "2022"): [(1, 18, "LAR")],
    ("Allen Robinson II", "2023"): [(1, 18, "PIT")],
    ("Logan Thomas", "2020"): [(1, 17, "WSH")],
    ("Logan Thomas", "2021"): [(1, 18, "WSH")],
    ("Logan Thomas", "2022"): [(1, 18, "WSH")],
    ("Logan Thomas", "2023"): [(1, 18, "NYJ")],  # lower confidence, verify
    ("Andy Dalton", "2020"): [(1, 17, "DAL")],
    ("Andy Dalton", "2022"): [(1, 18, "NO")],
    ("Colt McCoy", "2020"): [(1, 17, "NYG")],  # lower confidence, verify
    ("Rob Gronkowski", "2020"): [(1, 17, "TB")],
    ("Rob Gronkowski", "2021"): [(1, 18, "TB")],
    ("Matt Ryan", "2023"): [(1, 18, "IND")],
    # Deliberately NOT overridden -- these look like retired/suspended/
    # inactive players (Kaepernick, Baldwin, Lynch out of the league;
    # Eli Manning retired after 2019; Deshaun Watson suspended all of
    # 2021; Tom Brady retired/broadcasting in 2024; Ryquell Armstead
    # opted out of 2020 after Week 1; Gronkowski shown for 2023 despite
    # having retired in mid-2022). Worth checking these specific rows in
    # weekly_rosters_bracket_only.csv directly -- if the recorded points
    # are genuinely nonzero, that's a data question, not a pull-script one.
}


def player_games_from_override(player_name, season, schedule):
    """Returns (games, reason) using the manual team-override table."""
    segments = PLAYER_TEAM_OVERRIDE.get((player_name, season))
    if not segments:
        return None, "no override entry for this player/season"
    games = []
    for start_week, end_week, abbr in segments:
        team_games = schedule.get((season, abbr), [])
        for g in team_games:
            wk = int(g["week"])
            if start_week <= wk <= end_week:
                games.append(g)
    if not games:
        return None, f"override team(s) found but no matching schedule rows"
    return games, None


def load_schedule(schedule_path):
    """season,week,team,opponent,is_home -> {(season, team): [(week, opponent), ...]}"""
    sched = {}
    if not schedule_path or not os.path.exists(schedule_path):
        print(f"WARNING: schedule file not found at '{schedule_path}'. "
              f"D/ST rows cannot be resolved without it. Pass --schedule <path>.")
        return sched
    with open(schedule_path, encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            key = (row["season"], row["team"])
            sched.setdefault(key, []).append({"week": row["week"], "opponent": row["opponent"]})
    return sched


def dst_games_from_schedule(player_name, season, schedule):
    """Returns (games, reason). games is None on failure; reason explains why."""
    nickname = player_name.replace(" D/ST", "").strip()
    abbr = TEAM_NICKNAME_TO_ABBR.get(nickname)
    if not abbr:
        return None, f"nickname '{nickname}' not in TEAM_NICKNAME_TO_ABBR"
    games = schedule.get((season, abbr))
    if games is None:
        return None, f"no schedule rows for ({season}, {abbr}) -- schedule file may be missing/empty"
    return games, None


def pull_gamelog(player_id, season, retries=3):
    params = {"season": season}
    last_err = None
    for attempt in range(retries):
        try:
            resp = requests.get(
                f"{BASE}/{player_id}/gamelog",
                params=params,
                timeout=25,
                headers={"Connection": "close"},
            )
            resp.raise_for_status()
            data = resp.json()
            rows = []
            for event in data.get("events", {}).values():
                week = event.get("week")
                opp = event.get("opponent", {}).get("abbreviation")
                if week is not None and opp:
                    rows.append({"week": week, "opponent": opp})
            if not rows:
                # HTTP 200 but nothing usable -- don't fail silently.
                top_keys = list(data.keys())
                raise ValueError(f"200 OK but 0 parsable games (top-level keys: {top_keys})")
            return rows
        except Exception as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1))  # 2s, 4s backoff
    raise last_err


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="weekly_rosters_bracket_only.csv")
    parser.add_argument("--schedule", default="nfl_schedule_2020_2026.csv",
                         help="Path to the NFL schedule CSV, used to resolve D/ST opponents")
    args = parser.parse_args()

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    schedule = load_schedule(args.schedule)
    pairs = load_pairs(args.input)
    done = load_done_pairs()
    print(f"Total (player, season) pairs: {len(pairs)}; already done: {len(done)}")

    write_header = not os.path.exists(OUTPUT_FILE)
    with open(OUTPUT_FILE, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["player_id", "player_name", "season", "week", "opponent"])
        if write_header:
            w.writeheader()

        for i, ((player_id, season), player_name) in enumerate(pairs.items()):
            if (player_id, season) in done:
                continue
            try:
                if player_name.endswith(" D/ST"):
                    games, reason = dst_games_from_schedule(player_name, season, schedule)
                    if games is None:
                        print(f"FAILED (D/ST) {player_name} {season}: {reason}")
                        continue
                else:
                    try:
                        games = pull_gamelog(player_id, season)
                    except Exception as gamelog_err:
                        games, reason = player_games_from_override(player_name, season, schedule)
                        if games is None:
                            print(f"FAILED {player_name} {season}: gamelog error ({gamelog_err}); "
                                  f"override fallback also failed ({reason})")
                            continue
                        print(f"RECOVERED via override: {player_name} {season} ({len(games)} games)")
                for g in games:
                    w.writerow(
                        {
                            "player_id": player_id,
                            "player_name": player_name,
                            "season": season,
                            "week": g["week"],
                            "opponent": g["opponent"],
                        }
                    )
                f.flush()
                if i % 50 == 0:
                    print(f"{i}/{len(pairs)}: {player_name} {season}: {len(games)} games")
            except Exception as e:
                print(f"FAILED {player_name} {season}: {e}")
            time.sleep(0.3)

    print("Done.")


if __name__ == "__main__":
    main()
