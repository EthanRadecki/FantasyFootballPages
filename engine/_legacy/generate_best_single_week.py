"""
generate_best_single_week.py

Produces data/best_single_week.json for managers.html's "Best Single-Week
Performances" section: per manager, every real starting-lineup week a
player put up, ranked by points, capped to a generous top-N.

VALID-WEEK / NO-CONSOLATION LOGIC (verified against the real data, not
assumed):
  - weekly_rosters_clean.csv's Week column is a plain 1-17 week number.
  - matchup_data.csv's Week column is a label: "Week N" for the regular
    season, or "Playoff Round N" for the bracket. Regular season length
    varies by season (13 weeks for 2020/2021, 14 weeks for 2022-2025), so
    "Playoff Round 1" doesn't map to a fixed week number across seasons --
    it's (regular season length for that season) + round number.
  - Consolation-bracket games exist ONLY as Is_Playoff=='No' rows during
    what would otherwise look like playoff weeks (teams eliminated from
    the real bracket still play each other). Those are excluded here by
    only whitelisting (Team, Season, real playoff week) triples that
    actually appear with Is_Playoff=='Yes' in matchup_data.csv -- so an
    eliminated team's garbage-time weeks never make it into this file,
    even though they share a week number with teams still alive.

Run this, review the printed verification counts, then drop the output
into data/ before wiring it up.
"""

import pandas as pd
import json

ROSTERS_CSV = "weekly_rosters_clean.csv"
MATCHUP_CSV = "matchup_data.csv"
OUTPUT_PATH = "data/best_single_week.json"

TOP_N_PER_GROUP = 25  # per manager+position+season; generous for single-starter
                       # positions (K, D/ST -- effectively "keep everything"
                       # since a season only has ~17 weeks) and still plenty
                       # of depth for multi-starter positions (RB, WR) once
                       # sliced down to a specific season or position.

EXCLUDED_MANAGERS = {"Thomas Sullivan", "William Serafin"}


def main():
    rosters = pd.read_csv(ROSTERS_CSV)
    matchups = pd.read_csv(MATCHUP_CSV)

    rosters = rosters[~rosters["Manager"].isin(EXCLUDED_MANAGERS)]
    before = len(rosters)

    # Regular season length per season, derived from the data (13 for
    # 2020/2021, 14 for 2022-2025) rather than hardcoded.
    is_reg = matchups["Week"].astype(str).str.startswith("Week ")
    reg_len_by_season = (
        matchups.loc[is_reg]
        .assign(WeekNum=lambda d: d["Week"].str.replace("Week ", "", regex=False).astype(int))
        .groupby("Season_Year")["WeekNum"]
        .max()
        .to_dict()
    )

    # Regular-season whitelist: every team, every real regular season week.
    reg_whitelist = set()
    for season, reg_len in reg_len_by_season.items():
        teams = matchups.loc[matchups["Season_Year"] == season, "Team_Name"].unique()
        for team in teams:
            for wk in range(1, reg_len + 1):
                reg_whitelist.add((team, season, wk))

    # Real bracket whitelist: only rows where Is_Playoff == 'Yes', mapped
    # from "Playoff Round N" to an actual week number using that season's
    # regular season length. This is what excludes consolation games --
    # a team playing a consolation game the same week has Is_Playoff=='No'
    # and never enters this set.
    is_po = matchups["Week"].astype(str).str.startswith("Playoff Round") & (
        matchups["Is_Playoff"] == "Yes"
    )
    po_rows = matchups.loc[is_po].copy()
    po_rows["RoundNum"] = po_rows["Week"].str.replace("Playoff Round ", "", regex=False).astype(int)
    po_rows["RealWeek"] = po_rows.apply(
        lambda r: reg_len_by_season[r["Season_Year"]] + r["RoundNum"], axis=1
    )
    po_whitelist = set(zip(po_rows["Team_Name"], po_rows["Season_Year"], po_rows["RealWeek"]))

    valid_whitelist = reg_whitelist | po_whitelist

    def is_valid(row):
        return (row["Manager"], row["Season"], int(row["Week"])) in valid_whitelist

    rosters = rosters[rosters.apply(is_valid, axis=1)]
    print(f"Valid-week filter (no consolation): {before} -> {len(rosters)} roster rows")

    # "Real game" filter: starting lineup only, matching the Franchise
    # Leaders convention used elsewhere on the site.
    real = rosters[(rosters["Started"] == True) & (rosters["Slot"] != "IR")].copy()
    print(f"Started + not IR filter: {len(rosters)} -> {len(real)} roster rows")

    out = {}
    for manager, mgr_grp in real.groupby("Manager"):
        rows = []
        for (position, season), grp in mgr_grp.groupby(["Position", "Season"]):
            top = grp.sort_values("Points", ascending=False).head(TOP_N_PER_GROUP)
            rows.extend(
                {
                    "player": r["Player"],
                    "position": r["Position"],
                    "season": int(r["Season"]),
                    "week": int(r["Week"]),
                    "points": round(float(r["Points"]), 1),
                }
                for _, r in top.iterrows()
            )
        rows.sort(key=lambda r: r["points"], reverse=True)
        out[manager] = rows

    with open(OUTPUT_PATH, "w") as f:
        json.dump(out, f, separators=(",", ":"))

    print(f"Wrote {OUTPUT_PATH}: {len(out)} managers")
    for manager, rows in sorted(out.items()):
        print(f"  {manager}: top = {rows[0]}")


if __name__ == "__main__":
    main()
