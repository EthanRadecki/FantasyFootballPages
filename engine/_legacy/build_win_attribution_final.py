"""
Final Win% Attribution model: 5 factors (draft, waiver, lineup, trade,
schedule luck), refit at manager-season level (n=83), using:
  - corrected metrics_final.csv for trade_value
  - Win% now includes real playoff bracket games (not just regular
    season), still excluding consolation games
  - schedule_luck stays regular-season-only (the shrinking-bracket-field
    problem is sharper for a field-comparison metric than for a plain
    win/loss count, so this one wasn't extended)
"""
import pandas as pd
import numpy as np
import json
import re
from scipy import stats as spstats

EXCLUDE = {'Thomas Sullivan', 'William Serafin'}
NAME_ALIASES = {'Carmine Pittelli': 'Carmine Pittelli Jr.', 'Ryan McQuaid': 'Ryan P McQuaid'}

# ---- draft, waiver, lineup, trade: same as before ----
draft = pd.read_csv('draft_surplus_v2.csv')
draft['manager'] = draft['manager'].replace(NAME_ALIASES)
draft = draft[~draft['manager'].isin(EXCLUDE)]
draft_season = draft.groupby(['manager','season'])['surplus_wtd'].sum().reset_index()
draft_season.columns = ['Manager','Season','draft_value']

waiver = pd.read_csv('waiver_stints_full.csv')
waiver = waiver[~waiver['Manager'].isin(EXCLUDE)]
waiver['pos_z'] = waiver['Total_Z'].clip(lower=0)
waiver_season = waiver.groupby(['Manager','Season'])['pos_z'].sum().reset_index()
waiver_season.columns = ['Manager','Season','waiver_value']

lineup = pd.read_csv('lineup_efficiency.csv')
lineup = lineup[~lineup['Manager'].isin(EXCLUDE)]
lineup_season = lineup.groupby(['Manager','Season'])['Missed_Win'].sum().reset_index()
lineup_season['lineup_value'] = -lineup_season['Missed_Win']

quad = pd.read_csv('/home/claude/trade_pipeline/metrics_final.csv')
quad = quad[~quad['manager'].isin(EXCLUDE)]
trade_season = quad.groupby(['manager','season'])['QUAD'].sum().reset_index()
trade_season.columns = ['Manager','Season','trade_value']

# ---- schedule luck: regular season only, unchanged ----
luck_season = pd.read_csv('schedule_luck_season.csv')[['Manager','Season','schedule_luck']]

# ---- Win%: NOW includes real playoff bracket games ----
matchup = pd.read_csv('matchup_data.csv')
valid_all = matchup[(matchup['Week'].str.startswith('Week')) | (matchup['Is_Playoff']=='Yes')].copy()
valid_all = valid_all[~valid_all['Team_Name'].isin(EXCLUDE)]
winpct = valid_all.groupby(['Team_Name','Season_Year']).apply(
    lambda g: pd.Series({'W%': (g['Outcome']=='Win').mean()})
).reset_index()
winpct.columns = ['Manager','Season','W%']

df = winpct.merge(draft_season, on=['Manager','Season'], how='left') \
           .merge(waiver_season, on=['Manager','Season'], how='left') \
           .merge(lineup_season[['Manager','Season','lineup_value']], on=['Manager','Season'], how='left') \
           .merge(trade_season, on=['Manager','Season'], how='left') \
           .merge(luck_season, on=['Manager','Season'], how='left')
df['trade_value'] = df['trade_value'].fillna(0)
df = df.dropna(subset=['draft_value','waiver_value','lineup_value','schedule_luck'])
df.to_csv('attribution_season_data_final.csv', index=False)
print("n =", len(df))

df['winpct_pts'] = df['W%'] * 100
FACTORS = ['draft_value','waiver_value','lineup_value','trade_value','schedule_luck']
FACTOR_LABELS = {'draft_value':'draft','waiver_value':'waiver','lineup_value':'lineup',
                  'trade_value':'trade','schedule_luck':'luck'}

X = df[FACTORS].values
y = df['winpct_pts'].values
Xc = np.column_stack([np.ones(len(X)), X])
coef, _, _, _ = np.linalg.lstsq(Xc, y, rcond=None)
y_pred = Xc @ coef
ss_res = np.sum((y - y_pred)**2)
ss_tot = np.sum((y - y.mean())**2)
r2 = 1 - ss_res/ss_tot
n, k = Xc.shape
adj_r2 = 1 - (1-r2)*(n-1)/(n-k-1)

sigma2 = ss_res / (n - k)
XtX_inv = np.linalg.inv(Xc.T @ Xc)
se = np.sqrt(np.diag(sigma2 * XtX_inv))
t_stats = coef / se
p_values = 2 * (1 - spstats.t.cdf(np.abs(t_stats), df=n - k))

print(f"R2 = {r2:.4f}, Adjusted R2 = {adj_r2:.4f}")
print("Coefficients and significance:")
for name, c, p in zip(['intercept']+FACTORS, coef, p_values):
    print(f"  {name}: {c:.4f}  p={p:.4f}")

intercept = coef[0]
factor_coefs = dict(zip(FACTORS, coef[1:]))
std_x = df[FACTORS].std()
std_y = y.std()
beta = {f: round(factor_coefs[f] * std_x[f] / std_y, 4) for f in FACTORS}
print("\nStandardized coefficients:")
for f in FACTORS:
    print(f"  {FACTOR_LABELS[f]}: {beta[f]}")
ranked = sorted(FACTORS, key=lambda f: -abs(beta[f]))
print("Ranking:", [FACTOR_LABELS[f] for f in ranked])

league_avg = {f: df[f].mean() for f in FACTORS}
predicted_at_avg = intercept + sum(factor_coefs[f]*league_avg[f] for f in FACTORS)
LEAGUE_INTERCEPT = predicted_at_avg
print("\nLEAGUE_INTERCEPT (predicted at league-average inputs):", round(LEAGUE_INTERCEPT,2))

manager_avgs = df.groupby('Manager')[FACTORS].mean()
manager_winpct = df.groupby('Manager')['winpct_pts'].mean()

DATA = {}
for manager in manager_avgs.index:
    row = manager_avgs.loc[manager]
    contributions = {}
    total_contrib = 0
    for f in FACTORS:
        c = factor_coefs[f] * (row[f] - league_avg[f])
        contributions[FACTOR_LABELS[f]] = round(c, 2)
        total_contrib += c
    predicted = LEAGUE_INTERCEPT + total_contrib
    actual = manager_winpct[manager]
    entry = {'winpct': round(actual,1)}
    entry.update(contributions)
    entry['predicted'] = round(predicted,2)
    entry['residual'] = round(actual - predicted,2)
    DATA[manager] = entry

print("\nSample (Ethan Radecki):", DATA.get('Ethan Radecki'))
print("Sample (Quin Gegwich):", DATA.get('Quin Gegwich'))

out = {
    'DATA': DATA, 'LEAGUE_INTERCEPT': round(LEAGUE_INTERCEPT,2),
    'standardized_coef': {FACTOR_LABELS[f]: beta[f] for f in FACTORS},
    'p_values': {FACTOR_LABELS[f]: round(float(p),4) for f,p in zip(FACTORS, p_values[1:])},
    'all_significant': bool(all(p < 0.05 for p in p_values[1:])),
    'r2': round(r2,4), 'adj_r2': round(adj_r2,4), 'n': int(n)
}
with open('win_attribution_final.json','w') as f:
    json.dump(out, f, indent=2)
print("\nSaved win_attribution_final.json")
