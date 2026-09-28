"""
generate_position_impact.py

Builds data/position_impact_data.json for a unified "how much does each
position matter" comparison page, covering QB, RB, WR, TE, K, and D/ST
together (a generalization of the D/ST-only analysis in
generate_dst_impact.py, which stays in place as its own deeper dive).

For every position, computes:
  - flip rate: remove that position's started points from both teams in
    every real matchup, recheck the winner, see how often it changes.
  - week-to-week predictability (coefficient of variation).
  - draft-vs-waiver PPG by round, using the "Nth pick at this position"
    convention (1st for QB/TE/K/D-ST, 2nd for RB/WR -- see NTH_PICK below
    for why: nearly every manager takes their RB1/WR1 in the first couple
    rounds regardless of philosophy, so the 2nd RB/WR is where actual
    draft-capital philosophy actually diverges; for QB/TE/K/D-ST there's
    only ever one pick that matters in the same way).
  - draft capital by manager by year (which round they took their Nth
    pick at that position each season), with a career average.
  - PPG-vs-win% and draft-round-vs-win% correlations.
  - net games gained/lost per manager (removing the position would have
    flipped some of their actual wins into losses and vice versa).

INPUTS (same folder as this script):
  - matchup_data.csv
  - weekly_rosters_clean.csv
  - draft_history_all_positions.csv

OUTPUT:
  - position_impact_data.json (place in pages/data/ alongside the new page)

Run:  python3 generate_position_impact.py
"""

import csv
import json
from collections import defaultdict

MATCHUP_CSV = 'matchup_data.csv'
ROSTERS_CSV = 'weekly_rosters_clean.csv'
DRAFT_CSV = 'draft_history_all_positions.csv'
WAIVER_STINTS_CSV = 'waiver_stints_full.csv'
TRADE_STINTS_CSV = 'player_stints.csv'
OUTPUT_JSON = 'position_impact_data.json'

EXCLUDED_MANAGERS = {'Thomas Sullivan', 'William Serafin'}
ALIAS = {'Carmine Pittelli': 'Carmine Pittelli Jr.', 'Ryan McQuaid': 'Ryan P McQuaid'}
POSITIONS = ['QB', 'RB', 'WR', 'TE', 'K', 'D/ST']
NTH_PICK = {'QB': 1, 'TE': 1, 'K': 1, 'D/ST': 1, 'RB': 2, 'WR': 2}


def canon(name):
    return ALIAS.get(name, name)


def matchup_week_to_num(season, week_label):
    if week_label.startswith('Week'):
        return int(week_label.replace('Week ', ''))
    n = int(week_label.replace('Playoff Round ', ''))
    mapping = {1: 14, 2: 15, 3: 16, 4: 17} if season in (2020, 2021) else {1: 15, 2: 16, 3: 17}
    return mapping.get(n)


def is_valid_game_row(row):
    return row['Week'].startswith('Week') or row['Is_Playoff'] == 'Yes'


def _pearson(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sx = sum((x - mx) ** 2 for x in xs) ** 0.5
    sy = sum((y - my) ** 2 for y in ys) ** 0.5
    return cov / (sx * sy) if sx and sy else 0


def _linreg(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    denom = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denom if denom else 0
    intercept = my - slope * mx
    return slope, intercept


# ── Load shared source data once ─────────────────────────────────────────
def load_rosters():
    with open(ROSTERS_CSV) as f:
        return list(csv.DictReader(f))


def load_matchups():
    rows = []
    with open(MATCHUP_CSV) as f:
        for row in csv.DictReader(f):
            if row['Team_Name'] in EXCLUDED_MANAGERS or row['Opponent_Name'] in EXCLUDED_MANAGERS:
                continue
            if not is_valid_game_row(row):
                continue
            rows.append(row)
    # Fix the one known score/outcome transposition bug (same as generate_dst_impact.py)
    for row in rows:
        ts, os_ = float(row['Team_Score']), float(row['Opponent_Score'])
        if row['Outcome'] == 'Win' and ts <= os_:
            row['Team_Score'], row['Opponent_Score'] = row['Opponent_Score'], row['Team_Score']
        elif row['Outcome'] == 'Loss' and ts >= os_:
            row['Team_Score'], row['Opponent_Score'] = row['Opponent_Score'], row['Team_Score']
    return rows


def dedupe_games(rows):
    seen = set()
    unique = []
    for row in rows:
        season = int(row['Season_Year'])
        wk = matchup_week_to_num(season, row['Week'])
        gid = (season, wk, tuple(sorted([row['Team_Name'], row['Opponent_Name']])))
        if gid in seen:
            continue
        seen.add(gid)
        unique.append((season, wk, row))
    return unique


# ── Points started per (season, week, manager, position) ────────────────
def build_pos_started(rosters_rows):
    pos_started = defaultdict(float)
    for row in rosters_rows:
        if row['Started'] != 'True':
            continue
        key = (row['Season'], int(row['Week']), row['Manager'], row['Position'])
        pos_started[key] += float(row['Points'])
    return pos_started


# ── Flip rate + margin/net-impact data, per position ─────────────────────
def build_flip_and_impact(unique_games, pos_started):
    flip_rates = {}
    net_impact = {pos: defaultdict(lambda: {'gained': 0, 'lost': 0}) for pos in POSITIONS}
    season_flip = {pos: defaultdict(lambda: [0, 0]) for pos in POSITIONS}  # season -> [flips, total]

    for pos in POSITIONS:
        flips = 0
        for season, wk, row in unique_games:
            a, b = row['Team_Name'], row['Opponent_Name']
            sc_a, sc_b = float(row['Team_Score']), float(row['Opponent_Score'])
            pa = pos_started.get((str(season), wk, a, pos), 0.0)
            pb = pos_started.get((str(season), wk, b, pos), 0.0)
            adj_a, adj_b = sc_a - pa, sc_b - pb
            actual_winner = a if sc_a > sc_b else b
            adj_winner = a if adj_a > adj_b else (b if adj_b > adj_a else 'TIE')
            flipped = adj_winner != actual_winner

            season_flip[pos][season][1] += 1
            if flipped:
                flips += 1
                season_flip[pos][season][0] += 1
                for side, won_actual, won_adj in [
                    (a, actual_winner == a, adj_winner == a),
                    (b, actual_winner == b, adj_winner == b),
                ]:
                    if won_adj and not won_actual:
                        net_impact[pos][side]['gained'] += 1
                    elif won_actual and not won_adj:
                        net_impact[pos][side]['lost'] += 1

        flip_rates[pos] = {'flips': flips, 'total': len(unique_games), 'pct': round(flips / len(unique_games) * 100, 1)}

    net_impact_out = {
        pos: {m: v['gained'] - v['lost'] for m, v in net_impact[pos].items()}
        for pos in POSITIONS
    }
    season_flip_out = {
        pos: {str(s): round(f / t * 100, 1) for s, (f, t) in season_flip[pos].items()}
        for pos in POSITIONS
    }
    return flip_rates, net_impact_out, season_flip_out


# ── Week-to-week predictability (coefficient of variation), per position ─
def build_consistency(rosters_rows):
    by_player = defaultdict(list)
    for row in rosters_rows:
        if row['Started'] != 'True' or row['Slot'] == 'IR':
            continue
        key = (row['Season'], row['Manager'], row['Player'], row['Position'])
        by_player[key].append(float(row['Points']))

    cv_by_position = defaultdict(list)
    for (season, mgr, player, pos), pts in by_player.items():
        if len(pts) < 4:
            continue
        mean = sum(pts) / len(pts)
        if mean <= 0:
            continue
        variance = sum((p - mean) ** 2 for p in pts) / (len(pts) - 1)
        cv_by_position[pos].append((variance ** 0.5) / mean)

    return {
        pos: {'avg_cv': round(sum(cv_by_position[pos]) / len(cv_by_position[pos]), 3),
              'sample': len(cv_by_position[pos])}
        for pos in POSITIONS
    }


# ── Draft picks: Nth pick at each position, per (season, manager) ───────
def load_nth_picks():
    picks = defaultdict(lambda: defaultdict(list))  # pos -> (season,manager) -> [(round, player)]
    all_drafted_players = defaultdict(lambda: defaultdict(set))  # pos -> (season, manager) -> set of ALL drafted player names (any round)
    with open(DRAFT_CSV) as f:
        for row in csv.DictReader(f):
            pos = row['position']
            if pos not in POSITIONS:
                continue
            key = (int(row['season']), canon(row['manager']))
            picks[pos][key].append((int(row['round']), row['player_name']))
            all_drafted_players[pos][key].add(row['player_name'])
    for pos in picks:
        for key in picks[pos]:
            picks[pos][key].sort()
    return picks, all_drafted_players


# ── Draft-vs-waiver PPG by round, per position ───────────────────────────
def build_draft_vs_waiver(rosters_rows, picks, all_drafted_players):
    weekly = defaultdict(list)  # (season, manager, player, position) -> [(week, slot, started, points)]
    for row in rosters_rows:
        key = (row['Season'], row['Manager'], row['Player'], row['Position'])
        weekly[key].append((int(row['Week']), row['Slot'], row['Started'], float(row['Points'])))

    def real_game(slot, started):
        return started == 'True' and slot != 'IR'

    result = {}
    for pos in POSITIONS:
        n = NTH_PICK[pos]
        by_round = defaultdict(lambda: [0.0, 0])
        nondraft = [0.0, 0]

        for (season, mgr), plist in picks[pos].items():
            if mgr in EXCLUDED_MANAGERS:
                continue
            if len(plist) < n:
                continue
            rnd, player = plist[n - 1]
            for wk, slot, started, pts in weekly.get((str(season), mgr, player, pos), []):
                if real_game(slot, started):
                    by_round[rnd][0] += pts
                    by_round[rnd][1] += 1

        # Waiver baseline: real-game weeks at this position from players NEVER
        # drafted at all that season by that manager (a genuine non-draft add).
        for (season, mgr, player, ppos), entries in weekly.items():
            if ppos != pos:
                continue
            if mgr in EXCLUDED_MANAGERS:
                continue
            key = (int(season), mgr)
            if player in all_drafted_players[pos].get(key, set()):
                continue
            for wk, slot, started, pts in entries:
                if real_game(slot, started):
                    nondraft[0] += pts
                    nondraft[1] += 1

        total_pts = sum(v[0] for v in by_round.values())
        total_weeks = sum(v[1] for v in by_round.values())
        result[pos] = {
            'nth_pick': n,
            'overall_drafted_ppg': round(total_pts / total_weeks, 2) if total_weeks else 0,
            'waiver_ppg': round(nondraft[0] / nondraft[1], 2) if nondraft[1] else 0,
            'by_round_ppg': {str(r): round(v[0] / v[1], 2) for r, v in by_round.items() if v[1] > 0},
            'by_round_weeks': {str(r): v[1] for r, v in by_round.items()},
        }
    return result


# ── Draft capital by manager by year, per position ───────────────────────
# ── Draft ORDER (league-wide rank, not round) PPG, per position ─────────
# "1st team to take a QB, 2nd team to take a QB, ..." within each season,
# ranked by overall_pick of that manager's Nth pick at the position (1st
# for QB/TE/K/D-ST, 2nd for RB/WR, same convention as everywhere else).
# This is a genuinely different cut than round: it strips out which round
# it happened in and just asks whether being an early mover *relative to
# your own league that year* buys you anything.
def _quantile(sorted_vals, q):
    """Linear-interpolation quantile (matches the common numpy default)."""
    n = len(sorted_vals)
    if n == 1:
        return sorted_vals[0]
    idx = q * (n - 1)
    lo = int(idx)
    hi = min(lo + 1, n - 1)
    frac = idx - lo
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac


def build_draft_order_ppg(rosters_rows):
    n = NTH_PICK

    picks_by_season_mgr = defaultdict(lambda: defaultdict(list))  # pos -> (season,manager) -> [(round, overall_pick, player)]
    with open(DRAFT_CSV) as f:
        for row in csv.DictReader(f):
            pos = row['position']
            if pos not in POSITIONS:
                continue
            m = canon(row['manager'])
            if m in EXCLUDED_MANAGERS:
                continue
            key = (int(row['season']), m)
            picks_by_season_mgr[pos][key].append((int(row['round']), int(row['overall_pick']), row['player_name']))

    weekly = defaultdict(list)  # (season, manager, player, position) -> [(week, slot, started, points)]
    for row in rosters_rows:
        key = (row['Season'], row['Manager'], row['Player'], row['Position'])
        weekly[key].append((int(row['Week']), row['Slot'], row['Started'], float(row['Points'])))

    def real_game(slot, started):
        return started == 'True' and slot != 'IR'

    result = {}
    for pos in POSITIONS:
        nth = n[pos]
        for key in picks_by_season_mgr[pos]:
            picks_by_season_mgr[pos][key].sort()

        nth_pick_by_key = {}
        for key, plist in picks_by_season_mgr[pos].items():
            if len(plist) >= nth:
                nth_pick_by_key[key] = plist[nth - 1]

        by_season = defaultdict(list)
        for (season, m), (rnd, overall, player) in nth_pick_by_key.items():
            by_season[season].append((overall, m, player))

        by_order = defaultdict(lambda: [0.0, 0])
        by_order_values = defaultdict(list)  # order -> [individual real-game weekly points]
        for season, records in by_season.items():
            records.sort()
            for order, (overall, m, player) in enumerate(records, 1):
                for wk, slot, started, pts in weekly.get((str(season), m, player, pos), []):
                    if real_game(slot, started):
                        by_order[order][0] += pts
                        by_order[order][1] += 1
                        by_order_values[order].append(pts)

        boxplot = {}
        for order, vals in by_order_values.items():
            if len(vals) < 5:
                continue  # too few points for a meaningful box plot
            sv = sorted(vals)
            boxplot[str(order)] = {
                'min': round(sv[0], 1),
                'q1': round(_quantile(sv, 0.25), 1),
                'median': round(_quantile(sv, 0.5), 1),
                'q3': round(_quantile(sv, 0.75), 1),
                'max': round(sv[-1], 1),
                'n': len(vals),
            }

        result[pos] = {
            'by_order_ppg': {str(o): round(v[0] / v[1], 2) for o, v in by_order.items() if v[1] > 0},
            'by_order_weeks': {str(o): v[1] for o, v in by_order.items()},
            'by_order_boxplot': boxplot,
        }
    return result


def build_draft_capital(picks):
    seasons = [2020, 2021, 2022, 2023, 2024, 2025]
    result = {}
    for pos in POSITIONS:
        n = NTH_PICK[pos]
        seasons_active = defaultdict(set)
        with open(DRAFT_CSV) as f:
            for row in csv.DictReader(f):
                m = canon(row['manager'])
                seasons_active[m].add(int(row['season']))
        managers = sorted(m for m in seasons_active if m not in EXCLUDED_MANAGERS)

        by_manager = {}
        for m in managers:
            by_year = {}
            drafted_rounds = []
            for s in seasons:
                if s not in seasons_active[m]:
                    by_year[str(s)] = 'not_in_league'
                    continue
                plist = picks[pos].get((s, m), [])
                if len(plist) < n:
                    by_year[str(s)] = None
                    continue
                rnd = plist[n - 1][0]
                by_year[str(s)] = rnd
                drafted_rounds.append(rnd)
            avg = round(sum(drafted_rounds) / len(drafted_rounds), 1) if drafted_rounds else None
            by_manager[m] = {'by_year': by_year, 'career_avg_round': avg}
        result[pos] = by_manager
    return result


# ── PPG-vs-win% and draft-round-vs-win% correlations, per position ──────
def build_performance_correlation(unique_games, pos_started, picks):
    standings = defaultdict(lambda: [0, 0])  # (season,manager) -> [wins, games]
    for season, wk, row in unique_games:
        if not row['Week'].startswith('Week'):
            continue
        for side, other, sc, opp_sc in [
            (row['Team_Name'], row['Opponent_Name'], float(row['Team_Score']), float(row['Opponent_Score'])),
            (row['Opponent_Name'], row['Team_Name'], float(row['Opponent_Score']), float(row['Team_Score'])),
        ]:
            standings[(season, side)][1] += 1
            if sc > opp_sc:
                standings[(season, side)][0] += 1

    result = {}
    for pos in POSITIONS:
        n = NTH_PICK[pos]
        pos_ppg = defaultdict(lambda: [0.0, 0])  # (season,manager) -> [points, weeks]
        for (season, wk, mgr, ppos), pts in pos_started.items():
            if ppos != pos:
                continue
            pos_ppg[(int(season), mgr)][0] += pts
            pos_ppg[(int(season), mgr)][1] += 1

        draft_round = {}
        for (season, mgr), plist in picks[pos].items():
            if len(plist) >= n:
                draft_round[(season, mgr)] = plist[n - 1][0]

        rows = []
        for key, (wins, games) in standings.items():
            if key not in pos_ppg or pos_ppg[key][1] == 0:
                continue
            ppg = pos_ppg[key][0] / pos_ppg[key][1]
            rows.append((key[0], key[1], wins / games, ppg, draft_round.get(key)))

        ppg_xs = [r[3] for r in rows]
        ppg_ys = [r[2] for r in rows]
        ppg_r = _pearson(ppg_xs, ppg_ys)
        ppg_slope, ppg_intercept = _linreg(ppg_xs, ppg_ys)

        drafted_rows = [r for r in rows if r[4] is not None]
        rd_xs = [r[4] for r in drafted_rows]
        rd_ys = [r[2] for r in drafted_rows]
        rd_r = _pearson(rd_xs, rd_ys) if len(drafted_rows) > 1 else 0
        rd_slope, rd_intercept = _linreg(rd_xs, rd_ys) if len(drafted_rows) > 1 else (0, 0)

        result[pos] = {
            'points': [{'season': r[0], 'manager': r[1], 'win_pct': round(r[2], 4),
                        'ppg': round(r[3], 2), 'drafted_round': r[4]} for r in rows],
            'ppg_vs_winpct': {'r': round(ppg_r, 3), 'r2': round(ppg_r ** 2, 4),
                              'slope': ppg_slope, 'intercept': ppg_intercept, 'n': len(rows)},
            'round_vs_winpct': {'r': round(rd_r, 3), 'r2': round(rd_r ** 2, 4),
                                 'slope': rd_slope, 'intercept': rd_intercept, 'n': len(drafted_rows)},
        }
    return result


# ── Acquisition source (drafted / waiver-FA / traded), per position ──────
# Drafted is a residual: total position points minus waiver minus traded.
# Validated to never go negative across all 84 (position, manager) combos
# before trusting this -- same check used for the D/ST-only analysis.
def build_acquisition_source(rosters_rows):
    total_by_pos_mgr = defaultdict(float)
    weekly_by_pid = defaultdict(dict)
    for row in rosters_rows:
        pos = row['Position']
        if pos in POSITIONS:
            total_by_pos_mgr[(pos, row['Manager'])] += float(row['Points'])
        weekly_by_pid[(row['Season'], row['Manager'], row['Player_ID'])][int(row['Week'])] = float(row['Points'])

    waiver_by_pos_mgr = defaultdict(float)
    with open(WAIVER_STINTS_CSV) as f:
        for row in csv.DictReader(f):
            pos = row['Position']
            if pos in POSITIONS:
                waiver_by_pos_mgr[(pos, row['Manager'])] += float(row['Total_Points'])

    traded_by_pos_mgr = defaultdict(float)
    with open(TRADE_STINTS_CSV) as f:
        for row in csv.DictReader(f):
            pos = row['position']
            if pos not in POSITIONS:
                continue
            season, mgr, pid = row['season'], row['receiving_manager'], row['player_id']
            start, n = int(row['scoring_period']), int(row['weeks_rostered'])
            weeks = weekly_by_pid.get((season, mgr, pid), {})
            traded_by_pos_mgr[(pos, mgr)] += sum(weeks.get(w, 0.0) for w in range(start, start + n))

    result = {}
    for pos in POSITIONS:
        managers = sorted(set(m for (p, m) in total_by_pos_mgr if p == pos) - EXCLUDED_MANAGERS)
        per_manager = {}
        league_total = {'drafted': 0.0, 'waiver': 0.0, 'traded': 0.0}
        for m in managers:
            tot = total_by_pos_mgr.get((pos, m), 0.0)
            wv = waiver_by_pos_mgr.get((pos, m), 0.0)
            tr = traded_by_pos_mgr.get((pos, m), 0.0)
            drafted = tot - wv - tr
            per_manager[m] = {'drafted': round(drafted, 1), 'waiver': round(wv, 1), 'traded': round(tr, 1)}
            league_total['drafted'] += drafted
            league_total['waiver'] += wv
            league_total['traded'] += tr
        result[pos] = {
            'per_manager': per_manager,
            'league_total': {k: round(v, 1) for k, v in league_total.items()},
        }
    return result


def main():
    rosters_rows = load_rosters()
    matchup_rows = load_matchups()
    unique_games = dedupe_games(matchup_rows)
    pos_started = build_pos_started(rosters_rows)
    picks, all_drafted_players = load_nth_picks()

    flip_rates, net_impact, season_flip = build_flip_and_impact(unique_games, pos_started)
    consistency = build_consistency(rosters_rows)
    draft_vs_waiver = build_draft_vs_waiver(rosters_rows, picks, all_drafted_players)
    draft_capital = build_draft_capital(picks)
    performance = build_performance_correlation(unique_games, pos_started, picks)
    acquisition_source = build_acquisition_source(rosters_rows)
    draft_order = build_draft_order_ppg(rosters_rows)

    final = {
        'positions': POSITIONS,
        'nth_pick': NTH_PICK,
        'total_games': len(unique_games),
        'flip_rates': flip_rates,
        'net_impact': net_impact,
        'season_flip_rate': season_flip,
        'consistency': consistency,
        'draft_vs_waiver': draft_vs_waiver,
        'draft_capital': draft_capital,
        'performance_correlation': performance,
        'acquisition_source': acquisition_source,
        'draft_order': draft_order,
    }
    with open(OUTPUT_JSON, 'w') as f:
        json.dump(final, f, separators=(',', ':'))

    print(f"Wrote {OUTPUT_JSON}")
    print(f"Total games: {len(unique_games)}")
    for pos in POSITIONS:
        print(f"  {pos}: flip rate {flip_rates[pos]['pct']}%, CV {consistency[pos]['avg_cv']}, "
              f"drafted PPG {draft_vs_waiver[pos]['overall_drafted_ppg']} vs waiver {draft_vs_waiver[pos]['waiver_ppg']}")


if __name__ == '__main__':
    main()
