"""
Rebuild player_stints.csv with the forfeit-week fix applied.

The original player_stints.csv (Step 3, script not available) computes,
for each (group_id, receiving_manager, player_id): the player's weighted
position-relative z-score summed across every week they were rostered by
the receiving manager starting at the trade week (total_z, any slot
including bench), and the same sum restricted to weeks they were actually
started (realized_z). weeks_rostered is just the count of valid weeks in
that span.

Reverse-engineered and verified against the real data: recomputing
Roschon Johnson's stint (group_id 125) from weekly_rosters_bracket_only.csv
+ position_baseline.csv + playoff_weights.py reproduces total_z=-4.869388
to three decimal places, confirming this replication is faithful.

The bug: weekly_rosters_bracket_only.csv correctly excludes consolation
weeks, but not forfeited lineups (a forfeit is technically still a
"bracket" week for that manager, just with a botched 0-point lineup).
Removing forfeited weeks before this computation runs closes that gap
at the actual source, rather than patching around it downstream.
"""
import pandas as pd
import numpy as np
from playoff_weights import build_week_weight_lookup

rosters = pd.read_csv('weekly_rosters_bracket_only.csv')
baseline = pd.read_csv('position_baseline.csv')
old_stints = pd.read_csv('player_stints.csv')
lineup_eff = pd.read_csv('lineup_efficiency.csv')

# FIX: exclude forfeited weeks, same exclusion already applied on the
# Lineup Efficiency page. weekly_rosters_bracket_only.csv doesn't know
# about forfeits, only about consolation-bracket exclusion.
forfeited_weeks = set(zip(
    lineup_eff.loc[lineup_eff['Forfeited_Lineup'], 'Season'],
    lineup_eff.loc[lineup_eff['Forfeited_Lineup'], 'Week'],
    lineup_eff.loc[lineup_eff['Forfeited_Lineup'], 'Manager'],
))
rosters = rosters[~rosters.apply(lambda r: (r['Season'], r['Week'], r['Manager']) in forfeited_weeks, axis=1)].copy()

WEEK_WEIGHTS = build_week_weight_lookup(rosters)
rosters = rosters.merge(baseline, on=['Season','Week','Position'], how='left')
rosters['z'] = (rosters['Points'] - rosters['pos_mean']) / rosters['pos_std']
rosters['z'] = rosters['z'].replace([np.inf,-np.inf], np.nan)
rosters['week_weight'] = rosters.apply(lambda r: WEEK_WEIGHTS.get((r['Season'], r['Week']), 1.0), axis=1)
rosters['weighted_z'] = rosters['z'] * rosters['week_weight']

def recompute_stint(row):
    season, sp, manager, player_id = row['season'], row['scoring_period'], row['receiving_manager'], row['player_id']
    stint = rosters[(rosters.Season==season)&(rosters.Manager==manager)&(rosters.Player_ID==player_id)&
                    (rosters.Week>=sp)].sort_values('Week')
    if len(stint)==0:
        return pd.Series({'weeks_rostered':0, 'total_z':0.0, 'realized_z':0.0})
    total_z = stint['weighted_z'].sum()
    realized_z = stint[stint['Slot']!='BE']['weighted_z'].sum()
    return pd.Series({'weeks_rostered': len(stint), 'total_z': total_z, 'realized_z': realized_z})

new_stints = old_stints.copy()
recomputed = old_stints.apply(recompute_stint, axis=1)
new_stints[['weeks_rostered','total_z','realized_z']] = recomputed
new_stints['weeks_rostered'] = new_stints['weeks_rostered'].astype(int)

new_stints.to_csv('player_stints_fixed.csv', index=False)

# Report what changed
diff = old_stints.copy()
diff['new_total_z'] = new_stints['total_z']
diff['new_weeks_rostered'] = new_stints['weeks_rostered']
diff['delta'] = diff['new_total_z'] - diff['total_z']
changed = diff[diff['delta'].abs() > 0.001]
print(f"Rebuilt {len(new_stints)} stints. {len(changed)} changed by the forfeit fix.")
print(changed[['group_id','receiving_manager','player','weeks_rostered','new_weeks_rostered','total_z','new_total_z','delta']].to_string(index=False))
