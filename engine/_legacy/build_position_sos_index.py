"""
Builds a ratio-based, volume-weighted defense-vs-position SOS index.

For every player-week: ratio = actual points / player's own season average
(excluding that week, i.e. leave-one-out, to avoid a player's own game
inflating his own baseline). Index = 100 * weighted average of these
ratios, weighted by the player's season-total points (so a low-volume
player's one fluky game doesn't move a defense's index much).

100 = defense performs exactly at position-average expectation.
>100 = defense plays into that position's hands (allows more than normal).
<100 = defense suppresses that position (allows less than normal).
"""
import csv
from collections import defaultdict

ROSTER_PATH = "/mnt/project/weekly_rosters_bracket_only.csv"
OPP_PATH = "/mnt/user-data/uploads/player_opponents.csv"
OUT_PATH = "/home/claude/sos_pipeline/position_sos_index.csv"

# ---- Load data ----
roster_rows = []
with open(ROSTER_PATH, encoding="utf-8") as f:
    for row in csv.DictReader(f):
        roster_rows.append(row)

VALID_TEAMS = {
    "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN",
    "DET", "GB", "HOU", "IND", "JAX", "KC", "LAC", "LAR", "LV", "MIA",
    "MIN", "NE", "NO", "NYG", "NYJ", "PHI", "PIT", "SEA", "SF", "TB",
    "TEN", "WSH",
}

opp_lookup = {}
with open(OPP_PATH, encoding="utf-8") as f:
    for row in csv.DictReader(f):
        if row["opponent"] not in VALID_TEAMS:
            continue  # drops stray AFC/NFC Pro Bowl artifacts from ESPN's own data
        opp_lookup[(row["player_id"], row["season"], row["week"])] = row["opponent"]

# ---- Compute each player's season totals/games (for leave-one-out avg & volume weight) ----
# key: (player_id, season, position) -> list of (week, points)
player_season_games = defaultdict(list)
for row in roster_rows:
    key = (row["Player_ID"], row["Season"], row["Position"])
    player_season_games[key].append((row["Week"], float(row["Points"])))

# ---- Build weighted ratios per (defense_team, position, season) ----
# accumulate numerator = sum(weight * ratio), denominator = sum(weight)
agg = defaultdict(lambda: [0.0, 0.0, 0])  # [weighted_ratio_sum, weight_sum, n_games]

POSITIONS = {"QB", "RB", "WR", "TE"}  # D/ST and K excluded -- ratio metric doesn't apply cleanly

for row in roster_rows:
    pos = row["Position"]
    if pos not in POSITIONS:
        continue
    pid, season, week = row["Player_ID"], row["Season"], row["Week"]
    opp = opp_lookup.get((pid, season, week))
    if opp is None:
        continue
    points = float(row["Points"])

    games = player_season_games[(pid, season, pos)]
    season_total = sum(p for _, p in games)
    n_games = len(games)
    if n_games <= 1:
        continue  # can't compute leave-one-out average from a single game
    # leave-one-out average: season average excluding this specific week
    loo_avg = (season_total - points) / (n_games - 1)
    if loo_avg <= 0:
        continue  # avoid divide-by-zero / meaningless ratios for scored-only-once players
    ratio = points / loo_avg

    # volume weight = player's season total points at this position
    weight = max(season_total, 0.1)  # floor to avoid zero-weighting a scoreless season

    key = (opp, pos, season)
    agg[key][0] += weight * ratio
    agg[key][1] += weight
    agg[key][2] += 1

# ---- Write output ----
raw_rows = []
for (team, pos, season), (wsum, weight_sum, n) in agg.items():
    if weight_sum <= 0:
        continue
    raw_index = wsum / weight_sum  # un-normalized, centered above 1.0 due to small-sample bias
    raw_rows.append({"team": team, "position": pos, "season": season,
                      "raw_index": raw_index, "n_player_games": n})

# Normalize within each (position, season) group so the league average is
# exactly 100. This cancels the leave-one-out ratio's small-sample upward
# bias (a known statistical artifact, not a real defensive effect) and is
# also just the correct framing: SOS is about relative difficulty across
# that season's 32 defenses, not an absolute ratio value.
group_sums = defaultdict(lambda: [0.0, 0])
for r in raw_rows:
    key = (r["position"], r["season"])
    group_sums[key][0] += r["raw_index"]
    group_sums[key][1] += 1

rows_out = []
for r in raw_rows:
    key = (r["position"], r["season"])
    group_mean = group_sums[key][0] / group_sums[key][1]
    normalized_index = 100.0 * r["raw_index"] / group_mean
    rows_out.append({
        "team": r["team"], "position": r["position"], "season": r["season"],
        "index": round(normalized_index, 1), "n_player_games": r["n_player_games"],
    })

rows_out.sort(key=lambda r: (r["season"], r["position"], r["team"]))

with open(OUT_PATH, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=["team", "position", "season", "index", "n_player_games"])
    w.writeheader()
    w.writerows(rows_out)

print(f"Wrote {len(rows_out)} (team, position, season) rows to {OUT_PATH}")
