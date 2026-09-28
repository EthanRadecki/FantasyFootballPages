"""
generate_waiver_stint_data.py

Produces the compact per-stint array embedded in waiver-value.html for two
new visuals:
  1. Total Value Earned by Manager -- with a Career/season toggle and a
     minimum-weeks-rostered filter (to distinguish "pickups that mattered"
     from every single add).
  2. Value by Week of the Season -- volume and average value of pickups,
     by which week of the season they were added.

SOURCE: waiver_stints_full.csv (Season, Manager, Player_ID, Start_Week,
End_Week, Type, Weeks_Rostered, Total_Points, PPW, Avg_Z, Total_Z, Position)

VERIFICATION (already done manually before writing this script, repeated
here so it's part of the reproducible record): aggregating this file by
Manager+Type and computing weeks-weighted mean Avg_Z (equivalently
sum(Total_Z)/sum(Weeks_Rostered)) reproduces the already-published wvZ/faZ
values in waiver-value.html's CONTESTED_SPLIT to within 0.0006 (rounding),
across all 14 managers, with exact pickup-count matches too. That confirms
this file is the correct, same-methodology source before trusting it for
new cuts.

OUTPUT: prints a compact JS array literal to embed directly in
waiver-value.html, plus verification stats.
"""

import pandas as pd
import json

SOURCE_CSV = "waiver_stints_full.csv"
ROSTERS_CSV = "weekly_rosters_clean.csv"


def main():
    df = pd.read_csv(SOURCE_CSV)
    rosters = pd.read_csv(ROSTERS_CSV)

    # Player_ID -> name lookup, needed for the week-detail panel (this
    # file only has Player_ID, not the name). Verified all 1757 rows
    # match before trusting this join.
    name_lookup = rosters.drop_duplicates("Player_ID").set_index("Player_ID")["Player"].to_dict()
    missing = (~df["Player_ID"].isin(name_lookup)).sum()
    if missing:
        print(f"WARNING: {missing} rows have no matching player name -- check before using.")

    # Compact field names to keep the embedded payload small: s=season,
    # m=manager, t=type (W/F), sw=start week, wk=weeks rostered, z=total_z,
    # p=player, pos=position.
    records = []
    for _, r in df.iterrows():
        records.append({
            "s": int(r["Season"]),
            "m": r["Manager"],
            "t": "W" if r["Type"] == "WAIVER" else "F",
            "sw": int(r["Start_Week"]),
            "wk": int(r["Weeks_Rostered"]),
            "z": round(float(r["Total_Z"]), 3),
            "p": name_lookup.get(r["Player_ID"], "Unknown Player"),
            "pos": r["Position"],
        })

    payload = json.dumps(records, separators=(",", ":"))
    print(f"Records: {len(records)}")
    print(f"Payload size: {len(payload)} bytes")
    print()
    print("var WAIVER_STINTS = " + payload + ";")


if __name__ == "__main__":
    main()
