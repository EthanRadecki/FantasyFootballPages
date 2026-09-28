import pandas as pd
import numpy as np
import json

# =============================================================================
# surplus_value_index.py  (v2 -- position-relative surplus with round weighting)
#
# Methodology:
#   1. Starter baseline per position per season (top 14 QB/TE, top 28 RB/WR)
#   2. Position-relative value (PRV) = player PPG minus starter baseline
#   3. Expected PRV = avg PRV of all skill position players within +-3 picks
#      across all seasons, regardless of position (cross-position opportunity cost)
#   4. Surplus = actual PRV minus expected PRV
#   5. Picks with <8 games = 0 surplus (injury neutral)
#   6. Round weights applied to weighted avg surplus:
#      Rounds 1-3:  1.00 (full weight -- most important decisions)
#      Rounds 4-7:  0.85 (still meaningful, real opportunity cost)
#      Rounds 8-12: 0.70 (hit rate drops but skill still separates)
#      Rounds 13+:  0.55 (lottery tickets, late finds still rewarded)
# =============================================================================

EXCLUDE      = {"Thomas Sullivan", "William Serafin"}
SKILL        = {"RB", "WR", "QB", "TE"}
SEASONS      = [2020, 2021, 2022, 2023, 2024, 2025]
MIN_GAMES    = 8
STARTER_RANK = {"QB": 14, "TE": 14, "RB": 28, "WR": 28}

ROUND_WEIGHTS = {
    (1,  3):  1.00,
    (4,  7):  0.85,
    (8,  12): 0.70,
    (13, 99): 0.55,
}

def get_weight(rd):
    for (lo, hi), w in ROUND_WEIGHTS.items():
        if lo <= rd <= hi:
            return w
    return 0.55

draft       = pd.read_csv("draft_history_all_positions.csv")
espn        = pd.read_csv("espn_player_stats_season.csv")
surplus_old = pd.read_csv("draft_surplus.csv")

draft = draft[draft["position"].isin(SKILL)].copy()
draft = draft[~draft["manager"].isin(EXCLUDE)].copy()

# ── Step 1: Starter baseline per position per season ─────────────────────────
baselines = {}
for season in SEASONS:
    s_espn = espn[espn["season"] == season].copy()
    for pos in SKILL:
        n   = STARTER_RANK[pos]
        top = (s_espn[s_espn["position"] == pos]
               .nlargest(n, "ppr_per_game")["ppr_per_game"]
               .mean())
        baselines[(season, pos)] = round(top, 4)

print("=== Starter Baselines ===")
for pos in ["QB","RB","WR","TE"]:
    print(f"\n{pos} (top {STARTER_RANK[pos]}):")
    for season in SEASONS:
        print(f"  {season}: {baselines[(season,pos)]:.2f}")

# ── Step 2: PRV for every drafted skill player ────────────────────────────────
espn_skill = espn[espn["position"].isin(SKILL)].copy()

merged = draft.merge(
    espn_skill[["player_name","season","position","ppr_per_game","games_played"]],
    on=["player_name","season","position"],
    how="left"
)
merged = merged.merge(
    surplus_old[["player_name","season","position","manager","overall_pick","injury_zeroed"]],
    on=["player_name","season","position","manager","overall_pick"],
    how="left"
)
merged["injury_zeroed"] = merged["injury_zeroed"].fillna(0).astype(int)
merged["games_played"]  = merged["games_played"].fillna(0)
merged["ppr_per_game"]  = merged["ppr_per_game"].fillna(0)

def compute_prv(row):
    if row["games_played"] < MIN_GAMES or row["injury_zeroed"] == 1:
        return None
    baseline = baselines.get((row["season"], row["position"]), 0)
    return round(row["ppr_per_game"] - baseline, 4)

merged["prv"] = merged.apply(compute_prv, axis=1)

print(f"\nMerged picks: {len(merged)}")
print(f"PRV computed: {merged['prv'].notna().sum()}")
print(f"Injury/short-season zeroed: {merged['prv'].isna().sum()}")

# ── Step 3: Expected PRV per slot (+-3 picks, cross-position) ────────────────
def get_expected_prv(overall_pick, season, manager):
    window = merged[
        (merged["overall_pick"] >= overall_pick - 3) &
        (merged["overall_pick"] <= overall_pick + 3) &
        (merged["prv"].notna())
    ]
    window = window[~((window["overall_pick"] == overall_pick) &
                      (window["season"] == season) &
                      (window["manager"] == manager))]
    if len(window) == 0:
        return None, 0
    return round(window["prv"].mean(), 4), len(window)

print("\nComputing expected PRV per pick...")
expected_prvs, n_comps_list = [], []
for _, row in merged.iterrows():
    ep, nc = get_expected_prv(row["overall_pick"], row["season"], row["manager"])
    expected_prvs.append(ep)
    n_comps_list.append(nc)

merged["expected_prv"] = expected_prvs
merged["n_comps"]      = n_comps_list

# ── Step 4: Surplus and round weighting ──────────────────────────────────────
def compute_surplus(row):
    if pd.isna(row["prv"]) or row["prv"] is None:
        return 0.0
    if pd.isna(row["expected_prv"]) or row["expected_prv"] is None:
        return 0.0
    return round(row["prv"] - row["expected_prv"], 4)

merged["surplus"]       = merged.apply(compute_surplus, axis=1)
merged["actual_prv"]    = merged["prv"].fillna(0)
merged["expected_prv"]  = merged["expected_prv"].fillna(0)
merged["injury_zeroed"] = merged["prv"].isna().astype(int)
merged["weight"]        = merged["round"].apply(get_weight)
merged["surplus_wtd"]   = merged["surplus"] * merged["weight"]

# ── Career rankings ───────────────────────────────────────────────────────────
career = (merged.groupby("manager")
          .apply(lambda g: pd.Series({
              "weighted_total": g["surplus_wtd"].sum(),
              "total_weight":   g["weight"].sum(),
              "total_picks":    len(g),
              "seasons":        g["season"].nunique(),
          }), include_groups=False)
          .reset_index())

career["avg_surplus_wtd"] = (career["weighted_total"] / career["total_weight"]).round(4)
career = career[~career["manager"].isin(EXCLUDE)]
career = career.sort_values("avg_surplus_wtd", ascending=False).reset_index(drop=True)
career.index += 1

print("\n=== Career Draft Rankings (weighted avg surplus per pick) ===")
print(career[["manager","avg_surplus_wtd","weighted_total","total_picks","seasons"]].to_string())

# ── Season grades ─────────────────────────────────────────────────────────────
season_grades = (merged.groupby(["season","manager"])
                 .apply(lambda g: pd.Series({
                     "draft_grade": round(g["surplus_wtd"].sum(), 2),
                     "picks":       len(g),
                 }), include_groups=False)
                 .reset_index())

season_grades["season_rank"] = (season_grades.groupby("season")["draft_grade"]
                                 .rank(ascending=False).astype(int))
season_display = season_grades[~season_grades["manager"].isin(EXCLUDE)].copy()

pivot = season_display.pivot(index="manager", columns="season", values="draft_grade")
print("\n=== Season Draft Grades (weighted total surplus) ===")
print(pivot.round(1).to_string())

# ── Top surpluses and busts ───────────────────────────────────────────────────
top = merged[merged["actual_prv"] != 0].nlargest(15, "surplus")
print("\n=== Top 15 Individual Pick Surpluses (raw) ===")
print(top[["season","round","overall_pick","player_name","position",
           "actual_prv","expected_prv","surplus","manager"]].to_string(index=False))

busts = merged[(merged["round"] <= 7) & (merged["actual_prv"] != 0)].nsmallest(15, "surplus")
print("\n=== Top 15 Biggest Busts (Rounds 1-7, raw) ===")
print(busts[["season","round","overall_pick","player_name","position",
             "actual_prv","expected_prv","surplus","manager"]].to_string(index=False))

# ── Per-season best and worst ─────────────────────────────────────────────────
print("\n=== Per-Season Best Picks (top 10, all rounds, raw surplus) ===")
for season in SEASONS:
    s = merged[(merged["season"] == season) & (merged["actual_prv"] != 0)]
    best = s.nlargest(10, "surplus")
    print(f"\n{season}:")
    for _, r in best.iterrows():
        print(f"  Rd{int(r['round'])} Pk{int(r['overall_pick'])} {r['player_name']} ({r['position']}) "
              f"PRV:{r['actual_prv']:+.2f} exp:{r['expected_prv']:+.2f} surplus:{r['surplus']:+.2f} -- {r['manager']}")

print("\n=== Per-Season Worst Picks (rounds 1-7, raw surplus) ===")
for season in SEASONS:
    s = merged[(merged["season"] == season) & (merged["round"] <= 7) & (merged["actual_prv"] != 0)]
    worst = s.nsmallest(5, "surplus")
    print(f"\n{season}:")
    for _, r in worst.iterrows():
        print(f"  Rd{int(r['round'])} Pk{int(r['overall_pick'])} {r['player_name']} ({r['position']}) "
              f"PRV:{r['actual_prv']:+.2f} exp:{r['expected_prv']:+.2f} surplus:{r['surplus']:+.2f} -- {r['manager']}")

# ── JSON output ───────────────────────────────────────────────────────────────
career_json = []
for rank, row in career.iterrows():
    career_json.append({
        "rank":          int(rank),
        "manager":       row["manager"],
        "avg_surplus":   float(row["avg_surplus_wtd"]),
        "weighted_total": float(round(row["weighted_total"], 2)),
        "total_picks":   int(row["total_picks"]),
        "seasons":       int(row["seasons"]),
    })

season_json = season_display[["season","manager","draft_grade","season_rank"]].to_dict(orient="records")

output = {
    "career_grades": career_json,
    "season_grades": season_json,
}

with open("surplus_value_data.json", "w") as f:
    json.dump(output, f, indent=2)

merged.to_csv("draft_surplus_v2.csv", index=False)

print("\n=== Done ===")
print("surplus_value_data.json written")
print("draft_surplus_v2.csv written")
