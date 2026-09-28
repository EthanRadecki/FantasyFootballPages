"""
STEP 6: Regenerate the five external data files (page_data.js,
network_data.js, winpct_data.js, trade_explorer_data.js,
trade_week_data.js) from the corrected metrics_final.csv, so the whole
trade-value.html page is consistent -- not just the Total QUAD toggle,
which was patched separately before these files were available.
"""
import pandas as pd
import json
import numpy as np

ACTIVE = ['Aidan Quigley','Andrew Root','Anthony Kelly','Baylen Slansky','Ben Castaldo',
          'Brandon Hancock','Carmine Pittelli Jr.','Charlie Gorman','Cole Maney',
          'Deniz Bileydi','Ethan Radecki','Max Malich','Quin Gegwich','Ryan P McQuaid']

metrics = pd.read_csv('/home/claude/trade_pipeline/metrics_final.csv')
metrics['got_players'] = metrics['got_players'].apply(json.loads)
metrics['gave_players'] = metrics['gave_players'].apply(json.loads)
metrics['multi'] = metrics['num_managers_in_group'] > 2

wr = pd.read_csv('weekly_rosters_bracket_only.csv')
player_pos = wr.drop_duplicates('Player').set_index('Player')['Position'].to_dict()

le = pd.read_csv('lineup_efficiency.csv')

def nz(v):
    return None if pd.isna(v) else round(float(v), 3)

# ============================================================
# 1. page_data.js: LEADERBOARD, *_SCALE, BEST_WORST, TRADES
# ============================================================
active_metrics = metrics[metrics['manager'].isin(ACTIVE)].copy()

def leaderboard_for(df):
    g = df.groupby('manager').agg(quad=('QUAD','mean'), n=('QUAD','count'))
    return {m: {'quad': round(r['quad'],3), 'n': int(r['n'])} for m, r in g.iterrows()}

LEADERBOARD = {'career': leaderboard_for(active_metrics)}
for s in sorted(active_metrics['season'].unique()):
    LEADERBOARD[str(s)] = leaderboard_for(active_metrics[active_metrics['season']==s])

def scale_for(col):
    return {'min': round(float(metrics[col].min()),3), 'max': round(float(metrics[col].max()),3)}

QUAD_SCALE = scale_for('QUAD')
TG_SCALE = scale_for('trade_grade')
RG_SCALE = scale_for('realized_gains')
FIT_SCALE = scale_for('fit_score')
NEC_SCALE = {'min': round(float(metrics['necessity_per_week'].min()),3), 'max': round(float(metrics['necessity_per_week'].max()),3)}

def best_worst_for(df):
    out = {}
    for m, g in df.groupby('manager'):
        best = g.loc[g['QUAD'].idxmax()]
        worst = g.loc[g['QUAD'].idxmin()]
        out[m] = {
            'best': {'got': best['got_players'], 'gave': best['gave_players'], 'quad': round(float(best['QUAD']),2)},
            'worst': {'got': worst['got_players'], 'gave': worst['gave_players'], 'quad': round(float(worst['QUAD']),2)},
        }
    return out

BEST_WORST = {'career': best_worst_for(active_metrics)}
for s in sorted(active_metrics['season'].unique()):
    BEST_WORST[str(s)] = best_worst_for(active_metrics[active_metrics['season']==s])

TRADES = []
for _, r in active_metrics.iterrows():
    TRADES.append({
        's': int(r['season']), 'm': r['manager'], 'got': r['got_players'], 'gave': r['gave_players'],
        'tg': round(float(r['trade_grade']),2), 'rg': round(float(r['realized_gains']),2),
        'fit': round(float(r['fit_score']),3), 'nec': nz(r['necessity_per_week']),
        'quad': round(float(r['QUAD']),2), 'multi': bool(r['multi'])
    })

with open('page_data.js','w') as f:
    f.write('var LEADERBOARD = ' + json.dumps(LEADERBOARD) + ';\n')
    f.write('var QUAD_SCALE = ' + json.dumps(QUAD_SCALE) + ';\n')
    f.write('var TG_SCALE = ' + json.dumps(TG_SCALE) + ';\n')
    f.write('var RG_SCALE = ' + json.dumps(RG_SCALE) + ';\n')
    f.write('var FIT_SCALE = ' + json.dumps(FIT_SCALE) + ';\n')
    f.write('var NEC_SCALE = ' + json.dumps(NEC_SCALE) + ';\n')
    f.write('var BEST_WORST = ' + json.dumps(BEST_WORST) + ';\n')
    f.write('var TRADES = ' + json.dumps(TRADES) + ';\n')
print("page_data.js written:", len(TRADES), "trade-sides")

# ============================================================
# 2. network_data.js: NETWORK_DATA (active managers only)
# ============================================================
nodes = [{'id': m, 'trades': int((active_metrics['manager']==m).sum())} for m in sorted(active_metrics['manager'].unique())]

edges = []
managers_sorted = sorted(active_metrics['manager'].unique())
for i, a in enumerate(managers_sorted):
    groups_a = set(active_metrics[active_metrics['manager']==a]['group_id'])
    for b in managers_sorted[i+1:]:
        groups_b = set(active_metrics[active_metrics['manager']==b]['group_id'])
        shared = groups_a & groups_b
        if not shared:
            continue
        rows_a = active_metrics[(active_metrics['group_id'].isin(shared))&(active_metrics['manager']==a)]
        rows_b = active_metrics[(active_metrics['group_id'].isin(shared))&(active_metrics['manager']==b)]
        # netDiff: avg QUAD across their shared trades, a minus b.
        # Positive means a has generally come out ahead, negative means b.
        net_diff = round(float(rows_a['QUAD'].mean() - rows_b['QUAD'].mean()), 3)
        shared_rows = active_metrics[active_metrics['group_id'].isin(shared)]
        positions = {}
        for _, r in shared_rows.iterrows():
            for p in r['got_players'] + r['gave_players']:
                pos = player_pos.get(p, 'UNK')
                positions[pos] = positions.get(pos, 0) + 1
        seasons = sorted(int(s) for s in shared_rows['season'].unique())
        edges.append({'a': a, 'b': b, 'n': len(shared), 'netDiff': net_diff, 'positions': positions, 'seasons': seasons})

NETWORK_DATA = {'nodes': nodes, 'edges': edges}
with open('network_data.js','w') as f:
    f.write('var NETWORK_DATA = ' + json.dumps(NETWORK_DATA) + ';\n')
print("network_data.js written:", len(edges), "edges")

# ============================================================
# 3. winpct_data.js: WINPCT_DATA (win% from lineup_efficiency.csv, avgQuad from trades)
# ============================================================
win_rate = le[le['Manager'].isin(ACTIVE)].groupby('Manager')['Outcome'].apply(lambda s: round((s=='Win').mean()*100,1)).reset_index()
win_rate.columns = ['manager','winPct']
games = le[le['Manager'].isin(ACTIVE)].groupby('Manager').size().reset_index(name='games')
trade_counts = active_metrics.groupby('manager').size().reset_index(name='trades')
avg_quad = active_metrics.groupby('manager')['QUAD'].mean().round(3).reset_index()
avg_quad.columns = ['manager','avgQuad']

wp = win_rate.merge(games, left_on='manager', right_on='Manager').merge(trade_counts, on='manager').merge(avg_quad, on='manager')
wp = wp.sort_values('winPct', ascending=False)
WINPCT_DATA = [{'m': r['manager'], 'winPct': r['winPct'], 'games': int(r['games']), 'trades': int(r['trades']), 'avgQuad': r['avgQuad']} for _, r in wp.iterrows()]

with open('winpct_data.js','w') as f:
    f.write('var WINPCT_DATA = ' + json.dumps(WINPCT_DATA) + ';\n')
print("winpct_data.js written:", len(WINPCT_DATA), "managers")

# ============================================================
# 4. trade_explorer_data.js: TRADE_NODES (full historical roster, incl. Thomas Sullivan / William Serafin)
# ============================================================
TRADE_NODES = []
for gid, g in metrics.groupby('group_id'):
    row0 = g.iloc[0]
    managers_list = []
    positions = set()
    for _, r in g.iterrows():
        managers_list.append({
            'm': r['manager'], 'got': r['got_players'], 'gave': r['gave_players'],
            'tg': round(float(r['trade_grade']),2), 'rg': round(float(r['realized_gains']),2),
            'fit': round(float(r['fit_score']),3), 'nec': nz(r['necessity_per_week']),
            'quad': round(float(r['QUAD']),2)
        })
        for p in r['got_players'] + r['gave_players']:
            positions.add(player_pos.get(p, 'UNK'))
    TRADE_NODES.append({
        'gid': int(gid), 'season': int(row0['season']), 'sp': int(row0['scoring_period']),
        'multi': bool(row0['multi']), 'managers': managers_list, 'positions': sorted(positions)
    })

with open('trade_explorer_data.js','w') as f:
    f.write('var TRADE_NODES = ' + json.dumps(TRADE_NODES) + ';\n')
print("trade_explorer_data.js written:", len(TRADE_NODES), "trade groups")

# ============================================================
# 5. trade_week_data.js: TRADE_WEEK_DATA (full historical, includes week number)
# ============================================================
def fmt_players(players):
    return '[' + ', '.join(json.dumps(p) for p in players) + ']'

lines = []
for _, r in metrics.iterrows():
    lines.append(
        '{g:%d,s:%d,wk:%d,m:%s,multi:%s,got:%s,gave:%s,tg:%s,rg:%s,fit:%s,nec:%s,quad:%s}' % (
            int(r['group_id']), int(r['season']), int(r['scoring_period']), json.dumps(r['manager']),
            'true' if r['multi'] else 'false', fmt_players(r['got_players']), fmt_players(r['gave_players']),
            round(float(r['trade_grade']),3), round(float(r['realized_gains']),3), round(float(r['fit_score']),3),
            'null' if pd.isna(r['necessity_per_week']) else round(float(r['necessity_per_week']),3),
            round(float(r['QUAD']),3)
        )
    )
with open('trade_week_data.js','w') as f:
    f.write('var TRADE_WEEK_DATA = [' + ','.join(lines) + '];\n')
print("trade_week_data.js written:", len(lines), "trade-sides")
