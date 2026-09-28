import pandas as pd
from thefuzz import process

# =============================================================================
# Preach Fantasy — Player Name Matcher (ESPN Full Names)
# Joins draft_history.csv with espn_player_stats_season.csv
# Both sources use full player names so matching is much cleaner
# =============================================================================
# Outputs:
#   draft_with_stats.csv   — master analysis table
#   match_review.csv       — all matches for review
# =============================================================================

draft  = pd.read_csv("draft_history.csv")
stats  = pd.read_csv("espn_player_stats_season.csv")

print(f"Draft picks loaded:  {len(draft)}")
print(f"Stats rows loaded:   {len(stats)}")

# ── Manual overrides ──────────────────────────────────────────────────────────
# Only needed for genuine name mismatches or players with no ESPN stats
# Format: ("Draft name", season, position): "ESPN stats name" or None for zero stats

MANUAL_OVERRIDES = {
    # Players who did not play / were inactive
    ("Bryce Love",          2020, "RB"):  None,
    ("Ryquell Armstead",    2020, "RB"):  None,
    ("Lynn Bowden Jr.",     2020, "RB"):  None,
    ("Tarik Cohen",         2021, "RB"):  None,
    ("Deshaun Watson",      2021, "QB"):  None,
    ("Tyrell Williams",     2021, "WR"):  None,
    ("Odell Beckham Jr.",   2022, "WR"):  None,
    ("Duke Johnson",        2020, "RB"):  None,
    ("Darrel Williams",     2020, "RB"):  None,
    ("Chase Claypool",      2023, "WR"):  None,
    ("Allen Robinson II",   2023, "WR"):  None,
    ("Javonte Williams",    2023, "RB"):  None,
    ("Michael Wilson",      2024, "WR"):  None,
}

ZERO_STATS = {
    "games_played": 0,
    "total_ppr":    0.0,
    "ppr_per_game": 0.0,
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def get_candidates(season, position):
    subset = stats[
        (stats["season"] == season) &
        (stats["position"] == position)
    ]
    return subset["player_name"].tolist()

def get_stats_row(season, position, name):
    rows = stats[
        (stats["season"] == season) &
        (stats["position"] == position) &
        (stats["player_name"] == name)
    ]
    return rows.iloc[0] if len(rows) > 0 else None

SCORE_THRESHOLD = 80  # higher threshold since we now have full names

# ── Match each draft pick ─────────────────────────────────────────────────────

results = []

for _, row in draft.iterrows():
    season     = row["season"]
    position   = row["position"]
    draft_name = row["player_name"]

    if position not in ("RB", "WR", "TE", "QB"):
        continue

    override_key = (draft_name, season, position)

    # Manual override
    if override_key in MANUAL_OVERRIDES:
        stats_name = MANUAL_OVERRIDES[override_key]
        if stats_name is None:
            results.append({**row.to_dict(), "matched_name": draft_name,
                             "match_score": 100, "match_status": "manual_zero",
                             **ZERO_STATS})
        else:
            sr = get_stats_row(season, position, stats_name)
            if sr is not None:
                results.append({**row.to_dict(), "matched_name": stats_name,
                                 "match_score": 100, "match_status": "manual_match",
                                 "games_played": sr["games_played"],
                                 "total_ppr":    sr["total_ppr"],
                                 "ppr_per_game": sr["ppr_per_game"]})
            else:
                results.append({**row.to_dict(), "matched_name": stats_name,
                                 "match_score": 100, "match_status": "manual_zero",
                                 **ZERO_STATS})
        continue

    # Exact match first
    sr = get_stats_row(season, position, draft_name)
    if sr is not None:
        results.append({**row.to_dict(), "matched_name": draft_name,
                         "match_score": 100, "match_status": "exact",
                         "games_played": sr["games_played"],
                         "total_ppr":    sr["total_ppr"],
                         "ppr_per_game": sr["ppr_per_game"]})
        continue

    # Fuzzy match fallback
    candidates = get_candidates(season, position)

    if not candidates:
        results.append({**row.to_dict(), "matched_name": draft_name,
                         "match_score": 0, "match_status": "no_stats",
                         **ZERO_STATS})
        continue

    match, score = process.extractOne(draft_name, candidates)

    if score >= SCORE_THRESHOLD:
        sr = get_stats_row(season, position, match)
        results.append({**row.to_dict(), "matched_name": match,
                         "match_score": score, "match_status": "fuzzy",
                         "games_played": sr["games_played"],
                         "total_ppr":    sr["total_ppr"],
                         "ppr_per_game": sr["ppr_per_game"]})
    else:
        results.append({**row.to_dict(), "matched_name": match,
                         "match_score": score, "match_status": "below_threshold",
                         **ZERO_STATS})

df_results = pd.DataFrame(results)

# ── Summary ───────────────────────────────────────────────────────────────────

status_counts = df_results["match_status"].value_counts()
print(f"\n--- Match summary ---")
for status, count in status_counts.items():
    print(f"  {status:<20} {count:>4}  ({count/len(df_results)*100:.1f}%)")

# ── Below threshold ───────────────────────────────────────────────────────────

below = df_results[df_results["match_status"] == "below_threshold"]
print(f"\n--- Below threshold (need manual review) ---")
if len(below) > 0:
    print(
        below[["season", "round", "player_name", "position",
                "manager", "matched_name", "match_score"]]
        .sort_values("match_score")
        .to_string(index=False)
    )
else:
    print("None")

# ── No stats breakdown ────────────────────────────────────────────────────────

no_stats = df_results[df_results["match_status"] == "no_stats"]
print(f"\n--- Zero-stat picks by season ---")
if len(no_stats) > 0:
    print(no_stats.groupby("season").size().to_string())
else:
    print("None")

# ── Spot check ────────────────────────────────────────────────────────────────

print("\n--- Sample matched picks (spot check) ---")
matched = df_results[df_results["match_status"].isin(["exact", "fuzzy", "manual_match"])]
print(
    matched[["season", "round", "player_name", "matched_name",
             "match_score", "ppr_per_game", "manager"]]
    .sample(min(15, len(matched)), random_state=42)
    .sort_values(["season", "round"])
    .to_string(index=False)
)

# ── Save ──────────────────────────────────────────────────────────────────────

df_results.to_csv("draft_with_stats.csv", index=False)
df_results.to_csv("match_review.csv", index=False)

print(f"\n=== Done ===")
print(f"draft_with_stats.csv — {len(df_results)} total picks")
print(f"  exact matches:   {len(df_results[df_results['match_status'] == 'exact'])}")
print(f"  fuzzy matches:   {len(df_results[df_results['match_status'] == 'fuzzy'])}")
print(f"  manual zero:     {len(df_results[df_results['match_status'] == 'manual_zero'])}")
print(f"  no stats:        {len(df_results[df_results['match_status'] == 'no_stats'])}")
print(f"  below threshold: {len(df_results[df_results['match_status'] == 'below_threshold'])}")
