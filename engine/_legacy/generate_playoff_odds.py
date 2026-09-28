import pandas as pd
import numpy as np
import re
import json

np.random.seed(42)
S = 50000            # Monte Carlo trials (raised from 5,000: early weeks have almost
                      # no real signal yet, so noise needs to be small enough that it
                      # doesn't masquerade as a schedule-strength difference)
CUTOFF = 8           # "made the real playoff bracket" -- top 8 by (wins, points), consistent across all 6 seasons (see notes)
SHRINK_K = 3          # shrinkage weight toward league mean/var, matches site's existing shrinkage convention

EXCLUDE_FROM_DISPLAY = {'Thomas Sullivan', 'William Serafin'}  # still simulated (real opponents), just not plotted

m = pd.read_csv('/mnt/user-data/uploads/matchup_data.csv')
m = m[m['Week'].str.startswith('Week')].copy()   # regular season only
m['WeekNum'] = m['Week'].str.extract(r'(\d+)').astype(int)

results = {}

for season, g in m.groupby('Season_Year'):
    season = int(season)
    max_week = g['WeekNum'].max()
    teams = sorted(g['Team_Name'].unique())
    n_teams = len(teams)
    idx = {t: i for i, t in enumerate(teams)}

    # Dedupe games: one row per game (team perspective + opponent perspective both exist)
    games = g[['WeekNum', 'Team_Name', 'Opponent_Name', 'Team_Score']].copy()
    games['pair'] = games.apply(lambda r: tuple(sorted([r['Team_Name'], r['Opponent_Name']])), axis=1)
    games = games.drop_duplicates(subset=['WeekNum', 'pair'])

    week_odds = {}

    for W in range(1, max_week + 1):
        # "Week W" rankings on the site reflect state BEFORE week W is played
        # (pre-week-W), so the simulation must only know results through W-1,
        # then simulate week W onward as still unknown.
        played = g[g['WeekNum'] < W]

        # Real record/points to date
        real_wins = np.zeros(n_teams)
        real_pts = np.zeros(n_teams)
        team_scores = {t: [] for t in teams}
        for _, r in played.iterrows():
            ti = idx[r['Team_Name']]
            real_pts[ti] += r['Team_Score']
            team_scores[r['Team_Name']].append(r['Team_Score'])
            if r['Team_Score'] > r['Opponent_Score']:
                real_wins[ti] += 1
            elif r['Team_Score'] == r['Opponent_Score']:
                real_wins[ti] += 0.5

        all_scores_to_date = played['Team_Score'].values
        league_mu = all_scores_to_date.mean() if len(all_scores_to_date) else 100.0
        league_var = all_scores_to_date.var(ddof=1) if len(all_scores_to_date) > 1 else 225.0

        team_mu = np.zeros(n_teams)
        team_sigma = np.zeros(n_teams)
        for t in teams:
            n = len(team_scores[t])
            if n > 0:
                sample_mean = np.mean(team_scores[t])
                mu = (n * sample_mean + SHRINK_K * league_mu) / (n + SHRINK_K)
            else:
                mu = league_mu
            if n > 1:
                sample_var = np.var(team_scores[t], ddof=1)
                var = (n * sample_var + SHRINK_K * league_var) / (n + SHRINK_K)
            else:
                var = league_var
            team_mu[idx[t]] = mu
            team_sigma[idx[t]] = np.sqrt(max(var, 1.0))

        # Simulate remaining weeks
        sim_wins = np.tile(real_wins, (S, 1))     # (S, n_teams)
        sim_pts  = np.tile(real_pts, (S, 1))

        remaining = games[games['WeekNum'] >= W]
        for wk, wg in remaining.groupby('WeekNum'):
            for _, r in wg.iterrows():
                a, b = r['pair']
                ai, bi = idx[a], idx[b]
                scoreA = np.random.normal(team_mu[ai], team_sigma[ai], S)
                scoreB = np.random.normal(team_mu[bi], team_sigma[bi], S)
                sim_pts[:, ai] += scoreA
                sim_pts[:, bi] += scoreB
                a_wins = scoreA > scoreB
                sim_wins[:, ai] += a_wins
                sim_wins[:, bi] += ~a_wins
            # drop processed rows to avoid double-processing pair duplicates across weeks loop
        # (groupby+iterrows above already dedup'd via `games` drop_duplicates on pair+week)

        # Rank each trial: sort by wins desc, then points desc -> take top CUTOFF.
        # Vectorized across all S trials at once (points are always << 100000,
        # so this composite key preserves "wins first, points as tiebreak").
        combined = sim_wins * 100000.0 + sim_pts
        order = np.argsort(-combined, axis=1)      # best-to-worst team index per trial
        ranks = np.argsort(order, axis=1)          # 0-indexed rank of each team per trial
        made_playoffs = (ranks < CUTOFF)
        odds = made_playoffs.mean(axis=0) * 100

        week_odds[W] = {t: round(float(odds[idx[t]]), 1) for t in teams}

    results[season] = {'cutoff': CUTOFF, 'max_week': int(max_week), 'weeks': week_odds}
    print(f"Season {season}: teams={n_teams} max_week={max_week} done")

with open('/home/claude/work/playoff_odds.json', 'w') as f:
    json.dump(results, f, separators=(',', ':'))

print("Saved playoff_odds.json")
