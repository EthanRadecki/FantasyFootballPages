"""
generate_blunder_rosters.py

Produces data/blunder_rosters.json for lineup-efficiency.html's Biggest
Lineup Blunders modal: for each of the 10 rows already in that table, the
full starting lineup and bench for that manager/season/week.

This intentionally does NOT try to reconstruct which bench swap would have
produced the "optimal" score already shown in the table -- that number
comes from a real solver respecting FLEX eligibility properly, and a
simplified re-derivation here could disagree with it. Showing the real
starters (in slot order) and the real bench (sorted highest points first,
so the "should've started him" player is obvious from position alone)
gets the useful part without that risk.

Run this, verify the printed sums match the BLUNDERS array already in
lineup-efficiency.html (they should, since that table was itself built
from this same file), then drop the output into data/.
"""

import pandas as pd
import json

ROSTERS_CSV = "weekly_rosters_clean.csv"
OUTPUT_PATH = "data/blunder_rosters.json"

# The exact 10 (season, week, manager) combos already in the Biggest
# Lineup Blunders table, in the same order.
BLUNDERS = [
    (2024, 11, "Andrew Root"),
    (2023, 4,  "Deniz Bileydi"),
    (2025, 1,  "Andrew Root"),
    (2024, 15, "Ryan P McQuaid"),
    (2025, 7,  "Max Malich"),
    (2023, 5,  "Anthony Kelly"),
    (2023, 1,  "Anthony Kelly"),
    (2020, 15, "Anthony Kelly"),
    (2022, 2,  "Carmine Pittelli Jr."),
    (2022, 5,  "Carmine Pittelli Jr."),
]

# Real slot order for display: 1 QB, 2 RB, 2 WR, 1 TE, 1 FLEX, 1 D/ST, 1 K.
SLOT_ORDER = {'QB': 0, 'RB': 1, 'WR': 2, 'TE': 3, 'RB/WR/TE': 4, 'D/ST': 5, 'K': 6}


def main():
    rosters = pd.read_csv(ROSTERS_CSV)

    out = []
    for season, week, manager in BLUNDERS:
        sub = rosters[
            (rosters["Season"] == season)
            & (rosters["Week"] == week)
            & (rosters["Manager"] == manager)
        ]

        starters = sub[sub["Started"] == True].copy()
        starters["slot_order"] = starters["Slot"].map(SLOT_ORDER).fillna(9)
        starters = starters.sort_values(["slot_order", "Points"], ascending=[True, False])

        bench = sub[sub["Started"] == False].copy()
        bench = bench.sort_values("Points", ascending=False)

        entry = {
            "season": int(season),
            "week": int(week),
            "manager": manager,
            "starters": [
                {
                    "player": r["Player"],
                    "position": r["Position"],
                    "slot": r["Slot"],
                    "points": round(float(r["Points"]), 1),
                }
                for _, r in starters.iterrows()
            ],
            "bench": [
                {
                    "player": r["Player"],
                    "position": r["Position"],
                    "slot": r["Slot"],
                    "points": round(float(r["Points"]), 1),
                }
                for _, r in bench.iterrows()
            ],
        }
        out.append(entry)

        actual_sum = starters["Points"].sum()
        print(f"{season} wk{week} {manager}: {len(starters)} starters (sum={actual_sum:.2f}), {len(bench)} bench")

    with open(OUTPUT_PATH, "w") as f:
        json.dump(out, f, separators=(",", ":"))

    print(f"\nWrote {OUTPUT_PATH}: {len(out)} entries")


if __name__ == "__main__":
    main()
