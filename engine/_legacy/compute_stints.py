"""
STEP 3: For every player RECEIVED by a manager in a trade group, compute their
real stint with that manager (from the trade's scoring period through the next
event or season end), and derive Total_Z (Trade Grade component) and 
Realized_Z (Realized Gains component) from actual weekly production.
"""
import pandas as pd
import json
import numpy as np
from playoff_weights import build_week_weight_lookup

rosters = pd.read_csv('/mnt/user-data/uploads/weekly_rosters_bracket_only.csv')
baseline = pd.read_csv('/mnt/user-data/uploads/position_baseline.csv')
trade_universe = pd.read_csv('/home/claude/trade_pipeline/trade_universe.csv')

WEEK_WEIGHTS = build_week_weight_lookup(rosters)

# merge z-scores into rosters once, for speed
rosters = rosters.merge(baseline, on=['Season','Week','Position'], how='left')
rosters['z'] = (rosters['Points'] - rosters['pos_mean']) / rosters['pos_std']
rosters['z'] = rosters['z'].replace([np.inf,-np.inf], np.nan)
rosters['week_weight'] = rosters.apply(lambda r: WEEK_WEIGHTS.get((r['Season'], r['Week']), 1.0), axis=1)
rosters['weighted_z'] = rosters['z'] * rosters['week_weight']

roster_idx = rosters.set_index(['Season','Player_ID','Manager']).sort_index()

def get_stint(season, player_id, manager, start_week):
    """Consecutive weeks (from start_week onward) where this manager owns this player."""
    try:
        sub = roster_idx.loc[(season, player_id, manager)]
    except KeyError:
        return pd.DataFrame()
    if isinstance(sub, pd.Series):
        sub = sub.to_frame().T
    sub = sub[sub['Week'] >= start_week].sort_values('Week')
    if len(sub)==0:
        return sub
    # must be consecutive from start_week (no gap = still on roster each week)
    weeks = sub['Week'].tolist()
    consecutive = [weeks[0]]
    for w in weeks[1:]:
        if w == consecutive[-1] + 1:
            consecutive.append(w)
        else:
            break
    return sub[sub['Week'].isin(consecutive)]

# player -> (season, scoring_period as start week, receiving manager, group_id) lookup
records = []
for _, row in trade_universe.iterrows():
    got_ids = json.loads(row['got_player_ids'])
    got_names = json.loads(row['got_players'])
    for pid, pname in zip(got_ids, got_names):
        stint = get_stint(row['season'], pid, row['manager'], row['scoring_period'])
        total_z = stint['weighted_z'].sum() if len(stint) else 0.0
        realized_z = stint[stint['Started']==True]['weighted_z'].sum() if len(stint) else 0.0
        weeks_rostered = len(stint)
        position = stint['Position'].iloc[0] if len(stint) else None
        records.append({
            'group_id': row['group_id'], 'season': row['season'], 'scoring_period': row['scoring_period'],
            'receiving_manager': row['manager'], 'player_id': pid, 'player': pname,
            'position': position, 'weeks_rostered': weeks_rostered,
            'total_z': total_z, 'realized_z': realized_z
        })

player_stints = pd.DataFrame(records)
player_stints.to_csv('/home/claude/trade_pipeline/player_stints.csv', index=False)
print(f"Computed stints for {len(player_stints)} received-player instances")
print(player_stints.head(10).to_string())
print(f"\nMissing/zero stints (player never appears on receiving manager's roster after trade): {(player_stints.weeks_rostered==0).sum()}")
