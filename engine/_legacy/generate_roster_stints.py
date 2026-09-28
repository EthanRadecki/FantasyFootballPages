import pandas as pd
import json

df = pd.read_csv('/mnt/user-data/uploads/weekly_rosters_clean.csv')

EXCLUDE = {'Thomas Sullivan', 'William Serafin'}
df = df[~df['Manager'].isin(EXCLUDE)].copy()
df['Started'] = df['Started'].astype(str).str.strip().str.lower() == 'true'

out = {}

for (mgr, player), g in df.groupby(['Manager', 'Player']):
    position = g['Position'].iloc[0]
    stints = []
    for season, gs in g.groupby('Season'):
        weeks = sorted(gs['Week'].tolist())
        started_set = set(gs.loc[gs['Started'], 'Week'].tolist())
        # break into contiguous runs within this season
        run_start = weeks[0]
        prev = weeks[0]
        for w in weeks[1:] + [None]:
            if w is None or w != prev + 1:
                stints.append({
                    'season': int(season),
                    'start': int(run_start),
                    'end': int(prev),
                    'started': sorted([int(x) for x in started_set if run_start <= x <= prev])
                })
                if w is not None:
                    run_start = w
            prev = w if w is not None else prev

    out.setdefault(mgr, {})[player] = {
        'position': position,
        'stints': stints
    }

with open('/home/claude/work/roster_stints.json', 'w') as f:
    json.dump(out, f, separators=(',', ':'))

import os
print('Managers:', len(out))
print('File size KB:', os.path.getsize('/home/claude/work/roster_stints.json')/1024)

# sanity check
sample = out['Ethan Radecki']['A.J. Brown']
print(json.dumps(sample, indent=2))
