"""
build_matchups_json.py

Builds data/matchups.json from matchup_data.csv (scores, outcomes, bracket
flags) plus weekly roster CSVs (box scores). Consolation games (rows with a
"Playoff Round N" label but Is_Playoff == 'No') are excluded, matching the
shipped file.

Conventions, verified by rebuilding the shipped 2020-2025 matchups.json from
weekly_rosters_bracket_only.csv (all 624 games, every id/score/outcome/team
name/starter list identical; the only differences are the order of bench
players tied on points):
  - teamA = whichever team appears first in matchup_data.csv for that game
  - id    = season-week-<sorted pair of manager names, spaces/periods stripped>
  - week  = numeric week; playoff rounds map to (reg season length + round)
  - starters in slot order QB, RB, WR, TE, FLEX, D/ST, K (points desc within a slot)
  - bench (BE + IR) sorted by points desc

Full rebuild:
  python build_matchups_json.py matchup_data.csv weekly_rosters_clean.csv,weekly_rosters_2026.csv data/matchups.json
"""
import json
import sys
import pandas as pd

SLOT_ORDER = {"QB": 0, "RB": 1, "WR": 2, "TE": 3, "RB/WR/TE": 4, "D/ST": 5, "K": 6}
LAST_NAME_OVERRIDES = {"Carmine Pittelli Jr.": "Pittelli", "Ryan P McQuaid": "McQuaid"}


def _key(name):
    return name.replace(" ", "").replace(".", "")


def _last_name(name):
    return LAST_NAME_OVERRIDES.get(name, name.split()[-1])


def load_matchups(path):
    m = pd.read_csv(path)
    return m.loc[:, ~m.columns.str.startswith("Unnamed")]


def reg_season_lengths(m):
    is_reg = m["Week"].str.startswith("Week ")
    return (m.loc[is_reg, "Week"].str.replace("Week ", "", regex=False).astype(int)
            .groupby(m.loc[is_reg, "Season_Year"]).max().to_dict())


def with_week_numbers(m):
    """Regular season + real bracket rows only, with a numeric WeekNum."""
    reg_len = reg_season_lengths(m)
    is_reg = m["Week"].str.startswith("Week ")
    m = m[is_reg | (m["Is_Playoff"] == "Yes")].copy()

    def week_num(row):
        if row["Week"].startswith("Week "):
            return int(row["Week"].replace("Week ", ""))
        return reg_len[row["Season_Year"]] + int(row["Week"].replace("Playoff Round ", ""))

    m["WeekNum"] = m.apply(week_num, axis=1)
    return m


def build_games(m, r, seasons=None):
    """m: matchup_data frame, r: weekly rosters frame. Returns list of game dicts."""
    r = r.copy()
    r["Started"] = r["Started"].astype(str).str.strip().str.lower() == "true"
    m = with_week_numbers(m)
    if seasons is not None:
        m = m[m["Season_Year"].isin(seasons)]
    rosters = {k: g for k, g in r.groupby(["Season", "Week", "Manager"])}
    by_team = {(x["Season_Year"], x["WeekNum"], x["Team_Name"]): x for x in m.to_dict("records")}

    def side(row):
        g = rosters.get((row["Season_Year"], row["WeekNum"], row["Team_Name"]))
        starters, bench, fteam = [], [], ""
        if g is not None:
            fteam = g["Fantasy_Team"].iloc[0]
            real = g["Started"] & (g["Slot"] != "IR")
            st = g[real].assign(o=lambda d: d["Slot"].map(SLOT_ORDER))
            st = st.sort_values(["o", "Points"], ascending=[True, False], kind="stable")
            be = g[~real].sort_values("Points", ascending=False, kind="stable")
            conv = lambda df: [{"name": p.Player, "pos": p.Position, "slot": p.Slot,
                                "pts": round(float(p.Points), 2)} for p in df.itertuples()]
            starters, bench = conv(st), conv(be)
        return {"manager": row["Team_Name"], "lastName": _last_name(row["Team_Name"]),
                "fantasyTeam": fteam, "score": float(row["Team_Score"]),
                "outcome": row["Outcome"], "starters": starters, "bench": bench}

    out, seen = [], set()
    for row in m.to_dict("records"):
        pair = tuple(sorted([row["Team_Name"], row["Opponent_Name"]]))
        gk = (row["Season_Year"], row["WeekNum"], pair)
        if gk in seen:
            continue
        seen.add(gk)
        opp = by_team[(row["Season_Year"], row["WeekNum"], row["Opponent_Name"])]
        a, b = side(row), side(opp)
        out.append({
            "id": f"{row['Season_Year']}-{row['WeekNum']}-{_key(pair[0])}-{_key(pair[1])}",
            "season": int(row["Season_Year"]), "week": int(row["WeekNum"]),
            "weekLabel": row["Week"], "isPlayoff": row["Is_Playoff"] == "Yes",
            "teamA": a, "teamB": b,
            "margin": round(abs(a["score"] - b["score"]), 2),
            "combined": round(a["score"] + b["score"], 2),
        })
    return out


def main():
    matchup_csv = sys.argv[1] if len(sys.argv) > 1 else "matchup_data.csv"
    roster_csvs = sys.argv[2].split(",") if len(sys.argv) > 2 else ["weekly_rosters_clean.csv"]
    output_path = sys.argv[3] if len(sys.argv) > 3 else "data/matchups.json"
    m = load_matchups(matchup_csv)
    r = pd.concat([pd.read_csv(p) for p in roster_csvs], ignore_index=True)
    games = build_games(m, r)
    missing = [g["id"] for g in games if not g["teamA"]["starters"] or not g["teamB"]["starters"]]
    with open(output_path, "w") as f:
        json.dump(games, f, separators=(",", ":"))
    print(f"Wrote {output_path}: {len(games)} games; {len(missing)} missing box scores")
    if missing:
        print("  e.g.", missing[:5])


if __name__ == "__main__":
    main()
