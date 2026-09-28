import pandas as pd
import json

# =============================================================================
# Preach Fantasy — Hit Rate by Round
# =============================================================================
# A "hit" is defined as finishing in the top N at position within that season:
#   WR: top 24  |  RB: top 24  |  QB: top 7  |  TE: top 7
#
# Steals ranked by points above position average (position-normalized),
# not raw PPR/game — prevents QBs from dominating due to higher raw scores.
#
# Rounds grouped into three tiers:
#   Early  — rounds 1-3
#   Middle — rounds 4-7
#   Late   — rounds 8+
#
# Excludes 2025 pending season completion. Minimum 4 games to qualify as a steal.
# =============================================================================

draft = pd.read_csv("draft_with_stats.csv")

# Build benchmark from ESPN stats — players with 10+ games played
espn  = pd.read_csv("espn_player_stats_season.csv")
bench = espn[espn["games_played"] >= 10].copy()

# All seasons included -- 2025 NFL season completed February 2026
draft = draft.copy()

# ── Hit thresholds by position ────────────────────────────────────────────────
HIT_THRESHOLDS = {"WR": 24, "RB": 24, "QB": 7, "TE": 7}

# ── Build season-level hit cutoff AND position average per position ───────────
# hit_cutoffs: PPR/game of the Nth ranked player → defines a "hit"
# pos_averages: mean PPR/game across all qualifiers → used for surplus calc

hit_cutoffs  = {}
pos_averages = {}

for (season, position), group in bench.groupby(["season", "position"]):
    if position not in HIT_THRESHOLDS:
        continue
    ranked = group.sort_values("ppr_per_game", ascending=False).reset_index(drop=True)
    n = HIT_THRESHOLDS[position]
    cutoff = ranked.iloc[n - 1]["ppr_per_game"] if len(ranked) >= n else ranked.iloc[-1]["ppr_per_game"]
    hit_cutoffs[(season, position)]  = cutoff
    pos_averages[(season, position)] = round(ranked["ppr_per_game"].mean(), 2)

# ── Assign hit flag ───────────────────────────────────────────────────────────

def is_hit(row):
    if row["match_status"] in ("no_stats", "manual_zero") or row["ppr_per_game"] == 0:
        return 0
    key = (row["season"], row["position"])
    if key not in hit_cutoffs:
        return 0
    return 1 if row["ppr_per_game"] >= hit_cutoffs[key] else 0

draft["hit"] = draft.apply(is_hit, axis=1)

# ── Assign points above position average ─────────────────────────────────────
# Positive = outperformed league average at that position that season
# This is position-normalized so QBs don't inflate the steals list

def points_above_avg(row):
    if row["ppr_per_game"] == 0:
        return 0.0
    key = (row["season"], row["position"])
    avg = pos_averages.get(key, 0)
    return round(row["ppr_per_game"] - avg, 2)

draft["pts_above_avg"] = draft.apply(points_above_avg, axis=1)

# ── Round tier assignment ─────────────────────────────────────────────────────

def round_tier(r):
    if r <= 3:  return "Early (1-3)"
    if r <= 7:  return "Middle (4-7)"
    return              "Late (8+)"

def round_tier_short(r):
    if r <= 3:  return "Early"
    if r <= 7:  return "Middle"
    return              "Late"

draft["tier"]       = draft["round"].apply(round_tier)
draft["tier_short"] = draft["round"].apply(round_tier_short)

TIER_ORDER = ["Early (1-3)", "Middle (4-7)", "Late (8+)"]
TIER_SHORT  = ["Early", "Middle", "Late"]

# ── Hit rate by tier × position ───────────────────────────────────────────────

results = []
for tier in TIER_ORDER:
    tier_df = draft[draft["tier"] == tier]
    for pos in ["RB", "WR", "QB", "TE"]:
        pos_df = tier_df[tier_df["position"] == pos]
        total  = len(pos_df)
        hits   = pos_df["hit"].sum()
        rate   = round(hits / total * 100, 1) if total > 0 else 0
        results.append({
            "tier":        tier,
            "tier_short":  tier.split(" ")[0],
            "position":    pos,
            "total_picks": total,
            "hits":        int(hits),
            "hit_rate":    rate,
        })

df_results = pd.DataFrame(results)

# ── Overall hit rate by tier ──────────────────────────────────────────────────

overall = []
for tier in TIER_ORDER:
    tier_df = draft[draft["tier"] == tier]
    total   = len(tier_df)
    hits    = tier_df["hit"].sum()
    rate    = round(hits / total * 100, 1) if total > 0 else 0
    overall.append({
        "tier":        tier,
        "tier_short":  tier.split(" ")[0],
        "total_picks": total,
        "hits":        int(hits),
        "hit_rate":    rate,
    })

df_overall = pd.DataFrame(overall)

# ── Hit rate by individual round + position concentration ────────────────────
# Position counts come from draft_history_all_positions.csv so K and D/ST
# are included in the total, giving accurate concentration percentages

all_pos = pd.read_csv("draft_history_all_positions.csv")  # K and D/ST included
all_pos = all_pos[all_pos["season"] <= 2024].copy()

by_round = []
for rnd in sorted(draft["round"].unique()):
    rnd_df      = draft[draft["round"] == rnd]
    rnd_all     = all_pos[all_pos["round"] == rnd]
    total_all   = len(rnd_all)
    skill_total = len(rnd_df)
    hits        = rnd_df["hit"].sum()
    rate        = round(hits / skill_total * 100, 1) if skill_total > 0 else 0

    pos_counts = rnd_all["position"].value_counts()
    by_round.append({
        "round":       int(rnd),
        "tier":        round_tier_short(rnd),
        "total_picks": skill_total,
        "hits":        int(hits),
        "hit_rate":    rate,
        "rb":          int(pos_counts.get("RB",  0)),
        "wr":          int(pos_counts.get("WR",  0)),
        "qb":          int(pos_counts.get("QB",  0)),
        "te":          int(pos_counts.get("TE",  0)),
        "k":           int(pos_counts.get("K",   0)),
        "dst":         int(pos_counts.get("D/ST",0)),
        "total_all":   total_all,
    })

df_by_round = pd.DataFrame(by_round)

# ── Late-round steals — ranked by pts above position average ─────────────────
# Min 4 games played, round 8+, must be a hit
# Sorted by pts_above_avg so position doesn't bias the ranking

MIN_GAMES = 8

late_hits = draft[
    (draft["round"] >= 8) &
    (draft["games_played"] >= MIN_GAMES)
].copy()

late_hits = late_hits.sort_values("pts_above_avg", ascending=False)

top_steals = late_hits[[
    "season", "round", "draft_slot", "player_name",
    "position", "ppr_per_game", "pts_above_avg", "games_played", "manager"
]].head(10).reset_index(drop=True)

top_steals.index += 1  # rank starts at 1

# ── Print results ─────────────────────────────────────────────────────────────

print("=== Overall Hit Rate by Tier ===")
print(df_overall.to_string(index=False))

print("\n=== Hit Rate by Tier × Position ===")
print(df_results.to_string(index=False))

print("\n=== Position Concentration by Round ===")
print(df_by_round[["round","tier","total_all","rb","wr","qb","te","k","dst"]].to_string(index=False))

print("\n=== Hit Rate by Individual Round ===")
print(df_by_round.to_string(index=False))

print("\n=== Top 10 Late-Round Steals (Round 8+, ranked by pts above position avg) ===")
print(top_steals.to_string())

# ── Export JSON ───────────────────────────────────────────────────────────────

by_round_json = df_by_round.to_dict(orient="records")

tier_pos_json = {}
for pos in ["RB", "WR", "QB", "TE"]:
    tier_pos_json[pos] = df_results[df_results["position"] == pos]["hit_rate"].tolist()

overall_json = df_overall[["tier_short", "hit_rate", "total_picks", "hits"]].to_dict(orient="records")

steals_json = []
for rank, row in top_steals.iterrows():
    steals_json.append({
        "rank":         rank,
        "player":       row["player_name"],
        "pos":          row["position"],
        "round":        int(row["round"]),
        "slot":         int(row["draft_slot"]),
        "season":       int(row["season"]),
        "ppg":          float(row["ppr_per_game"]),
        "pts_above_avg": float(row["pts_above_avg"]),
        "games":        int(row["games_played"]),
        "manager":      row["manager"],
    })

output = {
    "by_round":       by_round_json,
    "tier_pos":       tier_pos_json,
    "overall":        overall_json,
    "top_steals":     steals_json,
    "tiers":          TIER_SHORT,
    "hit_thresholds": HIT_THRESHOLDS,
}

with open("hit_rate_data.json", "w") as f:
    json.dump(output, f, indent=2)

print("\n=== Done ===")
print("hit_rate_data.json written")

# ── Per-season steals for season filter feature ───────────────────────────────

season_steals = {}
for season in sorted(draft["season"].unique()):
    # Top 10 by pts_above_avg regardless of hit threshold
    # Only require 8+ games so injured players don't inflate the list
    s_df = draft[
        (draft["season"] == season) &
        (draft["round"] >= 8) &
        (draft["games_played"] >= MIN_GAMES)
    ].copy().sort_values("pts_above_avg", ascending=False).head(10).reset_index(drop=True)
    s_df.index += 1

    season_steals[int(season)] = []
    for rank, row in s_df.iterrows():
        season_steals[int(season)].append({
            "rank":          rank,
            "player":        row["player_name"],
            "pos":           row["position"],
            "round":         int(row["round"]),
            "slot":          int(row["draft_slot"]),
            "season":        int(row["season"]),
            "ppg":           float(row["ppr_per_game"]),
            "pts_above_avg": float(row["pts_above_avg"]),
            "games":         int(row["games_played"]),
            "manager":       row["manager"],
        })

print("\n=== Per-Season Steals ===")
for season, steals in season_steals.items():
    print(f"\n{season}:")
    for s in steals:
        print(f"  {s['rank']}. {s['player']} ({s['pos']}) Rd{s['round']} +{s['pts_above_avg']} - {s['manager']}")

# Update JSON output with season steals
import json
with open("hit_rate_data.json") as f:
    existing = json.load(f)

existing["season_steals"] = season_steals

with open("hit_rate_data.json", "w") as f:
    json.dump(existing, f, indent=2)

print("\nseason_steals added to hit_rate_data.json")
