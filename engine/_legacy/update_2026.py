"""
update_2026.py

Weekly in-season refresh for the matchups and managers pages. Re-runnable:
every run strips the live season from each output and rebuilds it from
scratch, so 2020-2025 content is never recomputed or touched.

Inputs (repo root):
  matchup_data.csv            2020-2025 + live season rows appended
  weekly_rosters_2026.csv     from pull_espn_2026.py
  teams_2026.csv              from pull_espn_2026.py
  data/matchups.json, data/franchise_leaders.json,
  data/best_single_week.json, data/preach_manager_stats.csv,

  data/roster_stints.json

Outputs: the same five data/ files, updated in place.

Player names: matchups.json keeps raw ESPN names (that's what the shipped
file uses), but franchise_leaders.json and best_single_week.json use the
canonical names from weekly_rosters_clean.csv. player_name_map.json maps raw
ESPN spellings to those canonical names so a player's 2026 rows join his
2020-2025 rows in the Career views. Seeded from the 2025 replay; add to it
when a new mismatch shows up.

Per-season stats columns use formulas verified against the shipped 2025
rows (exact match): PF/G and PA/G ranks within year, Luck_Rating =
PF/G rank - PA/G rank, LR_zscore and Dominance_Score = within-year z-scores
(sample std) of PA/G and PF/G, DIFF = PF/G - PA/G.

While the season is in progress: Placement_within_Year is the current
standings order (W desc, then PF desc), Playoffs/Champ_App/Champ_W are 0.
The four all-time columns (Rank_Win%_Overall, Rank_PPG_Overall,
Weighted_Rank_Ovr, Weighted_Rank_Overall_Value) are left blank for the live
season (see LIVE_OVERALL_RANKS below).
"""
import json
import sys
import pandas as pd

from build_matchups_json import build_games, load_matchups, reg_season_lengths

SEASON = int(sys.argv[1]) if len(sys.argv) > 1 else 2026
DATA = sys.argv[2] if len(sys.argv) > 2 else "GitHubRepoData"
MATCHUP_CSV = "GitHubRepoData/matchup_data.csv"
ROSTERS_CSV = f"weekly_rosters_{SEASON}.csv"
TEAMS_CSV = f"teams_{SEASON}.csv"

EXCLUDED_MANAGERS = {"Thomas Sullivan", "William Serafin"}
TOP_N_PER_GROUP = 25          # same as generate_best_single_week.py
NAME_MAP_JSON = "player_name_map.json"
LIVE_OVERALL_RANKS = None     # blank all-time rank columns for the live season


# ---------------------------------------------------------------- matchups.json
def update_matchups(m, r):
    path = f"{DATA}/matchups.json"
    with open(path) as f:
        games = [g for g in json.load(f) if g["season"] != SEASON]
    new = build_games(m, r, seasons=[SEASON])
    missing = [g["id"] for g in new if not g["teamA"]["starters"] or not g["teamB"]["starters"]]
    if missing:
        raise SystemExit(f"matchups.json: {len(missing)} live games have no box score, e.g. {missing[:3]}")
    games.extend(new)
    with open(path, "w") as f:
        json.dump(games, f, separators=(",", ":"))
    print(f"matchups.json: +{len(new)} {SEASON} games ({len(games)} total)")


# ------------------------------------------------------ franchise_leaders.json
def canonical_names(r):
    try:
        with open(NAME_MAP_JSON) as f:
            name_map = json.load(f)
    except FileNotFoundError:
        name_map = {}
    r = r.copy()
    r["Player"] = r["Player"].replace(name_map)
    return r


def update_franchise_leaders(r):
    """Same aggregation as generate_franchise_leaders.py, live season only."""
    path = f"{DATA}/franchise_leaders.json"
    with open(path) as f:
        fl = json.load(f)
    df = r[~r["Manager"].isin(EXCLUDED_MANAGERS)].copy()
    df["Started"] = df["Started"].astype(str).str.strip().str.lower() == "true"
    keys = ["Manager", "Player", "Position", "Season"]
    rostered = df.groupby(keys).size().reset_index(name="weeks_rostered")
    started = (df[df["Started"]].groupby(keys)
               .agg(games_played=("Points", "size"), total_points=("Points", "sum")).reset_index())
    merged = rostered.merge(started, on=keys, how="left")
    merged["games_played"] = merged["games_played"].fillna(0).astype(int)
    merged["total_points"] = merged["total_points"].fillna(0.0).round(2)

    added = 0
    for mgr, sub in merged.groupby("Manager"):
        rows = [x for x in fl.get(mgr, []) if x["season"] != SEASON]   # history untouched, in place
        for x in sub.sort_values(["Player", "Position"]).itertuples():
            rows.append({"player": x.Player, "position": x.Position, "season": int(x.Season),
                         "weeks_rostered": int(x.weeks_rostered), "games_played": int(x.games_played),
                         "total_points": float(x.total_points)})
            added += 1
        fl[mgr] = rows
    with open(path, "w") as f:
        json.dump(fl, f, separators=(",", ":"))
    print(f"franchise_leaders.json: +{added} {SEASON} player-season rows")


# ----------------------------------------------------- best_single_week.json
def update_best_single_week(m, r):
    """Same valid-week + starting-lineup filter as generate_best_single_week.py."""
    path = f"{DATA}/best_single_week.json"
    with open(path) as f:
        bsw = json.load(f)

    reg_len = reg_season_lengths(m)[SEASON]
    live = m[m["Season_Year"] == SEASON]
    valid = {(t, wk) for t in live["Team_Name"].unique() for wk in range(1, reg_len + 1)}
    po = live[live["Week"].str.startswith("Playoff Round") & (live["Is_Playoff"] == "Yes")]
    valid |= {(t, reg_len + int(w.replace("Playoff Round ", ""))) for t, w in zip(po["Team_Name"], po["Week"])}

    df = r[~r["Manager"].isin(EXCLUDED_MANAGERS)].copy()
    df["Started"] = df["Started"].astype(str).str.strip().str.lower() == "true"
    df = df[[(mg, int(w)) in valid for mg, w in zip(df["Manager"], df["Week"])]]
    real = df[df["Started"] & (df["Slot"] != "IR")]

    added = 0
    for mgr, grp in real.groupby("Manager"):
        rows = [x for x in bsw.get(mgr, []) if x["season"] != SEASON]
        for _, g in grp.groupby("Position"):
            for x in g.sort_values("Points", ascending=False).head(TOP_N_PER_GROUP).itertuples():
                rows.append({"player": x.Player, "position": x.Position, "season": int(x.Season),
                             "week": int(x.Week), "points": round(float(x.Points), 1)})
                added += 1
        rows.sort(key=lambda x: x["points"], reverse=True)
        bsw[mgr] = rows
    with open(path, "w") as f:
        json.dump(bsw, f, separators=(",", ":"))
    print(f"best_single_week.json: +{added} {SEASON} rows")


# ------------------------------------------------------- roster_stints.json
def season_stints(g):
    """Contiguous rostered-week runs within one season (same logic as generate_roster_stints.py)."""
    weeks = sorted(int(w) for w in g["Week"])
    started = {int(w) for w in g.loc[g["Started"], "Week"]}
    runs, start, prev = [], weeks[0], weeks[0]
    for w in weeks[1:] + [None]:
        if w is None or w != prev + 1:
            runs.append({"season": SEASON, "start": start, "end": prev,
                         "started": sorted(x for x in started if start <= x <= prev)})
            if w is not None:
                start = w
        prev = w if w is not None else prev
    return runs


def update_roster_stints(r):
    path = f"{DATA}/roster_stints.json"
    with open(path) as f:
        rs = json.load(f)
    # strip the live season everywhere (re-runnable), dropping players left with no stints
    for mgr in list(rs):
        for player in list(rs[mgr]):
            rs[mgr][player]["stints"] = [x for x in rs[mgr][player]["stints"] if x["season"] != SEASON]
            if not rs[mgr][player]["stints"]:
                del rs[mgr][player]
    df = r[~r["Manager"].isin(EXCLUDED_MANAGERS)].copy()
    df["Started"] = df["Started"].astype(str).str.strip().str.lower() == "true"
    added = new_players = 0
    for (mgr, player), g in df.groupby(["Manager", "Player"]):
        entry = rs.setdefault(mgr, {}).get(player)
        if entry is None:
            entry = rs[mgr][player] = {"position": g["Position"].iloc[0], "stints": []}
            new_players += 1
        runs = season_stints(g)
        entry["stints"].extend(runs)
        added += len(runs)
    with open(path, "w") as f:
        json.dump(rs, f, separators=(",", ":"))
    print(f"roster_stints.json: +{added} {SEASON} stints ({new_players} players new to their manager)")


# ---------------------------------------------------- preach_manager_stats.csv
def season_stats_rows(m, teams):
    reg = m[(m["Season_Year"] == SEASON) & m["Week"].str.startswith("Week ")]
    g = (reg.groupby("Team_Name")
         .agg(W=("Outcome", lambda x: int((x == "Win").sum())),
              L=("Outcome", lambda x: int((x == "Loss").sum())),
              GP=("Outcome", "size"), PF=("Team_Score", "sum"), PA=("Opponent_Score", "sum"))
         .reset_index().rename(columns={"Team_Name": "Manager"}))
    g["PF"] = g["PF"].round(2)
    g["PA"] = g["PA"].round(2)
    g["W%"] = g["W"] / g["GP"]
    g["PF/G"] = g["PF"] / g["GP"]
    g["PA/G"] = g["PA"] / g["GP"]
    # PF/G ties broken by wins (matches the shipped 2025 Carmine/Hancock tie)
    g = g.sort_values(["PF/G", "W"], ascending=False).reset_index(drop=True)
    g["PF/G_Rank_within_Year"] = g.index + 1
    g["PA/G_Rank_within_Year"] = g["PA/G"].rank(ascending=True, method="min").astype(int)
    g["Luck_Rating"] = g["PF/G_Rank_within_Year"] - g["PA/G_Rank_within_Year"]
    g["LR_zscore"] = (g["PA/G"] - g["PA/G"].mean()) / g["PA/G"].std(ddof=1)
    g["Dominance_Score"] = (g["PF/G"] - g["PF/G"].mean()) / g["PF/G"].std(ddof=1)
    g["DIFF"] = g["PF/G"] - g["PA/G"]
    for col in ["W%", "PF/G", "PA/G", "LR_zscore", "Dominance_Score", "DIFF"]:
        g[col] = g[col].round(9)
    g = g.sort_values(["W", "PF"], ascending=False).reset_index(drop=True)
    g["Placement_within_Year"] = g.index + 1
    g["Year"] = SEASON
    g["Playoffs"] = 0
    g["Champ_App"] = 0
    g["Champ_W"] = 0
    for col in ["Rank_Win%_Overall", "Rank_PPG_Overall", "Weighted_Rank_Ovr", "Weighted_Rank_Overall_Value"]:
        g[col] = LIVE_OVERALL_RANKS
    if teams is not None:
        g = g.merge(teams[["Manager", "Fantasy_Team", "Conference", "Draft_Slot"]]
                    .rename(columns={"Fantasy_Team": "Team"}), on="Manager", how="left")
    return g


def update_manager_stats(m, teams):
    """Splices the live season's rows in as text so 2020-2025 lines stay byte-identical."""
    path = f"{DATA}/preach_manager_stats.csv"
    s = pd.read_csv(path)
    new = season_stats_rows(m, teams)
    for col in ["Team", "Conference", "Draft_Slot"]:
        if col not in new:
            new[col] = None
    new = new[s.columns]
    known = set(s["Conference"].dropna())
    odd = set(new["Conference"].dropna()) - known
    if odd:
        print(f"  WARNING Conference values {odd} don't match historical {known}; fix in {TEAMS_CSV}")

    with open(path, newline="") as f:
        lines = f.read().split("\r\n")
    header, body = lines[0], [ln for ln in lines[1:] if ln]
    year_idx = header.split(",").index("Year")
    keep = [ln for ln in body if ln.split(",")[year_idx] != str(SEASON)]  # no commas inside fields
    new_lines = new.to_csv(index=False, header=False, lineterminator="\r\n").rstrip("\r\n").split("\r\n")
    with open(path, "w", newline="") as f:
        f.write("\r\n".join([header] + keep + new_lines) + "\r\n")
    print(f"preach_manager_stats.csv: {len(new)} {SEASON} rows (through {int(new['GP'].max())} games)")
    return new


def main():
    m = load_matchups(MATCHUP_CSV)
    r = pd.read_csv(ROSTERS_CSV)
    r = r[r["Season"] == SEASON]
    try:
        teams = pd.read_csv(TEAMS_CSV)
    except FileNotFoundError:
        teams = None
    update_matchups(m, r)
    update_franchise_leaders(canonical_names(r))
    update_best_single_week(m, canonical_names(r))
    update_roster_stints(canonical_names(r))
    update_manager_stats(m, teams)


if __name__ == "__main__":
    main()
