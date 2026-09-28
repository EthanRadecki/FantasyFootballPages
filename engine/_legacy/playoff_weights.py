"""
Shared playoff-weighting logic: maps (season, week) -> a multiplier applied
to every weekly z-score / point differential before it's aggregated into
any metric. Regular season = 1.0x. Playoff weeks are weighted by ROLE
(First Round/Quarterfinal/Semifinal/Championship), not raw round number,
since 2020/2021 ran 4 rounds and 2022+ ran 3.
"""
import pandas as pd

ROLE_WEIGHTS = {
    'Regular': 1.0,
    'First Round': 1.15,
    'Quarterfinal': 1.3,
    'Semifinal': 1.6,
    'Championship': 2.0,
}

def build_week_weight_lookup(rosters):
    """rosters: dataframe with Season, Week, Week_Label columns."""
    lookup = {}
    weeks = rosters[['Season','Week','Week_Label']].drop_duplicates()
    for season, g in weeks.groupby('Season'):
        playoff_rounds = sorted(g[g['Week_Label'].str.contains('Playoff', na=False)]['Week_Label'].unique(),
                                 key=lambda x: int(x.split()[-1]))
        n_rounds = len(playoff_rounds)
        if n_rounds == 4:
            role_order = ['First Round','Quarterfinal','Semifinal','Championship']
        elif n_rounds == 3:
            role_order = ['Quarterfinal','Semifinal','Championship']
        else:
            role_order = ['Championship'] * n_rounds  # fallback, shouldn't happen

        round_to_role = dict(zip(playoff_rounds, role_order))
        for _, row in g.iterrows():
            if row['Week_Label'] in round_to_role:
                role = round_to_role[row['Week_Label']]
            else:
                role = 'Regular'
            lookup[(row['Season'], row['Week'])] = ROLE_WEIGHTS[role]
    return lookup

if __name__ == '__main__':
    rosters = pd.read_csv('/mnt/user-data/uploads/weekly_rosters_bracket_only.csv')
    lookup = build_week_weight_lookup(rosters)
    # sanity check
    for season in [2020, 2022]:
        print(season, {wk: lookup[(season,wk)] for wk in range(12,18)})
