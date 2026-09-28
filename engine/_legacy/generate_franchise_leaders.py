import pandas as pd
import json

df = pd.read_csv('/mnt/user-data/uploads/weekly_rosters_clean.csv')

EXCLUDE = {'Thomas Sullivan', 'William Serafin'}
df = df[~df['Manager'].isin(EXCLUDE)].copy()

df['Started'] = df['Started'].astype(str).str.strip().str.lower() == 'true'

# Weeks rostered: every row = one week on that manager's roster (any slot incl IR/BE)
rostered = (
    df.groupby(['Manager', 'Player', 'Position', 'Season'])
      .size()
      .reset_index(name='weeks_rostered')
)

# Started-only points/games
started = df[df['Started']]
started_agg = (
    started.groupby(['Manager', 'Player', 'Position', 'Season'])
           .agg(games_played=('Points', 'size'), total_points=('Points', 'sum'))
           .reset_index()
)

merged = rostered.merge(
    started_agg,
    on=['Manager', 'Player', 'Position', 'Season'],
    how='left'
)
merged['games_played'] = merged['games_played'].fillna(0).astype(int)
merged['total_points'] = merged['total_points'].fillna(0.0).round(2)

out = {}
for mgr, sub in merged.groupby('Manager'):
    rows = []
    for _, r in sub.iterrows():
        rows.append({
            'player': r['Player'],
            'position': r['Position'],
            'season': int(r['Season']),
            'weeks_rostered': int(r['weeks_rostered']),
            'games_played': int(r['games_played']),
            'total_points': float(r['total_points'])
        })
    out[mgr] = rows

with open('/home/claude/work/franchise_leaders.json', 'w') as f:
    json.dump(out, f, separators=(',', ':'))

print('Managers:', len(out))
print('Total rows:', sum(len(v) for v in out.values()))
import os
print('File size KB:', os.path.getsize('/home/claude/work/franchise_leaders.json')/1024)

# sanity check one manager
sample_mgr = list(out.keys())[0]
print(sample_mgr, out[sample_mgr][:3])
