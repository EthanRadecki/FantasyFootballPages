import pandas as pd
import numpy as np
import json

# =============================================================================
# surplus_value_index_2026_live.py  (v2 -- cross-season comparison pool)
#
# Grades ONLY the 2026 picks. Still a separate pipeline from
# surplus_value_index.py -- doesn't touch or recompute the career/all-seasons
# index, which stays frozen until end of season.
#
# What changed from v1: the "expected PRV" comparison window (+-3 overall
# picks) now pools from EVERY season 2020-2026, not just 2026 alone. A
# single 224-pick draft class was too thin for a reliable +-3 window (many
# picks had 0-2 comps); pooling six extra seasons' worth of picks (~1033
# valid historical PRVs) fixes that. Each 2026 pick is still only compared
# on equal footing -- PRV values are already season-relative (each season's
# own starter baseline was subtracted out), so pooling across seasons is
# valid the same way the original career pipeline pools across seasons for
# its own comps.
#
# The 8-game floor still applies to the 2020-2025 half of the pool (pulled
# directly from your validated draft_surplus_v2.csv, injury_zeroed rows
# excluded) -- it's ONLY dropped for computing 2026 PRV itself, since this
# season doesn't have 8 games on the board yet. Revisit that once it does.
#
# Methodology (matches the career pipeline):
#   1. Starter baseline per position: 2026-to-date (top 14 QB/TE, top 28
#      RB/WR by current ppr_per_game) -- used only to compute 2026 PRV.
#   2. 2026 PRV = 2026-to-date PPG minus that baseline. No games floor:
#      any player with >=1 game counts.
#   3. Expected PRV = avg PRV of all skill picks (any season 2020-2026)
#      drafted within +-3 overall picks, cross-position, excluding the
#      pick itself.
#   4. Surplus = 2026 PRV minus expected PRV.
#   5. Round weights (same tiers as the career pipeline):
#      Rounds 1-3: 1.00 / 4-7: 0.85 / 8-12: 0.70 / 13+: 0.55
#
# Inputs:
#   - draft_history_all_positions.csv  (needs season=2026 draft results)
#   - espn_player_stats_season.csv     (needs season=2026 to-date rows)
#   - draft_surplus_v2.csv             (2020-2025 output from
#                                        surplus_value_index.py -- supplies
#                                        the historical half of the
#                                        comparison pool via actual_prv)
#
# Outputs:
#   - surplus_value_2026_live.csv   (row-level, one line per 2026 pick)
#   - surplus_value_2026_live.json  (per-manager grade + per-pick breakdown)
# =============================================================================

EXCLUDE      = {"Thomas Sullivan", "William Serafin"}
SKILL        = {"RB", "WR", "QB", "TE"}
SEASON       = 2026
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

draft   = pd.read_csv("GitHubRepoData/draft_history_all_positions.csv")
espn    = pd.read_csv("espn_player_stats_season.csv")
history = pd.read_csv("GitHubRepoData/draft_surplus_v2.csv")  # 2020-2025, validated actual_prv

draft = draft[draft["season"] == SEASON].copy()
if draft.empty:
    raise SystemExit(f"No season={SEASON} rows in draft_history_all_positions.csv.")
draft = draft[draft["position"].isin(SKILL)].copy()
draft = draft[~draft["manager"].isin(EXCLUDE)].copy()

espn_season = espn[espn["season"] == SEASON].copy()
if espn_season.empty:
    raise SystemExit(f"No season={SEASON} rows in espn_player_stats_season.csv.")
espn_skill = espn_season[espn_season["position"].isin(SKILL)].copy()

# ── Step 1: 2026-to-date starter baseline per position ───────────────────────
baselines = {}
for pos in SKILL:
    n = STARTER_RANK[pos]
    top = (espn_skill[espn_skill["position"] == pos]
           .nlargest(n, "ppr_per_game")["ppr_per_game"]
           .mean())
    baselines[pos] = round(top, 4)

print("=== Starter Baselines (2026-to-date) ===")
for pos in ["QB", "RB", "WR", "TE"]:
    print(f"  {pos} (top {STARTER_RANK[pos]}): {baselines[pos]:.2f}")

# ── Step 2: PRV for every 2026 drafted skill player, NO games floor ──────────
merged = draft.merge(
    espn_skill[["player_name", "position", "ppr_per_game", "games_played"]],
    on=["player_name", "position"],
    how="left"
)
merged["games_played"] = merged["games_played"].fillna(0)
merged["ppr_per_game"]  = merged["ppr_per_game"].fillna(0)

def compute_prv_2026(row):
    if row["games_played"] < 1:
        return None
    baseline = baselines.get(row["position"], 0)
    return round(row["ppr_per_game"] - baseline, 4)

merged["prv"] = merged.apply(compute_prv_2026, axis=1)

print(f"\n2026 drafted skill picks: {len(merged)}")
print(f"PRV computed (played >=1 game): {merged['prv'].notna().sum()}")
print(f"No games yet: {merged['prv'].isna().sum()}")

# ── Step 3: build the cross-season comparison pool (2020-2026) ───────────────
# Historical half: validated actual_prv from draft_surplus_v2.csv, injury_zeroed
# rows excluded (matches the 8-game floor + injury exclusion already applied
# when that file was generated).
hist_pool = history[history["injury_zeroed"] == 0][["season", "overall_pick", "actual_prv"]].copy()
hist_pool = hist_pool.rename(columns={"actual_prv": "prv"})

# 2026 half: this run's no-floor PRVs, valid ones only.
live_pool = merged[merged["prv"].notna()][["overall_pick"]].copy()
live_pool["season"] = SEASON
live_pool["prv"] = merged.loc[merged["prv"].notna(), "prv"].values

comp_pool = pd.concat([hist_pool, live_pool], ignore_index=True)
print(f"\nComparison pool: {len(comp_pool)} valid PRVs across seasons "
      f"{sorted(comp_pool['season'].unique())}")

def get_expected_prv(overall_pick):
    window = comp_pool[
        (comp_pool["overall_pick"] >= overall_pick - 3) &
        (comp_pool["overall_pick"] <= overall_pick + 3) &
        ~((comp_pool["season"] == SEASON) & (comp_pool["overall_pick"] == overall_pick))
    ]
    if len(window) == 0:
        return None, 0
    return round(window["prv"].mean(), 4), len(window)

print("Computing expected PRV per pick (pooled across 2020-2026)...")
expected_prvs, n_comps_list = [], []
for _, row in merged.iterrows():
    ep, nc = get_expected_prv(row["overall_pick"])
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

merged["surplus"]      = merged.apply(compute_surplus, axis=1)
merged["actual_prv"]   = merged["prv"].fillna(0)
merged["expected_prv"] = merged["expected_prv"].fillna(0)
merged["no_data_yet"]  = merged["prv"].isna().astype(int)
merged["weight"]       = merged["round"].apply(get_weight)
merged["surplus_wtd"]  = merged["surplus"] * merged["weight"]

zero_comp = (merged["n_comps"] == 0).sum()
print(f"Picks with zero comps even after pooling: {zero_comp}")

# ── Manager grades (weighted total surplus) ───────────────────────────────────
manager_grades = (merged.groupby("manager")
                   .apply(lambda g: pd.Series({
                       "draft_grade":     round(g["surplus_wtd"].sum(), 2),
                       "avg_surplus_wtd": round(g["surplus_wtd"].sum() / g["weight"].sum(), 4),
                       "total_picks":     len(g),
                       "picks_with_data": int((g["no_data_yet"] == 0).sum()),
                   }), include_groups=False)
                   .reset_index())
manager_grades = manager_grades.sort_values("draft_grade", ascending=False).reset_index(drop=True)
manager_grades["rank"] = manager_grades.index + 1

print("\n=== 2026 Live Draft Grades (weighted total surplus, cross-season pool) ===")
print(manager_grades[["rank", "manager", "draft_grade", "total_picks", "picks_with_data"]].to_string(index=False))

# ── CSV output ────────────────────────────────────────────────────────────────
merged.to_csv("surplus_value_2026_live.csv", index=False)

# ── JSON output, shaped for the week JSON's draft_grade / draft_picks fields ─
managers_json = {}
for _, row in manager_grades.iterrows():
    mgr = row["manager"]
    picks = merged[merged["manager"] == mgr].sort_values("overall_pick")
    managers_json[mgr] = {
        "draft_grade": float(row["draft_grade"]),
        "draft_surplus_total": float(row["draft_grade"]),
        "rank": int(row["rank"]),
        "picks_with_data": int(row["picks_with_data"]),
        "total_picks": int(row["total_picks"]),
        "picks": [
            {
                "player": r["player_name"],
                "pos": r["position"],
                "round": int(r["round"]),
                "overall_pick": int(r["overall_pick"]),
                "surplus_value": float(r["surplus"]),
                "actual_prv": float(r["actual_prv"]),
                "expected_prv": float(r["expected_prv"]),
                "n_comps": int(r["n_comps"]),
                "no_data_yet": bool(r["no_data_yet"]),
            }
            for _, r in picks.iterrows()
        ],
    }

with open("surplus_value_2026_live.json", "w") as f:
    json.dump(managers_json, f, indent=2)

print("\nSaved surplus_value_2026_live.csv")
print("Saved surplus_value_2026_live.json")
