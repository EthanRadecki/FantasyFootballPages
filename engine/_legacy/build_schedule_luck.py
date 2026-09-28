import pandas as pd
import numpy as np
import re

EXCLUDE = {'Thomas Sullivan', 'William Serafin'}

matchup = pd.read_csv('/mnt/user-data/uploads/matchup_data.csv')
season_round_to_week = {}
for season, g in matchup.groupby('Season_Year'):
    reg_weeks = [int(re.search(r'\d+', w).group()) for w in g['Week'].unique() if w.startswith('Week')]
    max_reg = max(reg_weeks)
    rounds = sorted(set(w for w in g['Week'].unique() if w.startswith('Playoff Round')),
                     key=lambda s: int(re.search(r'\d+', s).group()))
    for i, rnd in enumerate(rounds, start=1):
        season_round_to_week[(int(season), rnd)] = max_reg + i

def label_to_week(season, label):
    if label.startswith('Week'):
        return int(re.search(r'\d+', label).group())
    return season_round_to_week[(int(season), label)]

matchup['NumericWeek'] = matchup.apply(lambda r: label_to_week(r['Season_Year'], r['Week']), axis=1)
# Schedule luck uses REGULAR SEASON ONLY -- not even real playoff bracket games,
# since the league median comparison isn't meaningful once the field shrinks
# to 8/4/2 teams each round. Consolation games were never eligible either way.
valid = matchup[matchup['Week'].str.startswith('Week')].copy()
valid = valid[~valid['Team_Name'].isin(EXCLUDE)]

# Weekly median across all valid teams playing that (season, week)
medians = valid.groupby(['Season_Year', 'NumericWeek'])['Team_Score'].median().reset_index()
medians.columns = ['Season_Year', 'NumericWeek', 'median_score']

valid = valid.merge(medians, on=['Season_Year', 'NumericWeek'])
valid['expected_win'] = (valid['Team_Score'] > valid['median_score']).astype(float)
valid['actual_win'] = (valid['Outcome'] == 'Win').astype(float)

season_luck = valid.groupby(['Team_Name', 'Season_Year']).apply(lambda g: pd.Series({
    'actual_wins': g['actual_win'].sum(),
    'expected_wins': g['expected_win'].sum(),
    'schedule_luck': g['actual_win'].sum() - g['expected_win'].sum()
})).reset_index()
season_luck.columns = ['Manager', 'Season', 'actual_wins', 'expected_wins', 'schedule_luck']

season_luck.to_csv('/home/claude/work/schedule_luck_season.csv', index=False)

print("=== Career schedule luck per manager ===")
career = season_luck.groupby('Manager')['schedule_luck'].sum().sort_values(ascending=False)
print(career)
