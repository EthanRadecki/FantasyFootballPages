"""
STEP 1-2: Build the clean, linked trade universe.
- Reversal exclusion: pairwise net-cancellation within same season+scoring period
- Multi-team linking: same scoring period, linked via shared player OR complete pairwise clique
Output: trade_groups.csv -- one row per (logical trade group, manager) with their NET gives/receives
"""
import pandas as pd
from itertools import combinations
import json
from collections import Counter

df = pd.read_csv('/mnt/user-data/uploads/trades_mapped.csv')

def net_all_cancel(sub):
    first_from, last_to = {}, {}
    for _, r in sub.sort_values('Proposed_Date_Unix_ms').iterrows():
        if r.Player not in first_from: first_from[r.Player] = r.From_Manager
        last_to[r.Player] = r.To_Manager
    return all(first_from[p]==last_to[p] for p in first_from) if first_from else False

# STEP 1: reversal exclusion
excluded_ids = set()
for (season, sp), period_df in df.groupby(['Season','Scoring_Period']):
    mgr_pairs = {}
    for tid, g in period_df.groupby('Transaction_ID'):
        mgrs = frozenset(set(g.From_Manager) | set(g.To_Manager))
        if len(mgrs) == 2:
            mgr_pairs.setdefault(mgrs, []).append(tid)
    for mgrs, tids in mgr_pairs.items():
        if len(tids) < 2: continue
        sub = period_df[period_df.Transaction_ID.isin(tids)]
        if net_all_cancel(sub):
            excluded_ids.update(tids)

print(f"Reversal transactions excluded: {len(excluded_ids)}")
remaining = df[~df.Transaction_ID.isin(excluded_ids)].copy()
print(f"Remaining real transactions: {remaining['Transaction_ID'].nunique()}")

# STEP 2: multi-team linking within each scoring period
groups_output = []
group_id_counter = 0

for (season, sp), period_df in remaining.groupby(['Season','Scoring_Period']):
    tids = period_df['Transaction_ID'].unique().tolist()
    players_map = {tid: set(period_df[period_df.Transaction_ID==tid]['Player']) for tid in tids}
    mgrs_map = {tid: frozenset(set(period_df[period_df.Transaction_ID==tid]['From_Manager']) | set(period_df[period_df.Transaction_ID==tid]['To_Manager'])) for tid in tids}

    parent = {tid: tid for tid in tids}
    def find(x):
        while parent[x]!=x: x=parent[x]
        return x
    def union(a,b):
        ra,rb=find(a),find(b)
        if ra!=rb: parent[ra]=rb

    # link via shared player
    for i, t1 in enumerate(tids):
        for t2 in tids[i+1:]:
            if players_map[t1] & players_map[t2]:
                union(t1,t2)

    # link via complete triangle (2-manager transactions only)
    two_mgr_tids = [t for t in tids if len(mgrs_map[t])==2]
    for i, t1 in enumerate(two_mgr_tids):
        for t2 in two_mgr_tids[i+1:]:
            for t3 in two_mgr_tids:
                if t3 in (t1,t2): continue
                trio = [t1,t2,t3]
                all_mgrs = mgrs_map[t1] | mgrs_map[t2] | mgrs_map[t3]
                if len(all_mgrs) != 3: continue
                pairs_needed = set(combinations(sorted(all_mgrs),2))
                pairs_have = set(tuple(sorted(mgrs_map[t])) for t in trio)
                if pairs_needed == pairs_have:
                    union(t1,t2); union(t2,t3)

    groups = {}
    for tid in tids:
        groups.setdefault(find(tid), []).append(tid)

    for g in groups.values():
        group_id_counter += 1
        group_tids = g
        group_sub = period_df[period_df.Transaction_ID.isin(group_tids)]
        all_mgrs = set(group_sub.From_Manager) | set(group_sub.To_Manager)

        # compute NET position per manager: what they permanently gave vs received.
        # Uses COUNT-based cancellation (not set intersection) so a player who
        # bounces back and forth multiple times before landing somewhere real
        # nets out correctly instead of being wiped out entirely.
        for mgr in all_mgrs:
            gave = group_sub[group_sub.From_Manager==mgr][['Player','Player_ID','To_Manager']].rename(columns={'To_Manager':'Counterparty'})
            got = group_sub[group_sub.To_Manager==mgr][['Player','Player_ID','From_Manager']].rename(columns={'From_Manager':'Counterparty'})

            gave_counts = Counter(gave['Player_ID'].tolist())
            got_counts = Counter(got['Player_ID'].tolist())
            all_pids = set(gave_counts) | set(got_counts)

            net_gave_ids, net_got_ids = [], []
            for pid in all_pids:
                net = got_counts.get(pid,0) - gave_counts.get(pid,0)
                if net > 0:
                    net_got_ids.append(pid)
                elif net < 0:
                    net_gave_ids.append(pid)
                # net == 0 -> fully cancels, excluded entirely (genuine pass-through)

            # pick one representative row per player_id for the display name
            gave_lookup = gave.drop_duplicates('Player_ID').set_index('Player_ID')['Player']
            got_lookup = got.drop_duplicates('Player_ID').set_index('Player_ID')['Player']
            net_gave_names = [gave_lookup[pid] for pid in net_gave_ids]
            net_got_names = [got_lookup[pid] for pid in net_got_ids]

            if len(net_gave_ids)==0 and len(net_got_ids)==0:
                continue  # this manager was fully a pass-through, no net position

            earliest_ts = group_sub['Proposed_Date_Unix_ms'].min()

            groups_output.append({
                'group_id': group_id_counter,
                'season': season,
                'scoring_period': sp,
                'manager': mgr,
                'num_transactions_in_group': len(group_tids),
                'num_managers_in_group': len(all_mgrs),
                'gave_player_ids': json.dumps(net_gave_ids),
                'gave_players': json.dumps(net_gave_names),
                'got_player_ids': json.dumps(net_got_ids),
                'got_players': json.dumps(net_got_names),
                'earliest_ts': earliest_ts,
            })

trade_universe = pd.DataFrame(groups_output)
trade_universe.to_csv('/home/claude/trade_pipeline/trade_universe.csv', index=False)
print(f"\nTotal logical trade-sides (manager x group): {len(trade_universe)}")
print(f"Total logical trade groups: {trade_universe['group_id'].nunique()}")
print(f"Multi-team groups (3+ managers): {(trade_universe.groupby('group_id')['num_managers_in_group'].first() >= 3).sum()}")
