"""
STEP 4: Compute Trade Grade, Realized Gains, Fit Score, Necessity Score
for every (group_id, manager) trade-side.
"""
import pandas as pd
import json
import numpy as np
from playoff_weights import build_week_weight_lookup

rosters = pd.read_csv('/mnt/user-data/uploads/weekly_rosters_bracket_only.csv')
baseline = pd.read_csv('/mnt/user-data/uploads/position_baseline.csv')
trade_universe = pd.read_csv('/home/claude/trade_pipeline/trade_universe.csv')
player_stints = pd.read_csv('/home/claude/trade_pipeline/player_stints_fixed.csv')  # FIX: forfeit-corrected, see rebuild_player_stints.py

# FIX: weekly_rosters_bracket_only.csv correctly drops consolation-bracket
# weeks, but a forfeited lineup (scored 0, manager never set a real
# lineup) is technically still a "bracket" week for that manager and
# survives this filter. That's the same exclusion already applied on
# the Lineup Efficiency page (Excluded_From_Average) -- apply it here
# too, since a forfeit week's 0-point score shouldn't be able to drag
# down a traded player's realized/total z just because the receiving
# manager never set a lineup that week.
lineup_eff = pd.read_csv('/mnt/user-data/uploads/lineup_efficiency.csv')
forfeited_weeks = set(zip(
    lineup_eff.loc[lineup_eff['Forfeited_Lineup'], 'Season'],
    lineup_eff.loc[lineup_eff['Forfeited_Lineup'], 'Week'],
    lineup_eff.loc[lineup_eff['Forfeited_Lineup'], 'Manager'],
))
rosters = rosters[~rosters.apply(lambda r: (r['Season'], r['Week'], r['Manager']) in forfeited_weeks, axis=1)]

WEEK_WEIGHTS = build_week_weight_lookup(rosters)
NECESSITY_SHRINKAGE_K = 3  # shrinks low-sample necessity toward 0; higher k = more conservative

rosters = rosters.merge(baseline, on=['Season','Week','Position'], how='left')
rosters['z'] = (rosters['Points'] - rosters['pos_mean']) / rosters['pos_std']
rosters['z'] = rosters['z'].replace([np.inf,-np.inf], np.nan)
rosters['week_weight'] = rosters.apply(lambda r: WEEK_WEIGHTS.get((r['Season'], r['Week']), 1.0), axis=1)
rosters['weighted_z'] = rosters['z'] * rosters['week_weight']

# lookup: (group_id, player_id) -> total_z, realized_z, weeks_rostered (from receiving manager's perspective)
stint_lookup = player_stints.set_index(['group_id','player_id'])[['total_z','realized_z','weeks_rostered','position']].to_dict('index')

NECESSITY_ELIGIBLE = {'RB','WR','TE','K','D/ST'}  # FIX: was {'RB','WR','TE'} only,
# meaning necessity never evaluated K/D-ST acquisitions at all -- a trade
# for a kicker or D/ST always defaulted to neutral (0) necessity regardless
# of whether the acquiring manager actually needed it. Real impact is
# partial: most managers only roster one K/D-ST at a time, so there's
# often no bench alternative to compare against even now -- but roughly
# 19% of manager-weeks carry a bench K, and 34% carry a bench D/ST, so
# this now produces a real signal in those cases instead of always
# defaulting to neutral.

def necessity_for_player(season, manager, player_id, start_week, weeks_rostered):
    """Sum of (acquired points - best genuinely-benched pre-existing alt at matching slot) across the stint."""
    if weeks_rostered == 0:
        return 0.0, 0
    pre_trade_ids = set(rosters[(rosters.Season==season)&(rosters.Manager==manager)&(rosters.Week==start_week-1)&
                                 (rosters.Position.isin(NECESSITY_ELIGIBLE))]['Player_ID']) - {player_id}
    total_diff = 0.0
    weeks_compared = 0
    for wk in range(start_week, start_week+weeks_rostered):
        acq_row = rosters[(rosters.Season==season)&(rosters.Manager==manager)&(rosters.Week==wk)&(rosters.Player_ID==player_id)]
        if len(acq_row)==0: continue
        slot = acq_row['Slot'].values[0]
        pos = acq_row['Position'].values[0]
        if pos not in NECESSITY_ELIGIBLE:
            continue  # necessity only meaningful for RB/WR/TE bench-competition slots
        wk_roster = rosters[(rosters.Season==season)&(rosters.Manager==manager)&(rosters.Week==wk)&
                             (rosters.Player_ID.isin(pre_trade_ids))&(rosters.Slot=='BE')]
        if slot == 'RB/WR/TE':
            alt_pool = wk_roster
        else:
            alt_pool = wk_roster[wk_roster.Position==pos]
        if len(alt_pool)==0: continue
        best = alt_pool.loc[alt_pool['Points'].idxmax()]
        wt = WEEK_WEIGHTS.get((season, wk), 1.0)
        total_diff += (acq_row['Points'].values[0] - best['Points']) * wt
        weeks_compared += 1
    return total_diff, weeks_compared

def fit_score(season, manager, positions_affected, start_week):
    """Team's avg z at affected positions, before (weeks 1 to start_week-1) vs after (start_week to 17)."""
    if not positions_affected or start_week <= 1:
        return 0.0
    scores = []
    for pos in positions_affected:
        before = rosters[(rosters.Season==season)&(rosters.Manager==manager)&(rosters.Position==pos)&(rosters.Week<start_week)]
        after = rosters[(rosters.Season==season)&(rosters.Manager==manager)&(rosters.Position==pos)&(rosters.Week>=start_week)]
        if len(before)==0 or len(after)==0: continue
        b = before.groupby('Week')['weighted_z'].mean().mean()
        a = after.groupby('Week')['weighted_z'].mean().mean()
        if pd.notna(b) and pd.notna(a):
            scores.append(a-b)
    return np.mean(scores) if scores else 0.0

results = []
for _, row in trade_universe.iterrows():
    gid, season, sp, manager = row['group_id'], row['season'], row['scoring_period'], row['manager']
    got_ids = json.loads(row['got_player_ids'])
    gave_ids = json.loads(row['gave_player_ids'])

    got_total_z = sum(stint_lookup.get((gid,pid),{}).get('total_z',0) or 0 for pid in got_ids)
    got_realized_z = sum(stint_lookup.get((gid,pid),{}).get('realized_z',0) or 0 for pid in got_ids)
    gave_total_z = sum(stint_lookup.get((gid,pid),{}).get('total_z',0) or 0 for pid in gave_ids)
    gave_realized_z = sum(stint_lookup.get((gid,pid),{}).get('realized_z',0) or 0 for pid in gave_ids)

    trade_grade = got_total_z - gave_total_z
    realized_gains = got_realized_z - gave_realized_z

    # necessity: sum across all received players
    nec_total, nec_weeks = 0.0, 0
    positions_affected = set()
    for pid in got_ids:
        info = stint_lookup.get((gid,pid))
        if not info or info['weeks_rostered']==0: continue
        positions_affected.add(info['position'])
        diff, wks = necessity_for_player(season, manager, pid, sp, info['weeks_rostered'])
        nec_total += diff
        nec_weeks += wks

    fit = fit_score(season, manager, positions_affected, sp)

    results.append({
        'group_id': gid, 'season': season, 'scoring_period': sp, 'manager': manager,
        'num_managers_in_group': row['num_managers_in_group'],
        'got_players': row['got_players'], 'gave_players': row['gave_players'],
        'trade_grade': trade_grade, 'realized_gains': realized_gains,
        'necessity_raw': nec_total, 'necessity_weeks': nec_weeks,
        'necessity_per_week': nec_total/(nec_weeks + NECESSITY_SHRINKAGE_K) if nec_weeks>0 else np.nan,
        'fit_score': fit
    })

metrics = pd.DataFrame(results)
metrics.to_csv('/home/claude/trade_pipeline/metrics_raw.csv', index=False)
print(f"Computed metrics for {len(metrics)} trade-sides\n")
print(metrics[['trade_grade','realized_gains','necessity_per_week','fit_score']].describe())
