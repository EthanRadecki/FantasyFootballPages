"""
Playoff Odds Monte Carlo -- Preach Fantasy, 2026 LIVE season.

Kept as a separate pipeline from generate_playoff_odds.py (which owns the
validated 2020-2025 backtest) so historical results are never touched
mid-season -- same split as surplus_value_index.py vs
surplus_value_index_2026_live.py.

Unlike the historical backtest, which can see every week's actual pairing
because the season is already complete, live 2026 has no matchup_data.csv
rows for weeks that haven't been played yet -- so future-week opponent
pairs come from schedule_2026.csv instead of being derived from played
results.

Scoring model for each manager's simulated week:
  - MEAN: a blend of (a) their empirical shrinkage mean from actual 2026
    games played so far (identical shrinkage formula to the historical
    script) and (b) that week's ESPN rest-of-season projection from
    projected_sos_weekly_detail.csv (built by build_projected_sos.py,
    bye-substitution aware). Blend weight shifts toward the empirical
    mean as more real games accumulate:
        weight_on_empirical = games_played / (games_played + BLEND_K)
    So with 1 game played and BLEND_K=3, that's 25% empirical / 75%
    projection -- the projection (which actually knows about byes and
    roster construction) carries more weight early, when the empirical
    average is mostly noise, and less as the season goes on. This uses
    ONE blend weight per manager (based on games played as of
    CURRENT_WEEK), applied uniformly to every remaining week -- not a
    fresh weight per week.
  - VARIANCE: unchanged from the historical script's empirical shrinkage
    variance. ESPN gives a point projection, not a distribution, so
    there's nothing to blend it with.

Weekly maintenance:
    1. Append last week's actual results to matchup_data_2026_live.csv
       (same two-rows-per-game format as the site's historical file).
    2. Re-run build_projected_sos.py with START_WEEK bumped, to refresh
       projected_sos_weekly_detail.csv.
    3. Bump CURRENT_WEEK below to the next unplayed week.
    4. Run this script. It merges results into playoff_odds.json under
       the "2026" key only -- the 2020-2025 entries already in that file
       are read back in and rewritten byte-for-byte unchanged.

Run:
    python generate_playoff_odds_2026_live.py
"""

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

np.random.seed(42)
S = 50000          # Monte Carlo trials, matches historical script
CUTOFF = 8          # top 8 by (wins, points) make the bracket, consistent with 2020-2025
SHRINK_K = 3        # empirical mean/variance shrinkage toward league mean (matches historical script)
BLEND_K = 3         # empirical-vs-ESPN-projection blend rate; same constant as SHRINK_K by
                    # convention here, but edit independently if it should decay faster/slower

CURRENT_WEEK = 3    # bump this each week: the next week that hasn't been played yet
NUM_WEEKS = 14      # regular season only, per schedule_2026.csv

DATA_DIR = Path(__file__).parent
MATCHUP_2026_FILE = DATA_DIR / "GitHubRepoData/matchup_data_2026_live.csv"
SCHEDULE_FILE = DATA_DIR / "schedule_2026.csv"
PROJECTED_SOS_FILE = DATA_DIR / "projected_sos_weekly_detail.csv"
PLAYOFF_ODDS_FILE = DATA_DIR / "playoff_odds.json"

# schedule_2026.csv and build_projected_sos.py's TEAM_TO_MANAGER use short
# names for two managers; normalize to the full names used everywhere else
# on the site (matchup_data.csv, playoff_odds.json's existing keys).
NAME_NORMALIZE = {
    "Ryan McQuaid": "Ryan P McQuaid",
    "Carmine Pittelli": "Carmine Pittelli Jr.",
}


def normalize(name):
    return NAME_NORMALIZE.get(name, name)


def main():
    if CURRENT_WEEK > NUM_WEEKS:
        print(f"CURRENT_WEEK ({CURRENT_WEEK}) is past the regular season "
              f"({NUM_WEEKS} weeks) -- nothing left to simulate.")
        return

    # ---- Actual 2026 results played so far (weeks < CURRENT_WEEK) ----
    played = pd.read_csv(MATCHUP_2026_FILE)
    played = played[played["Week"].str.startswith("Week")].copy()
    played["WeekNum"] = played["Week"].str.extract(r"(\d+)").astype(int)
    played = played[played["WeekNum"] < CURRENT_WEEK]

    # ---- Full 14-manager roster, from the schedule (normalized names) ----
    schedule = pd.read_csv(SCHEDULE_FILE)
    schedule["Team_A"] = schedule["Team_A"].map(normalize)
    schedule["Team_B"] = schedule["Team_B"].map(normalize)
    managers = sorted(set(schedule["Team_A"]) | set(schedule["Team_B"]))
    n_teams = len(managers)
    idx = {m: i for i, m in enumerate(managers)}

    # ---- Real record/points to date, empirical scoring distribution ----
    real_wins = np.zeros(n_teams)
    real_pts = np.zeros(n_teams)
    team_scores = {m: [] for m in managers}
    for _, r in played.iterrows():
        m = normalize(r["Team_Name"])
        real_pts[idx[m]] += r["Team_Score"]
        team_scores[m].append(r["Team_Score"])
        if r["Team_Score"] > r["Opponent_Score"]:
            real_wins[idx[m]] += 1
        elif r["Team_Score"] == r["Opponent_Score"]:
            real_wins[idx[m]] += 0.5

    all_scores_to_date = played["Team_Score"].values
    league_mu = all_scores_to_date.mean() if len(all_scores_to_date) else 100.0
    league_var = all_scores_to_date.var(ddof=1) if len(all_scores_to_date) > 1 else 225.0

    team_mu_emp = np.zeros(n_teams)
    team_sigma = np.zeros(n_teams)
    games_played = np.zeros(n_teams, dtype=int)
    for m in managers:
        n = len(team_scores[m])
        games_played[idx[m]] = n
        if n > 0:
            sample_mean = np.mean(team_scores[m])
            mu = (n * sample_mean + SHRINK_K * league_mu) / (n + SHRINK_K)
        else:
            mu = league_mu
        if n > 1:
            sample_var = np.var(team_scores[m], ddof=1)
            var = (n * sample_var + SHRINK_K * league_var) / (n + SHRINK_K)
        else:
            var = league_var
        team_mu_emp[idx[m]] = mu
        team_sigma[idx[m]] = np.sqrt(max(var, 1.0))

    # ---- Week 1 special case: no games played yet, so every manager gets ----
    # the same flat odds (CUTOFF / n_teams) instead of running the sim. With
    # zero real data, team_mu/sigma are identical for everyone anyway (both
    # default to the league constants) -- the only thing that would still
    # vary is the rest-of-season schedule pairing, and letting the sim run
    # would produce small schedule-driven differences that look like signal
    # but are really just noise, since no team has actually played yet.
    weight_emp = games_played / (games_played + BLEND_K)  # used in the printout either way

    if games_played.sum() == 0:
        flat_odds = round(CUTOFF / n_teams * 100, 1)
        week_odds = {m: flat_odds for m in managers}
    else:
        # ---- ESPN rest-of-season projections, for blending future-week means ----
        proj = pd.read_csv(PROJECTED_SOS_FILE)
        proj["manager"] = proj["manager"].map(normalize)
        # {manager: {week: proj_ppg}}
        proj_lookup = {
            m: dict(zip(g["week"], g["proj_ppg"]))
            for m, g in proj.groupby("manager")
        }

        def team_mu_for_week(m, week):
            w = weight_emp[idx[m]]
            emp = team_mu_emp[idx[m]]
            pj = proj_lookup.get(m, {}).get(week)
            if pj is None:
                return emp  # no projection available, fall back to empirical
            return w * emp + (1 - w) * pj

        # ---- Simulate remaining weeks ----
        sim_wins = np.tile(real_wins, (S, 1))
        sim_pts = np.tile(real_pts, (S, 1))

        remaining_sched = schedule[schedule["Week"] >= CURRENT_WEEK]
        for wk, wg in remaining_sched.groupby("Week"):
            for _, r in wg.iterrows():
                a, b = r["Team_A"], r["Team_B"]
                ai, bi = idx[a], idx[b]
                mu_a = team_mu_for_week(a, wk)
                mu_b = team_mu_for_week(b, wk)
                scoreA = np.random.normal(mu_a, team_sigma[ai], S)
                scoreB = np.random.normal(mu_b, team_sigma[bi], S)
                sim_pts[:, ai] += scoreA
                sim_pts[:, bi] += scoreB
                a_wins = scoreA > scoreB
                sim_wins[:, ai] += a_wins
                sim_wins[:, bi] += ~a_wins

        combined = sim_wins * 100000.0 + sim_pts
        order = np.argsort(-combined, axis=1)
        ranks = np.argsort(order, axis=1)
        made_playoffs = (ranks < CUTOFF)
        odds = made_playoffs.mean(axis=0) * 100

        week_odds = {m: round(float(odds[idx[m]]), 1) for m in managers}

    # ---- Merge into playoff_odds.json: touch ONLY the "2026" -> weeks[CURRENT_WEEK] entry ----
    with open(PLAYOFF_ODDS_FILE) as f:
        results = json.load(f)

    if "2026" not in results:
        results["2026"] = {"cutoff": CUTOFF, "max_week": NUM_WEEKS, "weeks": {}}
    results["2026"]["weeks"][str(CURRENT_WEEK)] = week_odds

    with open(PLAYOFF_ODDS_FILE, "w") as f:
        json.dump(results, f, separators=(",", ":"))

    print(f"Week {CURRENT_WEEK} 2026 playoff odds (using data through week {CURRENT_WEEK - 1}):")
    for m, pct in sorted(week_odds.items(), key=lambda kv: -kv[1]):
        print(f"  {m:22s} {pct:5.1f}%  (games played: {games_played[idx[m]]}, "
              f"blend weight on empirical: {weight_emp[idx[m]]:.2f})")
    print(f"\nSaved to {PLAYOFF_ODDS_FILE.name}")


if __name__ == "__main__":
    main()
