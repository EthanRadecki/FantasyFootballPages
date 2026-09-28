import pandas as pd
import json

# =============================================================================
# Generates the DRAFT and SLOT_ORDER JS data objects for draft-history.html
# Run this and paste the output into the <script> block
# =============================================================================

draft  = pd.read_csv("draft_history_all_positions.csv")
stats  = pd.read_csv("draft_with_stats.csv")

# Merge in PPG and games_played from stats (skill positions only)
skill  = stats[["player_name","season","position","ppr_per_game","games_played"]].copy()
draft  = draft.merge(skill, on=["player_name","season","position"], how="left")

SEASONS = sorted(draft["season"].unique(), reverse=True)

print("var DRAFT = {")

for season in SEASONS:
    s_df = draft[draft["season"] == season].copy()
    rounds = sorted(s_df["round"].unique())

    print(f"\n{season}: {{")

    for rnd in rounds:
        r_df = s_df[s_df["round"] == rnd].sort_values("overall_pick")
        picks = []
        for _, row in r_df.iterrows():
            ppg   = None if pd.isna(row.get("ppr_per_game")) else round(float(row["ppr_per_game"]), 2)
            games = None if pd.isna(row.get("games_played")) else int(row["games_played"])
            picks.append({
                "p":   row["player_name"],
                "pos": row["position"],
                "ppg": ppg,
                "g":   games,
            })

        picks_json = json.dumps(picks, separators=(',',':'))
        comma = "," if rnd < max(rounds) else ""
        print(f"  {rnd}: {picks_json}{comma}")

    season_comma = "," if season != SEASONS[-1] else ""
    print(f"}}{season_comma}")

print("};")

print("\n\nvar SLOT_ORDER = {")
for season in SEASONS:
    s_df = draft[(draft["season"] == season) & (draft["round"] == 1)].sort_values("draft_slot")
    managers = s_df["manager"].tolist()
    comma = "," if season != SEASONS[-1] else ""
    print(f"  {season}: {json.dumps(managers)}{comma}")
print("};")
