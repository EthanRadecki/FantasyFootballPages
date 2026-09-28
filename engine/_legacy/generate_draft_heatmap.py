import pandas as pd
import numpy as np
import json

# =============================================================================
# generate_draft_heatmap.py
# Computes per-manager surplus by round x draft_slot for the board heatmap
# Output: draft_heatmap.json
# =============================================================================

EXCLUDE = {"Thomas Sullivan", "William Serafin"}
SKILL   = {"RB", "WR", "QB", "TE"}

df = pd.read_csv("draft_surplus_v2.csv")
df = df[~df["manager"].isin(EXCLUDE)]
df = df[df["position"].isin(SKILL)].copy()

managers = sorted(df["manager"].unique())
rounds   = list(range(1, 17))
slots    = list(range(1, 15))

output = {}

for mgr in managers:
    m = df[df["manager"] == mgr]
    board = {}

    for rd in rounds:
        for slot in slots:
            cell = m[(m["round"] == rd) & (m["draft_slot"] == slot)]
            if len(cell) == 0:
                continue

            picks = []
            for _, row in cell.iterrows():
                picks.append({
                    "season":   int(row["season"]),
                    "player":   row["player_name"],
                    "pos":      row["position"],
                    "surplus":  round(float(row["surplus"]), 2),
                    "prv":      round(float(row["actual_prv"]), 2),
                    "exp_prv":  round(float(row["expected_prv"]), 2),
                    "games":    int(row["games_played"]),
                    "zeroed":   int(row["injury_zeroed"]),
                })

            # Cell summary
            surpluses    = [p["surplus"] for p in picks]
            avg_surplus  = round(np.mean(surpluses), 3)
            n_seasons    = len(picks)

            key = f"{rd}_{slot}"
            board[key] = {
                "round":       rd,
                "slot":        slot,
                "avg_surplus": avg_surplus,
                "n_seasons":   n_seasons,
                "picks":       picks,
            }

    # Career summary stats for context
    total_picks  = len(m)
    avg_surplus  = round(float(m["surplus"].mean()), 4)
    wtd_avg      = round(float((m["surplus_wtd"].sum() / m["weight"].sum())), 4)

    # Tier breakdown
    tiers = {}
    for label, lo, hi in [("early",1,3),("middle",4,7),("midlate",8,12),("late",13,16)]:
        t = m[(m["round"] >= lo) & (m["round"] <= hi)]
        league_t = df[(df["round"] >= lo) & (df["round"] <= hi)]
        tiers[label] = {
            "mgr_avg":    round(float(t["surplus"].mean()), 3) if len(t) > 0 else 0,
            "league_avg": round(float(league_t["surplus"].mean()), 3),
            "n_picks":    int(len(t)),
        }

    # Positional breakdown
    pos_stats = {}
    for pos in ["RB","WR","QB","TE"]:
        mp = m[m["position"] == pos]
        lp = df[df["position"] == pos]
        pos_stats[pos] = {
            "mgr_avg":    round(float(mp["surplus"].mean()), 3) if len(mp) > 0 else 0,
            "league_avg": round(float(lp["surplus"].mean()), 3),
            "n_picks":    int(len(mp)),
            "hit_rate":   round(float((mp["surplus"] > 0).mean()), 3) if len(mp) > 0 else 0,
            "league_hit": round(float((lp["surplus"] > 0).mean()), 3),
        }

    # Best and worst career picks
    scored = m[m["actual_prv"] != 0].copy()
    best3  = scored.nlargest(3, "surplus")
    worst3 = scored[scored["round"] <= 7].nsmallest(3, "surplus")

    def pick_dict(row):
        return {
            "season":  int(row["season"]),
            "round":   int(row["round"]),
            "pick":    int(row["overall_pick"]),
            "player":  row["player_name"],
            "pos":     row["position"],
            "surplus": round(float(row["surplus"]), 2),
            "prv":     round(float(row["actual_prv"]), 2),
        }

    output[mgr] = {
        "board":       board,
        "tiers":       tiers,
        "positions":   pos_stats,
        "best_picks":  [pick_dict(r) for _, r in best3.iterrows()],
        "worst_picks": [pick_dict(r) for _, r in worst3.iterrows()],
        "career_wtd_avg": wtd_avg,
        "total_picks": total_picks,
    }

with open("draft_heatmap.json", "w") as f:
    json.dump(output, f, indent=2)

print(f"draft_heatmap.json written")
print(f"Managers: {len(output)}")
for mgr in managers:
    n_cells = len(output[mgr]["board"])
    print(f"  {mgr}: {n_cells} board cells")
