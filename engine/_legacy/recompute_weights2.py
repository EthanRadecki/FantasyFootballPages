import pandas as pd
import numpy as np
import json

EXCLUDED = {'Thomas Sullivan', 'William Serafin'}

# Known forfeit: Ben Castaldo, 2024 Week 14 (since-banned) -- excluded from
# real-game analyses site-wide per established convention, same here.
W_PTS, W_DOM, W_STREAK = 0.70, 0.15, 0.15

# Each champion's EXACT known opponent sequence (from the already-published,
# verified CHAMPIONS array) -- used to identify their real window precisely,
# instead of picking whichever window scores highest under new weights
# (that was the bug: a different, non-playoff stretch can outscore a
# champion's real run once weights change).
CHAMPIONS_KNOWN = [
    (2024, 'Baylen Slansky', ['Max Malich','Cole Maney','Brandon Hancock']),
    (2023, 'Carmine Pittelli Jr.', ['Aidan Quigley','Charlie Gorman','Cole Maney']),
    (2022, 'Anthony Kelly', ['Ethan Radecki','Brandon Hancock','Ryan P McQuaid']),
    (2025, 'Anthony Kelly', ['Cole Maney','Ethan Radecki','Charlie Gorman']),
    (2020, 'Ethan Radecki', ['Ryan P McQuaid','Andrew Root','Deniz Bileydi','Brandon Hancock']),
    (2021, 'Ben Castaldo', ['Baylen Slansky','Andrew Root','Anthony Kelly']),
]

def week_num(w, reg_len):
    if w.startswith('Week'):
        return int(w.split(' ')[1])
    return reg_len + int(w.split(' ')[-1])

m = pd.read_csv('matchup_data.csv')
d = pd.read_csv('preach_manager_stats.csv')
m = m[~m['Team_Name'].isin(EXCLUDED) & ~m['Opponent_Name'].isin(EXCLUDED)].copy()
d = d[~d['Manager'].isin(EXCLUDED)].copy()

is_real = m['Week'].str.startswith('Week') | (m['Is_Playoff'] == 'Yes')
is_forfeit = (m['Team_Score'] == 0) | (m['Opponent_Score'] == 0)
real = m[is_real & ~is_forfeit].copy()
reg_len_by_season = real[real['Week'].str.startswith('Week')].assign(
    wn=lambda x: x['Week'].str.replace('Week ', '', regex=False).astype(int)
).groupby('Season_Year')['wn'].max().to_dict()
real['abs_week'] = real.apply(lambda r: week_num(r['Week'], reg_len_by_season[r['Season_Year']]), axis=1)
real = real.sort_values(['Season_Year', 'Team_Name', 'abs_week']).reset_index(drop=True)
is_reg = real['Week'].str.startswith('Week')

pts_pop = real['Team_Score'].values
pts_mean, pts_std = pts_pop.mean(), pts_pop.std()
dom_map = {}
for _, r in d.iterrows():
    dom_map[(r['Year'], r['Manager'])] = r['Dominance_Score']
dom_pop = d['Dominance_Score'].values
dom_mean, dom_std = dom_pop.mean(), dom_pop.std()
season_avg_reg = real[is_reg].groupby(['Season_Year', 'Team_Name'])['Team_Score'].mean().to_dict()
streak_map, streak_vals = {}, []
for (season, mgr), grp in real.groupby(['Season_Year', 'Team_Name']):
    grp = grp.sort_values('abs_week').reset_index(drop=True)
    scores = grp['Team_Score'].tolist(); weeks_abs = grp['abs_week'].tolist()
    baseline = season_avg_reg.get((season, mgr))
    for i in range(5, len(scores)):
        surge = sum(scores[i-5:i]) / 5 - baseline
        streak_map[(season, mgr, weeks_abs[i])] = surge
        streak_vals.append(surge)
streak_mean, streak_std = np.mean(streak_vals), np.std(streak_vals)

def logistic(z): return 100 / (1 + np.exp(-z))

def compute_windows(n):
    results = []
    for (season, mgr), grp in real.groupby(['Season_Year', 'Team_Name']):
        grp = grp.sort_values('abs_week').reset_index(drop=True)
        n_games = len(grp)
        for start in range(5, n_games - (n - 1)):
            window = grp.iloc[start:start+n]
            if len(window) < n: continue
            aw = window['abs_week'].tolist()
            if any(aw[j+1] != aw[j]+1 for j in range(len(aw)-1)): continue
            pts_zs, dom_zs, streak_zs, opps, games_detail = [], [], [], [], []
            ok = True
            for _, g in window.iterrows():
                opp = g['Opponent_Name']; wk = g['abs_week']
                dom = dom_map.get((season, opp)); surge = streak_map.get((season, opp, wk))
                if dom is None or surge is None: ok = False; break
                pts_zs.append((g['Opponent_Score']-pts_mean)/pts_std)
                dom_zs.append((dom-dom_mean)/dom_std)
                streak_zs.append((surge-streak_mean)/streak_std)
                opps.append(opp)
                games_detail.append({
                    'week': g['Week'], 'opponent': opp,
                    'own_score': round(float(g['Team_Score']), 1),
                    'opp_score': round(float(g['Opponent_Score']), 1),
                    'margin': round(float(g['Team_Score']-g['Opponent_Score']), 1),
                    'opp_dom': round(float(dom), 3), 'opp_surge': round(float(surge), 1),
                })
            if not ok: continue
            shrink = n / (n + 1)
            s_pts = logistic(sum(pts_zs)/n*shrink)
            s_dom = logistic(sum(dom_zs)/n*shrink)
            s_streak = logistic(sum(streak_zs)/n*shrink)
            gs = W_PTS*s_pts + W_DOM*s_dom + W_STREAK*s_streak
            results.append({'season': int(season), 'manager': mgr, 'start': aw[0], 'opps': opps,
                             's_pts': round(float(s_pts),1), 's_dom': round(float(s_dom),1),
                             's_streak': round(float(s_streak),1), 'gs': round(float(gs),2),
                             'games': games_detail})
    return pd.DataFrame(results)

res3 = compute_windows(3)
res4 = compute_windows(4)

ranked3 = res3.sort_values('gs', ascending=False).reset_index(drop=True)
ranked3['rank'] = ranked3.index + 1
ranked4 = res4.sort_values('gs', ascending=False).reset_index(drop=True)
ranked4['rank'] = ranked4.index + 1

champion_results = []
for year, champ, opp_seq in CHAMPIONS_KNOWN:
    n = len(opp_seq)
    pool = res4 if n == 4 else res3
    rankedX = ranked4 if n == 4 else ranked3
    matches = rankedX[(rankedX['season']==year) & (rankedX['manager']==champ)]
    # Identify by EXACT opponent sequence match, not by max score
    exact = matches[matches['opps'].apply(lambda x: x == opp_seq)]
    if len(exact) == 0:
        print(f"NO EXACT MATCH for {year} {champ} -- opps found: {matches['opps'].tolist()}")
        continue
    row = exact.iloc[0]
    champion_results.append({
        'year': year, 'champion': champ, 'n': n,
        's_pts': row['s_pts'], 's_dom': row['s_dom'], 's_streak': row['s_streak'],
        'gs': round(float(row['gs']), 1),
        'rank': int(row['rank']), 'total': len(rankedX),
        'games': row['games'],
    })
    print(f"{year} {champ} (n={n}): gs={row['gs']:.1f}  rank={int(row['rank'])}/{len(rankedX)}")

champion_results.sort(key=lambda x: -x['gs'])
print("\nRe-sorted champion order:")
for c in champion_results:
    print(f"  {c['year']} {c['champion']}: {c['gs']}")

idx_max = res3.groupby(['season','manager'])['gs'].idxmax()
idx_min = res3.groupby(['season','manager'])['gs'].idxmin()
hardest5 = res3.loc[idx_max].sort_values('gs', ascending=False).head(5).to_dict('records')
easiest5 = res3.loc[idx_min].sort_values('gs', ascending=True).head(5).to_dict('records')

print("\nNew hardest 5:")
for r in hardest5: print(f"  {r['season']} {r['manager']}: gs={r['gs']}")
print("\nNew easiest 5:")
for r in easiest5: print(f"  {r['season']} {r['manager']}: gs={r['gs']}")
print(f"\nGlobal hardest: {ranked3.iloc[0]['gs']:.2f}   Global easiest: {ranked3.iloc[-1]['gs']:.2f}")

def clean(rec):
    r = dict(rec)
    r.pop('opps', None)
    return r

output = {
    'champions': champion_results,
    'hardest5': [clean(r) for r in hardest5],
    'easiest5': [clean(r) for r in easiest5],
    'global_hardest': round(float(ranked3.iloc[0]['gs']), 2),
    'global_easiest': round(float(ranked3.iloc[-1]['gs']), 2),
    'total3': len(ranked3), 'total4': len(ranked4),
}
with open('reweighted_output2.json', 'w') as f:
    json.dump(output, f, indent=2, default=str)
print("\nWrote reweighted_output2.json")
