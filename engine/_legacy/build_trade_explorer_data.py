"""
Trade Explorer data: one node per real trade group, with every manager's
full metric breakdown nested inside. Used for the interactive bipartite
trade-explorer graph (manager <-> trade nodes).
"""
import pandas as pd
import json

metrics = pd.read_csv('metrics_final.csv')
# NOTE: Trade Explorer intentionally does NOT exclude Sullivan/Serafin.
# They're excluded from leaderboard-style visuals (Manager Leaderboard, Trade
# Network, Win%, Most Traded) since those rank ongoing manager performance,
# but Trade Explorer's whole purpose is showing what actually happened in a
# specific trade -- hiding a real participant there misrepresents history.

trade_universe = pd.read_csv('trade_universe.csv')
player_stints = pd.read_csv('player_stints.csv')
pos_lookup = player_stints.set_index(['group_id','player_id'])['position'].to_dict()

nodes = []
for gid, g in metrics.groupby('group_id'):
    season = int(g['season'].iloc[0])
    sp = int(g['scoring_period'].iloc[0])
    n_managers = int(g['num_managers_in_group'].iloc[0])

    # positions involved, from trade_universe's got_player_ids for this group
    tu_group = trade_universe[trade_universe.group_id==gid]
    positions = set()
    for _, row in tu_group.iterrows():
        for pid in json.loads(row['got_player_ids']):
            pos = pos_lookup.get((gid, pid))
            if pos and isinstance(pos, str):
                positions.add(pos)

    managers = []
    for _, r in g.iterrows():
        managers.append({
            'm': r['manager'],
            'got': json.loads(r['got_players']),
            'gave': json.loads(r['gave_players']),
            'tg': round(r['trade_grade'],2),
            'rg': round(r['realized_gains'],2),
            'fit': round(r['fit_score'],3),
            'nec': None if pd.isna(r['necessity_per_week']) else round(r['necessity_per_week'],2),
            'quad': round(r['QUAD'],2),
        })

    nodes.append({
        'gid': int(gid),
        'season': season,
        'sp': sp,
        'multi': n_managers >= 3,
        'managers': managers,
        'positions': sorted(positions),
    })

with open('trade_explorer_data.js', 'w') as f:
    f.write('var TRADE_NODES = ' + json.dumps(nodes) + ';\n')

print(f"Trade nodes: {len(nodes)}")
print(f"Multi-team: {sum(1 for n in nodes if n['multi'])}")
print("Sample:", json.dumps(nodes[0], indent=2))
