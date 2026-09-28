"""
=============================================================================
Preach Fantasy — Lineup Efficiency
Compares actual starting lineup points vs. the best possible lineup that
could have been set from the same roster that week.

Handles:
  - 2020's 15-team bye weeks: solved by inner-joining to matchup_data.csv.
    Any manager-week with no real matchup (bye) is dropped automatically.
  - Consolation/loser-bracket weeks: dropped via Is_Playoff == 'Yes' filter
    for playoff weeks, same convention as H2H Matrix / Gauntlet / rivalry
    table fixes.
  - IR-slotted players are EXCLUDED from the optimal lineup pool (per
    Ethan's call — they were flagged unplayable that week, so crediting an
    "optimal" lineup built around them would be unrealistic).

Starting lineup structure (confirmed from actual roster data):
  1 QB, 2 RB, 2 WR, 1 TE, 1 FLEX (RB/WR/TE), 1 D/ST, 1 K
=============================================================================
Input:
  weekly_rosters_clean.csv
  matchup_data.csv
Output:
  lineup_efficiency.csv — one row per manager-week that had a real,
  bracket-eligible matchup.
=============================================================================
"""

import pandas as pd

EXCLUDED_MANAGERS = {'Thomas Sullivan', 'William Serafin'}

# ── Week-label mapping: numeric week -> matchup_data.csv's "Week X" / "Playoff Round X" ──
def week_label(season, week):
    reg_weeks = 13 if season in (2020, 2021) else 14
    if week <= reg_weeks:
        return f"Week {week}"
    playoff_round = week - reg_weeks
    return f"Playoff Round {playoff_round}"

# ── Optimal lineup solver ──
# Single-FLEX greedy is provably optimal here: lock top N for each strict
# position, then the FLEX slot goes to the single best leftover RB/WR/TE.
REQUIRED = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "D/ST": 1, "K": 1}
FLEX_ELIGIBLE = {"RB", "WR", "TE"}

def optimal_points(group):
    pool = group[group["Slot"] != "IR"]

    total = 0.0
    leftovers = []  # (points,) for FLEX-eligible players not used in locked slots

    for pos, n in REQUIRED.items():
        pos_players = pool[pool["Position"] == pos].sort_values("Points", ascending=False)
        locked = pos_players.head(n)
        total += locked["Points"].sum()
        if pos in FLEX_ELIGIBLE:
            leftover = pos_players.iloc[n:]
            leftovers.extend(leftover["Points"].tolist())

    if leftovers:
        total += max(leftovers)

    return total

def actual_points(group):
    return group.loc[group["Started"] == True, "Points"].sum()

def main():
    rosters = pd.read_csv("weekly_rosters_clean.csv")
    match = pd.read_csv("matchup_data.csv", index_col=0)

    rosters = rosters[~rosters["Manager"].isin(EXCLUDED_MANAGERS)].copy()

    rosters["Week_Label"] = rosters.apply(lambda r: week_label(r["Season"], r["Week"]), axis=1)
    rosters["Is_Playoff_Week"] = rosters["Week_Label"].str.startswith("Playoff")

    print("Computing actual vs. optimal points per manager-week...")
    grouped = rosters.groupby(["Season", "Week", "Week_Label", "Manager", "Fantasy_Team"])
    results = grouped.apply(lambda g: pd.Series({
        "Actual_Points": actual_points(g),
        "Optimal_Points": optimal_points(g),
    })).reset_index()

    print(f"  {len(results)} manager-weeks before matchup join")

    # ── Join to matchup_data to attach real opponent/outcome, and to
    #    naturally drop bye weeks (no match = dropped by inner join) ──
    match_slim = match[["Team_Name", "Opponent_Name", "Team_Score", "Opponent_Score",
                         "Outcome", "Week", "Season_Year", "Is_Playoff"]].rename(columns={
        "Team_Name": "Manager", "Week": "Week_Label", "Season_Year": "Season"
    })

    merged = results.merge(match_slim, on=["Manager", "Season", "Week_Label"], how="inner")
    print(f"  {len(merged)} manager-weeks after inner join (bye weeks dropped)")

    # ── Drop consolation/loser-bracket playoff weeks — bracket-only, matching
    #    the convention already used for H2H Matrix / Gauntlet / rivalry table ──
    before_bracket_filter = len(merged)
    merged = merged[(~merged["Week_Label"].str.startswith("Playoff")) | (merged["Is_Playoff"] == "Yes")]
    print(f"  {before_bracket_filter - len(merged)} consolation-bracket weeks dropped")
    print(f"  {len(merged)} manager-weeks in final dataset")

    merged["Efficiency_Gap"] = merged["Optimal_Points"] - merged["Actual_Points"]
    merged["Would_Have_Beaten_Opponent"] = merged["Optimal_Points"] > merged["Opponent_Score"]
    merged["Missed_Win"] = (merged["Outcome"] == "Loss") & (merged["Would_Have_Beaten_Opponent"])

    # ── Known exception: Ben Castaldo, 2024 Week 14, did not set a lineup
    # because he'd already been eliminated from playoff contention. He
    # genuinely would have won with any real lineup set — that's a fair,
    # true "missed win" and stays in. But it's a forfeit, not a bad
    # decision, so it shouldn't count toward lineup-efficiency stats
    # (points left on the bench implies an active, if flawed, choice).
    # Flagged rather than dropped: kept for Missed_Win, excluded from
    # Efficiency_Gap aggregation. The underlying rule has since been
    # banned, so this is a documented one-off flag, not a general filter. ──
    KNOWN_FORFEITS = [
        {"Season": 2024, "Week": 14, "Manager": "Ben Castaldo"},
    ]
    merged["Forfeited_Lineup"] = False
    for f in KNOWN_FORFEITS:
        mask = ((merged["Season"] == f["Season"]) &
                 (merged["Week"] == f["Week"]) &
                 (merged["Manager"] == f["Manager"]))
        merged.loc[mask, "Forfeited_Lineup"] = True
    print(f"  {merged['Forfeited_Lineup'].sum()} known forfeited/no-lineup weeks flagged (kept for Missed_Win, excluded from efficiency stats)")

    merged = merged.sort_values(["Season", "Week", "Manager"]).reset_index(drop=True)
    merged.to_csv("lineup_efficiency.csv", index=False)

    print(f"\nSaved lineup_efficiency.csv — {len(merged)} rows")
    print(f"\nTotal 'missed wins' (lost with actual lineup, would've won with optimal) — includes forfeited weeks:")
    print(merged.groupby("Manager")["Missed_Win"].sum().sort_values(ascending=False).to_string())

    efficiency_only = merged[~merged["Forfeited_Lineup"]]
    print(f"\nAverage efficiency gap (points left on the bench) by manager — excludes forfeited weeks:")
    print(efficiency_only.groupby("Manager")["Efficiency_Gap"].mean().round(2).sort_values(ascending=False).to_string())

if __name__ == "__main__":
    main()
