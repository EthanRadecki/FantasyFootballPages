import pandas as pd
import numpy as np
from scipy import stats

EXCLUDE = {'Thomas Sullivan', 'William Serafin'}
NAME_ALIASES = {'Carmine Pittelli': 'Carmine Pittelli Jr.', 'Ryan McQuaid': 'Ryan P McQuaid'}

draft = pd.read_csv('/mnt/user-data/uploads/draft_surplus_v2.csv')
draft['manager'] = draft['manager'].replace(NAME_ALIASES)
draft = draft[~draft['manager'].isin(EXCLUDE)]
draft_season = draft.groupby(['manager','season'])['surplus_wtd'].sum().reset_index()
draft_season.columns = ['Manager','Season','draft_value']

# Waiver: upside-only impact (sum of positive Total_Z per stint; bad/neutral
# pickups contribute nothing, rather than dragging the season total down)
waiver = pd.read_csv('/mnt/user-data/uploads/waiver_stints_full.csv')
waiver = waiver[~waiver['Manager'].isin(EXCLUDE)]
waiver['pos_z'] = waiver['Total_Z'].clip(lower=0)
waiver_season = waiver.groupby(['Manager','Season'])['pos_z'].sum().reset_index()
waiver_season.columns = ['Manager','Season','waiver_value']

lineup = pd.read_csv('/mnt/user-data/uploads/lineup_efficiency.csv')
lineup = lineup[~lineup['Manager'].isin(EXCLUDE)]
lineup_season = lineup.groupby(['Manager','Season'])['Missed_Win'].sum().reset_index()
lineup_season['lineup_value'] = -lineup_season['Missed_Win']

quad = pd.read_csv('/mnt/user-data/uploads/metrics_final.csv')
quad = quad[~quad['manager'].isin(EXCLUDE)]
trade_season = quad.groupby(['manager','season'])['QUAD'].sum().reset_index()
trade_season.columns = ['Manager','Season','trade_value']

luck_season = pd.read_csv('/home/claude/work/schedule_luck_season.csv')[['Manager','Season','schedule_luck']]

mgr_stats = pd.read_csv('/mnt/user-data/uploads/preach_manager_stats.csv')
mgr_stats = mgr_stats[~mgr_stats['Manager'].isin(EXCLUDE)]
winpct = mgr_stats[['Manager','Year','W%']].rename(columns={'Year':'Season'})

df = winpct.merge(draft_season, on=['Manager','Season'], how='left') \
           .merge(waiver_season, on=['Manager','Season'], how='left') \
           .merge(lineup_season[['Manager','Season','lineup_value']], on=['Manager','Season'], how='left') \
           .merge(trade_season, on=['Manager','Season'], how='left') \
           .merge(luck_season, on=['Manager','Season'], how='left')
df['trade_value'] = df['trade_value'].fillna(0)
df = df.dropna(subset=['draft_value','waiver_value','lineup_value','schedule_luck'])
df.to_csv('/home/claude/work/attribution_season_data_v5.csv', index=False)
print("Saved attribution_season_data_v5.csv, n =", len(df))
