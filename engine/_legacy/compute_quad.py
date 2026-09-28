"""
STEP 5: Z-score each metric across the population, combine into QUAD.
"""
import pandas as pd
import numpy as np
import json

metrics = pd.read_csv('/home/claude/trade_pipeline/metrics_raw.csv')

def zscore(s):
    return (s - s.mean()) / s.std()

metrics['z_trade_grade'] = zscore(metrics['trade_grade'])
metrics['z_realized_gains'] = zscore(metrics['realized_gains'])
metrics['z_fit_score'] = zscore(metrics['fit_score'])
metrics['z_necessity'] = zscore(metrics['necessity_per_week']).fillna(0)  # missing -> treated as average

WEIGHTS = {'z_realized_gains': 0.35, 'z_trade_grade': 0.30, 'z_fit_score': 0.20, 'z_necessity': 0.15}

metrics['quad_raw'] = sum(metrics[k]*w for k,w in WEIGHTS.items())
metrics['QUAD_unadjusted'] = zscore(metrics['quad_raw'])  # re-standardize the composite

# FIX: low-stakes dampener. Some trades are effectively equivalent to two
# independent waiver moves that just happened to be bundled into one
# transaction (e.g. a struggling RB for a kicker) -- these shouldn't be
# able to produce a QUAD that looks as meaningful as a genuine trade,
# regardless of which side the raw math favors. Flagged specifically
# when one side of the exchange, once K/D-ST pieces are removed, is
# empty -- i.e. that side of the deal was nothing but K/D-ST. This is
# deliberately narrower than "K/D-ST appears anywhere," since a
# throwaway D/ST tacked onto an otherwise real multi-player trade
# shouldn't dampen the whole thing.
LOW_STAKES_MULTIPLIER = 0.15

_rosters_for_pos = pd.read_csv('/mnt/user-data/uploads/weekly_rosters_bracket_only.csv')
PLAYER_POSITION = _rosters_for_pos.drop_duplicates('Player').set_index('Player')['Position'].to_dict()

def is_low_stakes(row):
    got = json.loads(row['got_players'])
    gave = json.loads(row['gave_players'])
    got_real = [p for p in got if PLAYER_POSITION.get(p,'') not in ('K','D/ST')]
    gave_real = [p for p in gave if PLAYER_POSITION.get(p,'') not in ('K','D/ST')]
    return (len(got)>0 and len(got_real)==0) or (len(gave)>0 and len(gave_real)==0)

metrics['low_stakes'] = metrics.apply(is_low_stakes, axis=1)
metrics['QUAD'] = np.where(metrics['low_stakes'], metrics['QUAD_unadjusted']*LOW_STAKES_MULTIPLIER, metrics['QUAD_unadjusted'])

print(f"Low-stakes trade-sides flagged: {metrics['low_stakes'].sum()} of {len(metrics)}")

metrics.to_csv('/home/claude/trade_pipeline/metrics_final.csv', index=False)

print("QUAD distribution:")
print(metrics['QUAD'].describe())

print("\n=== TOP 10 BEST TRADE-SIDES (by QUAD) ===")
top = metrics.sort_values('QUAD', ascending=False).head(10)
for _, r in top.iterrows():
    print(f"S{r.season} SP{r.scoring_period} | {r.manager}: got {r.got_players} for {r.gave_players} | QUAD={r.QUAD:.2f} (TG={r.trade_grade:.1f}, RG={r.realized_gains:.1f}, Fit={r.fit_score:.2f}, Nec/wk={r.necessity_per_week:.1f})")

print("\n=== BOTTOM 10 WORST TRADE-SIDES (by QUAD) ===")
bottom = metrics.sort_values('QUAD').head(10)
for _, r in bottom.iterrows():
    print(f"S{r.season} SP{r.scoring_period} | {r.manager}: got {r.got_players} for {r.gave_players} | QUAD={r.QUAD:.2f} (TG={r.trade_grade:.1f}, RG={r.realized_gains:.1f}, Fit={r.fit_score:.2f}, Nec/wk={r.necessity_per_week:.1f})")
