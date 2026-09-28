"""
generate_dst_impact.py

Builds data/dst_removed_data.json for the "Life Without Defense" page.

For every real matchup in league history (regular season + real playoff
bracket games, no consolation weeks), recomputes both teams' scores with
their own D/ST's *started* points subtracted out, then compares the
adjusted scores to see whether the winner would have changed.

Also computes:
  - per manager, how their career D/ST points break down by acquisition
    source: Drafted, Waiver/Free Agent, or Traded.
  - per season, whether the playoff field / playoff outcomes would change.
  - the same "remove this position, recheck the winner" flip-rate analysis
    for every position (QB/RB/WR/TE/K/D/ST), for context on how much D/ST
    actually matters relative to the rest of the roster.
  - whether drafting a D/ST early actually outperforms streaming one off
    waivers, using real draft-pick data.

INPUTS (place in the same folder as this script, or update the paths below):
  - matchup_data.csv              (Team_Name, Outcome, Team_Score, Opponent_Name,
                                    Opponent_Score, Week, Season_Year, Is_Playoff)
  - weekly_rosters_clean.csv       (Season, Week, Manager, Player, Player_ID,
                                    Position, Slot, Started, Points)
  - waiver_stints_full.csv         (Season, Manager, Player_ID, Start_Week, End_Week,
                                    Type, Weeks_Rostered, Total_Points, Position)
  - player_stints.csv              (group_id, season, scoring_period, receiving_manager,
                                    player_id, player, position, weeks_rostered)
  - draft_history_all_positions.csv (season, round, draft_slot, overall_pick,
                                    pick_in_round, player_name, position, manager, fantasy_team)

OUTPUT:
  - dst_removed_data.json  (place in pages/data/ alongside dst-impact.html)

Run:  python3 generate_dst_impact.py
"""

import csv
import json
from collections import defaultdict

# ── Config ──────────────────────────────────────────────────────────────
MATCHUP_CSV        = 'matchup_data.csv'
ROSTERS_CSV         = 'weekly_rosters_clean.csv'
WAIVER_STINTS_CSV   = 'waiver_stints_full.csv'
TRADE_STINTS_CSV    = 'player_stints.csv'
DRAFT_CSV           = 'draft_history_all_positions.csv'
OUTPUT_JSON         = 'dst_removed_data.json'

EXCLUDED_MANAGERS = {'Thomas Sullivan', 'William Serafin'}

# Manager name aliases: some source files use a shorter name than others.
# (Same alias map used elsewhere on the site for these two managers.)
ALIAS = {'Carmine Pittelli': 'Carmine Pittelli Jr.', 'Ryan McQuaid': 'Ryan P McQuaid'}


def canon(name):
    """Normalize a manager name to the canonical long form used by
    matchup_data.csv and weekly_rosters_clean.csv. draft_history_all_positions.csv
    (like manager_schedule.json elsewhere on the site) uses the shorter form
    for these two managers specifically, so every read of that file's
    'manager' field needs to pass through this before use as a lookup key."""
    return ALIAS.get(name, name)


# ── Helpers ─────────────────────────────────────────────────────────────
def matchup_week_to_num(season, week_label):
    """Convert matchup_data.csv's 'Week N' / 'Playoff Round N' label into a
    plain week number matching weekly_rosters_clean.csv's Week column.
    Playoff round -> week mapping is season-dependent: 2020/2021 had a
    4-round playoff (weeks 14-17), every other year has 3 rounds (15-17)."""
    if week_label.startswith('Week'):
        return int(week_label.replace('Week ', ''))
    n = int(week_label.replace('Playoff Round ', ''))
    mapping = {1: 14, 2: 15, 3: 16, 4: 17} if season in (2020, 2021) else {1: 15, 2: 16, 3: 17}
    return mapping.get(n)


def round_label(season, week_label):
    """Convert a raw week label into the site's display convention
    (First Round / Quarterfinal / Semifinal / Championship for playoffs)."""
    if week_label.startswith('Week'):
        return week_label
    n = int(week_label.replace('Playoff Round ', ''))
    mapping = ({1: 'First Round', 2: 'Quarterfinal', 3: 'Semifinal', 4: 'Championship'}
               if season in (2020, 2021) else
               {1: 'Quarterfinal', 2: 'Semifinal', 3: 'Championship'})
    return mapping.get(n, week_label)


def is_valid_game_row(row):
    """Site-wide consolation-game exclusion rule: keep a row if it's a
    regular-season week, OR if it's a real (non-consolation) playoff game."""
    return row['Week'].startswith('Week') or row['Is_Playoff'] == 'Yes'


# ── Step 1: started D/ST points per (season, week, manager) ─────────────
# This is what actually counted toward that manager's real score that week.
def build_dst_started_points():
    dst_started_pts = defaultdict(float)
    dst_all_pts = defaultdict(float)      # for PPG: total D/ST points while started
    dst_started_weeks = defaultdict(int)  # for PPG: count of weeks a D/ST was started
    with open(ROSTERS_CSV) as f:
        for row in csv.DictReader(f):
            if row['Position'] != 'D/ST' or row['Started'] != 'True':
                continue
            mgr = row['Manager']
            pts = float(row['Points'])
            dst_started_pts[(row['Season'], int(row['Week']), mgr)] += pts
            dst_all_pts[mgr] += pts
            dst_started_weeks[mgr] += 1
    return dst_started_pts, dst_all_pts, dst_started_weeks


# ── Step 2: build the deduplicated valid-games list, with adjusted scores ─
def build_games(dst_started_pts):
    rows = []
    with open(MATCHUP_CSV) as f:
        for row in csv.DictReader(f):
            if row['Team_Name'] in EXCLUDED_MANAGERS or row['Opponent_Name'] in EXCLUDED_MANAGERS:
                continue
            if not is_valid_game_row(row):
                continue
            rows.append(row)

    # Known data-quality fix: a small number of rows have Team_Score/
    # Opponent_Score transposed relative to the Outcome field. Correct any
    # row where the scores contradict the stated outcome.
    for row in rows:
        ts, os_ = float(row['Team_Score']), float(row['Opponent_Score'])
        if row['Outcome'] == 'Win' and ts <= os_:
            row['Team_Score'], row['Opponent_Score'] = row['Opponent_Score'], row['Team_Score']
        elif row['Outcome'] == 'Loss' and ts >= os_:
            row['Team_Score'], row['Opponent_Score'] = row['Opponent_Score'], row['Team_Score']

    # matchup_data.csv has one row per team per game (each game appears twice).
    # Keep only one row per real game.
    seen = set()
    unique_games = []
    for row in rows:
        season = int(row['Season_Year'])
        wk = matchup_week_to_num(season, row['Week'])
        gid = (season, wk, tuple(sorted([row['Team_Name'], row['Opponent_Name']])))
        if gid in seen:
            continue
        seen.add(gid)
        unique_games.append(row)

    games_out = []
    for row in unique_games:
        season = int(row['Season_Year'])
        wk = matchup_week_to_num(season, row['Week'])
        a, b = row['Team_Name'], row['Opponent_Name']
        score_a, score_b = float(row['Team_Score']), float(row['Opponent_Score'])

        # Subtracting D/ST points: if a defense scored negative, this adds
        # those points back rather than penalizing the team further.
        dst_a = dst_started_pts.get((str(season), wk, a), 0.0)
        dst_b = dst_started_pts.get((str(season), wk, b), 0.0)
        adj_a, adj_b = round(score_a - dst_a, 2), round(score_b - dst_b, 2)

        actual_winner = a if score_a > score_b else b
        adj_winner = a if adj_a > adj_b else (b if adj_b > adj_a else 'TIE')
        flipped = adj_winner != actual_winner

        games_out.append({
            'season': season, 'label': round_label(season, row['Week']), 'week_num': wk,
            'team_a': a, 'team_b': b,
            'score_a': round(score_a, 2), 'score_b': round(score_b, 2),
            'dst_a': round(dst_a, 2), 'dst_b': round(dst_b, 2),
            'adj_a': adj_a, 'adj_b': adj_b,
            'actual_winner': actual_winner, 'adj_winner': adj_winner, 'flipped': flipped,
        })
    return games_out


# ── Step 3: per-manager records + their specific flipped games ──────────
def build_manager_stats(games_out):
    mgr_stats = defaultdict(lambda: {
        'games': 0, 'actual_w': 0, 'actual_l': 0, 'adj_w': 0, 'adj_l': 0,
        'flipped': 0, 'flipped_games': [],
    })
    for g in games_out:
        sides = [
            (g['team_a'], g['team_b'], g['score_a'], g['adj_a'], g['score_b'], g['adj_b']),
            (g['team_b'], g['team_a'], g['score_b'], g['adj_b'], g['score_a'], g['adj_a']),
        ]
        for side, other, sc, adj_sc, opp_sc, opp_adj in sides:
            st = mgr_stats[side]
            st['games'] += 1
            won_actual = g['actual_winner'] == side
            won_adj = g['adj_winner'] == side
            if won_actual:
                st['actual_w'] += 1
            else:
                st['actual_l'] += 1
            if won_adj:
                st['adj_w'] += 1
            elif g['adj_winner'] != 'TIE':
                st['adj_l'] += 1
            if g['flipped']:
                st['flipped'] += 1
                if won_adj and not won_actual:
                    direction = 'gained_win'
                elif won_actual and not won_adj:
                    direction = 'lost_win'
                else:
                    direction = 'tie'
                st['flipped_games'].append({
                    'season': g['season'], 'label': g['label'], 'opponent': other,
                    'my_score': sc, 'opp_score': opp_sc, 'my_adj': adj_sc, 'opp_adj': opp_adj,
                    'direction': direction,
                })
    return mgr_stats


# ── Step 5: per-season playoff field + playoff-outcome changes ──────────
def build_season_playoffs(games_out):
    seasons = sorted(set(g['season'] for g in games_out))
    result = {}

    for season in seasons:
        # Regular season standings, actual vs adjusted: [wins, games_played, points]
        standings_actual = defaultdict(lambda: [0, 0, 0.0])
        standings_adj = defaultdict(lambda: [0, 0, 0.0])

        reg_games = [g for g in games_out if g['season'] == season and g['label'].startswith('Week')]
        for g in reg_games:
            for side, other, sc, adj_sc, opp_sc, opp_adj in [
                (g['team_a'], g['team_b'], g['score_a'], g['adj_a'], g['score_b'], g['adj_b']),
                (g['team_b'], g['team_a'], g['score_b'], g['adj_b'], g['score_a'], g['adj_a']),
            ]:
                standings_actual[side][1] += 1
                standings_adj[side][1] += 1
                standings_actual[side][2] += sc
                standings_adj[side][2] += adj_sc
                if sc > opp_sc:
                    standings_actual[side][0] += 1
                if adj_sc > opp_adj:
                    standings_adj[side][0] += 1

        def top8(standings):
            # Rank by win PERCENTAGE, not raw win count -- matters in 2020,
            # where 15 teams meant a rotating bye each week, so teams played
            # different total game counts. Ties broken by total points.
            ranked = sorted(
                standings.items(),
                key=lambda kv: (-(kv[1][0] / kv[1][1]) if kv[1][1] else 0, -kv[1][2])
            )
            return [m for m, _ in ranked[:8]]

        actual_top8 = top8(standings_actual)
        adj_top8 = top8(standings_adj)
        gained = [m for m in adj_top8 if m not in actual_top8]   # would make it, but actually didn't
        lost = [m for m in actual_top8 if m not in adj_top8]     # actually made it, but wouldn't have

        # Playoff-outcome changes: does any REAL playoff game (using the
        # actual bracket matchups that really happened) flip without D/ST?
        playoff_games = [g for g in games_out if g['season'] == season and not g['label'].startswith('Week')]
        playoff_flips = [{
            'label': g['label'], 'team_a': g['team_a'], 'team_b': g['team_b'],
            'score_a': g['score_a'], 'score_b': g['score_b'],
            'adj_a': g['adj_a'], 'adj_b': g['adj_b'],
            'actual_winner': g['actual_winner'], 'adj_winner': g['adj_winner'],
        } for g in playoff_games if g['flipped']]

        # Did the actual champion's title actually hold up without D/ST? Not
        # just whether the Championship game itself flipped -- a flip in ANY
        # earlier real round (Quarterfinal, Semifinal) they actually played
        # means they'd have been eliminated before ever reaching the final,
        # so the champion changes either way. Those earlier rounds are just
        # as real (both sides had real stakes and set real lineups), so this
        # is a valid conclusion even though we can't simulate who the
        # *replacement* champion would have been beyond that point.
        champ_game = next((g for g in playoff_games if g['label'] == 'Championship'), None)
        actual_champion = champ_game['actual_winner'] if champ_game else None
        champion_path_games = [
            g for g in playoff_games
            if actual_champion and (g['team_a'] == actual_champion or g['team_b'] == actual_champion)
        ]
        champion_survives = all(not g['flipped'] for g in champion_path_games)
        champion_changed = bool(actual_champion) and not champion_survives
        earliest_flip = next((g['label'] for g in champion_path_games if g['flipped']), None)

        result[season] = {
            'actual_top8': actual_top8, 'adj_top8': adj_top8,
            'gained': gained, 'lost': lost,
            'playoff_flips': playoff_flips,
            'champion_changed': champion_changed,
            'actual_champion': actual_champion,
            'champion_eliminated_round': earliest_flip,
        }
    return result



def build_acquisition_source():
    # Total D/ST points per manager across ALL weeks (started or benched) --
    # this is the denominator the three buckets need to add up to.
    total_dst_allweeks = defaultdict(float)
    weekly_by_pid = defaultdict(dict)  # (season, manager, player_id) -> {week: points}
    with open(ROSTERS_CSV) as f:
        for row in csv.DictReader(f):
            if row['Position'] == 'D/ST':
                total_dst_allweeks[row['Manager']] += float(row['Points'])
            weekly_by_pid[(row['Season'], row['Manager'], row['Player_ID'])][int(row['Week'])] = float(row['Points'])

    # Waiver/free-agent bucket: waiver_stints_full.csv already gives real,
    # verified point totals per stint directly.
    waiver_dst = defaultdict(float)
    with open(WAIVER_STINTS_CSV) as f:
        for row in csv.DictReader(f):
            if row['Position'] == 'D/ST':
                waiver_dst[row['Manager']] += float(row['Total_Points'])

    # Traded bucket: player_stints.csv only has z-scores, not raw points, so
    # recompute real points from the roster data using the stint's week range
    # (scoring_period is the start week, weeks_rostered the stint length).
    traded_dst = defaultdict(float)
    with open(TRADE_STINTS_CSV) as f:
        for row in csv.DictReader(f):
            if row['position'] != 'D/ST':
                continue
            season, mgr, pid = row['season'], row['receiving_manager'], row['player_id']
            start, n = int(row['scoring_period']), int(row['weeks_rostered'])
            weeks = weekly_by_pid.get((season, mgr, pid), {})
            traded_dst[mgr] += sum(weeks.get(w, 0.0) for w in range(start, start + n))

    # Drafted bucket is the residual: whatever's left after waiver + trade
    # points are subtracted from the manager's career D/ST total. This is an
    # inference, not a directly-measured field -- validated to never go
    # negative across all managers before trusting it.
    acquisition = {}
    for m in total_dst_allweeks:
        tot = total_dst_allweeks[m]
        wv = waiver_dst.get(m, 0)
        tr = traded_dst.get(m, 0)
        drafted = round(tot - wv - tr, 1)
        acquisition[m] = {'drafted': drafted, 'waiver': round(wv, 1), 'traded': round(tr, 1)}
    return acquisition


# ── Assemble and write ───────────────────────────────────────────────────
# ── Step 6: flip rate by position (context for how much D/ST matters) ───
def build_position_flip_rates(games_out, rosters_rows):
    # Points started per (season, week, manager, position) -- grouped by
    # real NFL position, not roster slot, so a RB/WR/TE started via FLEX
    # still counts toward its own position's total.
    pos_started = defaultdict(float)
    for row in rosters_rows:
        if row['Started'] != 'True':
            continue
        key = (row['Season'], int(row['Week']), row['Manager'], row['Position'])
        pos_started[key] += float(row['Points'])

    positions = ['QB', 'RB', 'WR', 'TE', 'K', 'D/ST']
    results = {}
    for pos in positions:
        flips = 0
        for g in games_out:
            season = g['season']
            wk = g['week_num']
            a, b = g['team_a'], g['team_b']
            pa = pos_started.get((str(season), wk, a, pos), 0.0)
            pb = pos_started.get((str(season), wk, b, pos), 0.0)
            adj_a, adj_b = g['score_a'] - pa, g['score_b'] - pb
            adj_winner = a if adj_a > adj_b else (b if adj_b > adj_a else 'TIE')
            if adj_winner != g['actual_winner']:
                flips += 1
        results[pos] = {'flips': flips, 'total': len(games_out), 'pct': round(flips / len(games_out) * 100, 1)}
    return results


# ── Step 7: does drafting a D/ST early actually outperform streaming one? ─
def build_draft_vs_waiver():
    weekly = defaultdict(list)  # (season, manager, player) -> [(week, slot, started, points)]
    with open(ROSTERS_CSV) as f:
        for row in csv.DictReader(f):
            if row['Position'] != 'D/ST':
                continue
            key = (row['Season'], row['Manager'], row['Player'])
            weekly[key].append((int(row['Week']), row['Slot'], row['Started'], float(row['Points'])))

    def real_game(slot, started):
        return started == 'True' and slot != 'IR'

    drafted_keys = {}  # (season, manager, player) -> round
    with open(DRAFT_CSV) as f:
        for row in csv.DictReader(f):
            if row['position'] == 'D/ST':
                drafted_keys[(row['season'], canon(row['manager']), row['player_name'])] = int(row['round'])

    by_round = defaultdict(lambda: [0.0, 0])   # round -> [points, real-game weeks]
    overall_drafted = [0.0, 0]
    nondraft = [0.0, 0]

    for key, entries in weekly.items():
        is_drafted = key in drafted_keys
        for wk, slot, started, pts in entries:
            if not real_game(slot, started):
                continue
            if is_drafted:
                overall_drafted[0] += pts
                overall_drafted[1] += 1
                by_round[drafted_keys[key]][0] += pts
                by_round[drafted_keys[key]][1] += 1
            else:
                nondraft[0] += pts
                nondraft[1] += 1

    round_ppg = {
        str(r): round(pts / weeks, 2)
        for r, (pts, weeks) in by_round.items() if weeks > 0
    }
    round_weeks = {str(r): weeks for r, (pts, weeks) in by_round.items()}

    return {
        'overall_drafted_ppg': round(overall_drafted[0] / overall_drafted[1], 2) if overall_drafted[1] else 0,
        'overall_drafted_weeks': overall_drafted[1],
        'waiver_ppg': round(nondraft[0] / nondraft[1], 2) if nondraft[1] else 0,
        'waiver_weeks': nondraft[1],
        'by_round_ppg': round_ppg,
        'by_round_weeks': round_weeks,
    }


# ── Step 8: week-to-week predictability by position (coefficient of variation) ─
def build_position_consistency(rosters_rows):
    # Each player-season's own weekly scores, real games only (started, not IR)
    by_player = defaultdict(list)
    for row in rosters_rows:
        if row['Started'] != 'True' or row['Slot'] == 'IR':
            continue
        key = (row['Season'], row['Manager'], row['Player'], row['Position'])
        by_player[key].append(float(row['Points']))

    cv_by_position = defaultdict(list)
    for (season, mgr, player, pos), pts in by_player.items():
        if len(pts) < 4:
            continue  # need a real sample to make a coefficient of variation meaningful
        mean = sum(pts) / len(pts)
        if mean <= 0:
            continue  # avoid divide-by-near-zero distortion
        variance = sum((p - mean) ** 2 for p in pts) / (len(pts) - 1)
        stdev = variance ** 0.5
        cv_by_position[pos].append(stdev / mean)

    return {
        pos: {
            'avg_cv': round(sum(cv_by_position[pos]) / len(cv_by_position[pos]), 3),
            'sample': len(cv_by_position[pos]),
        }
        for pos in ['QB', 'RB', 'WR', 'TE', 'K', 'D/ST']
    }


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


# ── Step 9: does D/ST performance (and draft capital spent on it) actually
# correlate with real team win%? Uses regular-season win% per manager-season
# (the same denominator used for standings elsewhere), D/ST PPG per manager-
# season (real games: started, not IR), and the earliest round a manager
# drafted a D/ST that season (if any).
def build_dst_performance_correlation():
    standings = defaultdict(lambda: [0, 0])  # (season,manager) -> [wins, games]
    with open(MATCHUP_CSV) as f:
        for row in csv.DictReader(f):
            if row['Team_Name'] in EXCLUDED_MANAGERS:
                continue
            if not row['Week'].startswith('Week'):
                continue
            key = (int(row['Season_Year']), row['Team_Name'])
            standings[key][1] += 1
            if row['Outcome'] == 'Win':
                standings[key][0] += 1

    dst_pts = defaultdict(lambda: [0.0, 0])  # (season,manager) -> [points, real-game weeks]
    with open(ROSTERS_CSV) as f:
        for row in csv.DictReader(f):
            if row['Position'] != 'D/ST' or row['Started'] != 'True' or row['Slot'] == 'IR':
                continue
            key = (int(row['Season']), row['Manager'])
            dst_pts[key][0] += float(row['Points'])
            dst_pts[key][1] += 1

    draft_round = {}  # (season,manager) -> earliest round a D/ST was drafted that season
    with open(DRAFT_CSV) as f:
        for row in csv.DictReader(f):
            if row['position'] != 'D/ST':
                continue
            key = (int(row['season']), canon(row['manager']))
            rnd = int(row['round'])
            if key not in draft_round or rnd < draft_round[key]:
                draft_round[key] = rnd

    points_ppg = []
    for key, (wins, games) in standings.items():
        if key not in dst_pts or dst_pts[key][1] == 0:
            continue
        ppg = dst_pts[key][0] / dst_pts[key][1]
        points_ppg.append({
            'season': key[0], 'manager': key[1],
            'win_pct': round(wins / games, 4), 'ppg': round(ppg, 2),
            'drafted_round': draft_round.get(key),
        })

    ppg_xs = [p['ppg'] for p in points_ppg]
    ppg_ys = [p['win_pct'] for p in points_ppg]
    ppg_r = _pearson(ppg_xs, ppg_ys)
    ppg_slope, ppg_intercept = _linreg(ppg_xs, ppg_ys)

    drafted_points = [p for p in points_ppg if p['drafted_round'] is not None]
    rd_xs = [p['drafted_round'] for p in drafted_points]
    rd_ys = [p['win_pct'] for p in drafted_points]
    rd_r = _pearson(rd_xs, rd_ys)
    rd_slope, rd_intercept = _linreg(rd_xs, rd_ys)

    return {
        'points': points_ppg,
        'ppg_vs_winpct': {'r': round(ppg_r, 3), 'r2': round(ppg_r ** 2, 4),
                           'slope': ppg_slope, 'intercept': ppg_intercept, 'n': len(points_ppg)},
        'round_vs_winpct': {'r': round(rd_r, 3), 'r2': round(rd_r ** 2, 4),
                             'slope': rd_slope, 'intercept': rd_intercept, 'n': len(drafted_points)},
    }


# ── Step 10: draft capital (earliest D/ST round) spent per manager per year,
# plus each manager's career average across the years they actually drafted one.
def build_draft_capital_by_manager():
    seasons = [2020, 2021, 2022, 2023, 2024, 2025]

    draft_round = {}       # (season,manager) -> earliest D/ST round drafted that season
    seasons_active = defaultdict(set)  # manager -> set of seasons they had ANY draft pick in
    with open(DRAFT_CSV) as f:
        for row in csv.DictReader(f):
            m = canon(row['manager'])
            s = int(row['season'])
            seasons_active[m].add(s)
            if row['position'] != 'D/ST':
                continue
            key = (s, m)
            rnd = int(row['round'])
            if key not in draft_round or rnd < draft_round[key]:
                draft_round[key] = rnd

    managers = sorted(m for m in seasons_active if m not in EXCLUDED_MANAGERS)

    by_manager = {}
    for m in managers:
        by_year = {}
        drafted_rounds = []
        for s in seasons:
            if s not in seasons_active[m]:
                by_year[str(s)] = 'not_in_league'
                continue
            rnd = draft_round.get((s, m))
            by_year[str(s)] = rnd  # a real round number, or None (genuinely streamed that year)
            if rnd is not None:
                drafted_rounds.append(rnd)
        avg = round(sum(drafted_rounds) / len(drafted_rounds), 1) if drafted_rounds else None
        by_manager[m] = {
            'by_year': by_year,
            'career_avg_round': avg,
            'years_drafted': len(drafted_rounds),
            'years_streamed': len(seasons_active[m]) - len(drafted_rounds),
        }
    return by_manager


def main():
    dst_started_pts, dst_all_pts, dst_started_weeks = build_dst_started_points()
    games_out = build_games(dst_started_pts)
    mgr_stats = build_manager_stats(games_out)
    acquisition = build_acquisition_source()
    season_playoffs = build_season_playoffs(games_out)

    with open(ROSTERS_CSV) as f:
        rosters_rows = list(csv.DictReader(f))
    position_flip_rates = build_position_flip_rates(games_out, rosters_rows)
    draft_vs_waiver = build_draft_vs_waiver()
    position_consistency = build_position_consistency(rosters_rows)
    dst_performance = build_dst_performance_correlation()
    draft_capital = build_draft_capital_by_manager()

    managers_out = {}
    for m, st in mgr_stats.items():
        ppg = (round(dst_all_pts.get(m, 0) / dst_started_weeks[m], 2)
               if dst_started_weeks.get(m, 0) > 0 else 0)
        managers_out[m] = {
            'games': st['games'],
            'actual_record': [st['actual_w'], st['actual_l']],
            'adj_record': [st['adj_w'], st['adj_l']],
            'flipped_count': st['flipped'],
            'flipped_games': st['flipped_games'],
            'acquisition': acquisition.get(m, {'drafted': 0, 'waiver': 0, 'traded': 0}),
            'dst_ppg': ppg,
        }

    league = {
        'total_games': len(games_out),
        'total_flips': sum(1 for g in games_out if g['flipped']),
        'all_games': games_out,
    }

    final = {
        'league': league, 'managers': managers_out, 'season_playoffs': season_playoffs,
        'position_flip_rates': position_flip_rates, 'draft_vs_waiver': draft_vs_waiver,
        'position_consistency': position_consistency, 'dst_performance': dst_performance,
        'draft_capital': draft_capital,
    }
    with open(OUTPUT_JSON, 'w') as f:
        json.dump(final, f, separators=(',', ':'))

    print(f"Wrote {OUTPUT_JSON}")
    print(f"  Managers: {len(managers_out)}")
    print(f"  Total games: {league['total_games']}")
    print(f"  Total flips: {league['total_flips']} "
          f"({league['total_flips']/league['total_games']*100:.1f}%)")


if __name__ == '__main__':
    main()
