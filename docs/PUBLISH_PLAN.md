# Publish plan (phase 4)

Status: agreed, 2026-09-30 (session 6). Owner: Ethan Radecki.
Progress: Stage A complete (#29-#41); F1a merged (#42); F1b (build provenance, size budget, headless page tests in CI) in review; then M0/M1 and Stage B. Status columns below are as of A8c.

This is the page data contract for phase 4: every page, every piece of data it reads, the shape of that data today, the engine table or function that produces it, and what is missing. It is the input to `engine/publish/` and to the frontend refactor (ARCHITECTURE.md sections 3 and 6 to 8). The current site files are the goldens; `engine/_legacy/regenerate_data_files.py` and `update_2026.py` are the spec for the files they write.

Decisions are recorded in section 7 and the rollout in section 8. Nothing here changes methodology.

## 1. How to read this

**Where data lives today**

| Term | Meaning |
|---|---|
| file | a file in `data/` fetched at runtime (JSON, CSV) |
| global | a `data/*.js` file loaded by script tag that defines a global variable |
| inline | a JS literal pasted into the page's HTML |
| HTML | numbers typed straight into the page markup (tables, stat cards, prose) |
| client | numbers the page computes in the browser from another file |
| config | league facts (names, colors, logos, seasons, round names, exclusions) hardcoded in the page |
| template | static text or metadata that belongs to the web template, not to any league (labels, metric descriptions) |

**Status of each element**

| Status | Meaning |
|---|---|
| COVERED | engine table exists and `--verify` checks it against this exact golden |
| PARTIAL | engine table exists; only part of the element is checked, or a page-layer step (rounding, top-N, grouping) is not yet written |
| NO GOLDEN | engine can produce it, but the page's data has not been frozen as a golden yet |
| NO PRODUCER | nothing in the engine produces it yet |
| EDITORIAL | hand-written content; moves to `leagues/<league>/editorial/` (phase 5) |
| LEAGUE-AUTHORED | league facts ESPN does not have; stays hand-kept by the league |
| CONFIG | comes from `league.yaml` via `config.json` |
| TEMPLATE | moves into `web/` as static template content |

Names: legacy data keys rows by manager display name, and the pages disagree on spelling ("Carmine Pittelli Jr." vs "Carmine Pittelli", "Ryan P McQuaid" vs "Ryan McQuaid"). The engine keys by `manager_key`; display names come from config.

## 2. Summary

| Page | Data today | Elements | Status in one line |
|---|---|---|---|
| index.html | file (stats CSV) + client | 3 | leaderboard COVERED via manager seasons; client math moves to publish |
| managers.html | 5 files, rankings files, ~280 KB inline, client | 14 | mostly COVERED; draft board map COVERED (A5); headshots COVERED (A8c); client luck uses a legacy method |
| matchups.html | file (matchups.json) | 4 | COVERED |
| weekly-rankings.html | rankings files, playoff odds, headshots | 6 plus ~20 computed fields | COVERED (A8b: editorial files, frozen snapshots, derived fields; odds A4); headshots COVERED (A8c) |
| trade-value.html | 6 globals + inline | 8 | explorer COVERED; other globals NO GOLDEN; most traded NO PRODUCER |
| position-impact.html | file | 1 (12 sections) | COVERED |
| dst-impact.html | file | 1 (8 sections) | COVERED |
| schedule_release.html | 2 files + inline | 4 | NO PRODUCER; schedule LEAGUE-AUTHORED |
| champions.html | ~15 KB inline + headshots | 4 | COVERED (A8a cards and finals, A8c headshots) |
| surplus-value.html | ~25 KB inline | 9 | COVERED (A5: new golden for tips, highs and lows, best/worst lists, scale) |
| draft-analysis.html | ~14 KB inline + HTML | 8 | COVERED (A5: inline data and typed HTML replaced) |
| draft-fingerprints.html | ~245 KB inline | 2 | data COVERED (A5); metadata TEMPLATE; archetype names EDITORIAL file |
| draft-history.html | ~84 KB inline | 3 | COVERED (A5) |
| lineup-efficiency.html | ~150 KB inline | 11 | COVERED (A6b: bench depth ported, every inline block) |
| waiver-value.html | ~284 KB inline | 6 | COVERED (A6a: every inline block, golden `waivers/waiver_value_page.json`) |
| extra-analytics.html | ~90 KB inline + HTML | 13 | COVERED (A7a matchup sections, A7b model sections); R2 history and swap caveats EDITORIAL |
| transaction-analysis.html | none | 0 | hub page; config only |

## 3. Shared across pages

These appear in many pages and become `config.json` (built from `league.yaml`) or template code.

| Element | Where today | Target | Status |
|---|---|---|---|
| Nav bar and mobile menu (14 links plus Home) | copied into every page, twice | `config.json` nav + page features; template renders it | CONFIG + TEMPLATE |
| Manager display names, short names, logo file names | `LASTNAME_MAP` (data-engine.js, weekly-rankings), `LOGO_MAP` (champions), `LOGO_LASTNAMES` (trade-value), `MANAGERS` (draft-history), pills (managers.html), 14 logo paths (extra-analytics) | `config.json` managers: key, name, short, logo, championship_logos | CONFIG |
| Manager colors | `MANAGER_COLORS` in 6 pages, `MANAGER_COLOR_HEX` (dst-impact), `MANAGER_COLOR` (schedule_release), `FP_COLOR_MAP`, `MGR_COLORS`; three stray values noted in league.yaml | `config.json` managers[].colors {dark, light} | CONFIG |
| Excluded managers | `EXCLUDED` (data-engine.js), `EXCLUDED_MANAGERS` (update_2026.py), `ACTIVE` (regenerate_data_files.py), prose | `hidden` flag on rows; `config.json` managers[].hidden | CONFIG |
| Season colors | `SEASON_COLORS` in 8 pages, `TINT_HEX` (champions), `SEASON_THEME_COLORS` (weekly-rankings) | `config.json` theme.season_colors plus named shades per season | CONFIG |
| Playoff round names | `ROUND_NAMES` (matchups) | `rules.playoff_rounds` | CONFIG |
| Forfeit game | `SUPERLATIVE_EXCLUDE` (matchups) | `analysis.exclude_games` | CONFIG |
| Seasons and "live" season | `FL_TL_SEASONS`, `SEASONS`, `HEATMAP_SEASONS`, "six seasons (2020-2025)", "seven seasons, 2020-2026", "Est. 2020" | `config.json` seasons, first_season, live_season, finished_seasons | CONFIG |
| Regular season length, playoff start week | `flPlayoffStartWeek` (managers), `FL_TL_WEEKS_PER_SEASON` | `rules.regular_season_weeks` | CONFIG |
| League logo and favicon | `preach_logo_2026.png` in every head; `preach_logo.png` at the root | `league.logo.by_season`, current season | CONFIG |
| Player headshots | `data/player_headshots.json` (1,319 entries keyed `name|POS`, NFL.com image URLs; no producer) read by managers, champions, weekly-rankings | generated per player id (decision 7.5): `data/v1/headshots.json` by id; the legacy view keyed by ESPN name and every spelling the published data uses | COVERED (A8c: ESPN images by player id, golden `headshots/player_headshots.json`) |
| Position colors, pos badge classes, gradients | every page | template tokens | TEMPLATE |
| `data-engine.js` | index (leaderboard), managers (profiles, pills) | its CSV parser and math go away; publish emits the numbers | client |
| `shared.js` | every page | menu and lightbox only; stays as template | TEMPLATE |

## 4. Page contracts

Columns: element, where today, shape today, engine producer, golden and check, status. `ms` = `manager_seasons`.

### 4.1 index.html

| Element | Where | Shape | Producer | Golden / check | Status |
|---|---|---|---|---|---|
| All-time leaderboard | file `preach_manager_stats.csv` via `buildLeaderboard` | rows: Manager, Year, Team, W, L, Playoffs, Champ_W, PF/G, LR_zscore (27 columns in file) | `ms` (wins, losses, made_playoffs, champion, pf_per_game, pa_z, team_name) | `manager_seasons/preach_manager_stats.csv`, 2 checks PASS | COVERED |
| Career totals, avg PF/G (mean of season PF/G), avg luck (mean LR_zscore), best/worst season, rank tiers | client (data-engine.js) | computed per manager | publish from `ms`, visible-only ranks | none | client -> publish |
| Hero "2025 Champion Anthony Kelly", "seven seasons, 2020-2026", "Est. 2020" | HTML | text | `ms.champion` of last finished season; config | none | HTML -> data/config |

Note: the live season's rows (Playoffs 0, all-time ranks blank) are included in the leaderboard today.

### 4.2 managers.html

| Element | Where | Shape | Producer | Golden / check | Status |
|---|---|---|---|---|---|
| Season table, career stats, ranks, pills | file `preach_manager_stats.csv` + `buildManagerProfiles` | as 4.1 plus PA/G, DIFF, Draft_Slot, PF/G rank, Dominance, Luck_Rating | `ms` | as 4.1 | COVERED (client math -> publish) |
| H2H chart, best/worst rival | client from file `matchup_data.csv` (bracket-only filter) | rows: Team_Name, Outcome, Team_Score, Opponent_Name, Opponent_Score, Week, Season_Year, Is_Playoff | `head_to_head`, `games` | `matchup_data.csv.gz` (normalize check) + h2h check (extra-analytics) | COVERED (client -> publish) |
| Scoring distribution | client: regular-season weekly scores | list of scores | `games` | none | client -> publish |
| Schedule luck by season | client: median method re-implemented in JS (score > median = expected win; no half wins; drops 0 scores) | {season: {actual, predicted}} | `schedule_luck` (engine: half wins, finished weeks) | `schedule/schedule_luck_season.csv` | COVERED; the page's JS method is the legacy one, engine numbers differ where half wins apply |
| Seasonal scoring trends | client: weekly score vs league weekly average | per week | `games` | none | client -> publish |
| Performance over time (league avg PF/G line) | client from stats CSV | per season | `ms` | as 4.1 | client -> publish |
| Power ranking trajectory | rankings manifest + every weekly file | {manager: {season: {week: rank}}} | editorial rankings | none | EDITORIAL |
| Draft fingerprint radar | inline `FINGERPRINTS` (7 measures, raw + normalized, 2021-2025 + career) | {name: {season: {raw, normalized}}} | replaced by 10-dim `draft_profile_seasons` / `draft_profile_career` (Ethan, session 5) | draft profile page checks | COVERED (replacement decided); Stage A leaves the inline literal as it is, the 10-dim profile is in `managers/<key>.json` (A5), Stage B rebuilds the radar |
| Draft board performance map | inline `HEATMAP_DATA` (~250 KB) | {name: {board: {"r_s": {round, slot, avg_surplus, n_seasons, picks[]}}, tiers, positions, best_picks, worst_picks, career_wtd_avg, total_picks}} | `draft_heatmap` rules on `draft_surplus` + `draft_career_grades` (`publish/pages/board_map.py`; rules in METRICS_REFERENCE) | `draft/draft_heatmap.json` (identical to the page), every field checked | COVERED (A5) |
| Franchise leaders table, scatter | file `franchise_leaders.json` | {name: [{player, position, season, weeks_rostered, games_played, total_points}]} | `franchise_leaders` | `records/franchise_leaders.json`, PASS | COVERED |
| Roster timeline | file `roster_stints.json` | {name: {player: {position, stints: [{season, start, end, started[]}]}}} | `roster_stints` | `waivers/roster_stints.json`, PASS | COVERED |
| Best single-week performances | file `best_single_week.json` | {name: [{player, position, season, week, points}]}, top 25 per position and season | `best_weeks` | `records/best_single_week.json`, PASS | COVERED |
| Headshots | file `player_headshots.json` | {"name|POS": url} | `pages/headshots.py` | `headshots/player_headshots.json`, coverage PASS | COVERED (A8c: ESPN images by player id, golden `headshots/player_headshots.json`) |
| Pills, colors, aliases, season colors | HTML + inline | config | config | | CONFIG |

`update_2026.py` patched the live season into five of these files in place (matchups.json, franchise_leaders, best_single_week, roster_stints, preach_manager_stats.csv). Publish writes each whole, every run.

### 4.3 matchups.html

| Element | Where | Shape | Producer | Golden / check | Status |
|---|---|---|---|---|---|
| Every game with box scores | file `matchups.json` (638 games through 2026 week 2, 1.5 MB) | [{id, season, week, weekLabel, isPlayoff, teamA/teamB: {manager, lastName, fantasyTeam, score, outcome, starters[{name,pos,slot,pts}], bench[]}, margin, combined}] | `games` + `box_scores` | `records/matchups.json`, 1,276 sides PASS | COVERED |
| Round names | inline `ROUND_NAMES` | {season: {round: {full, short}}} | `rules.playoff_rounds` | | CONFIG |
| Superlative exclusion | inline `SUPERLATIVE_EXCLUDE` | game id | `analysis.exclude_games` | | CONFIG |
| Colors | inline | | | | CONFIG |

### 4.4 weekly-rankings.html

| Element | Where | Shape | Producer | Golden / check | Status |
|---|---|---|---|---|---|
| Manifest | file `rankings/manifest.json` | [{season, weeks[], playoffRounds?, weekLabels?}] | built from the editorial files present | `rankings/rankings_files.json`, PASS | COVERED (A8b, generated) |
| Weekly rankings, 2021-2025 | files `rankings/<season>_weekNN.json` | {season, week, teams[{manager, rank, prev_rank, rank_change, avg_rank, ppg_to_date, record_to_date, last_score, streak, synopsis, blurb}]} | editorial files (rank, synopsis, blurb); record, PPG, last score, streak and the rank fields derived from `games` and the ranks | `rankings/rankings_files.json`, PASS (avg_rank by the older rule, 1-place typing excused) | COVERED (A8b) |
| Playoff round preview | file `rankings/2025_playoff_quarterfinals.json` | {season, round, round_label, overview, matchups[{matchup_label, higher_seed/lower_seed {seed, team, manager, projection, regular_season_avg, record}, pick, blurb}]} | editorial file as written (its projections were a snapshot) | same, PASS | EDITORIAL (A8b); a generated preview is Stage B |
| Weekly rankings, live season | files `rankings/2026_weekNN.json` | teams[] adds: proj_ppg, proj_ppg_ros, sos_avg_opp_ppg, sos_rank, draft_grade, draft_surplus_total, draft_picks[{player, nfl_team, pos, round, pick_in_round, overall, espn_adp, adp_deviation, grade, surplus_value}], week 1 only: adp_value, position_spend {QB,RB,WR,TE}, draft_archetype {cluster_id, name, confidence, comparisons[3], dist_to_nearest, margin_over_2nd}; file adds: player_season_totals {"name|POS": pts}, undrafted_players[{player, pos, nfl_team, manager?}], matchup_of_the_week {team_a/b {manager, rank, record, proj_total, starters[{player, nfl_team, pos, slot, opp, proj}]}, blurb}, hide_archetype_link | see split below | `rankings/rankings_files.json`, PASS; generator checked on 2026 (draft record and week 1 measures exact, drift INFO) | COVERED (A8b) |
| Playoff odds chart | file `rankings/playoff_odds.json` | {season: {cutoff, max_week, weeks: {week: {name: odds}}}} | `playoff_odds` | `playoff_odds/playoff_odds.json`, backtest + live week 3 PASS | COVERED |
| Headshots | file `player_headshots.json` | as 3 | `pages/headshots.py` | as 3 | COVERED (A8c: ESPN images by player id, golden `headshots/player_headshots.json`) |
| `DRAFT_METRICS` labels and descriptions | inline | metadata | | | TEMPLATE |
| `MANAGER_COLORS`, `LASTNAME_MAP`, `SEASON_THEME_COLORS` | inline | | | | CONFIG |

Live-season computed fields and their engine source. The builder that wrote them is lost; A8b stores the published values as frozen snapshots and generates new weeks with `engine rankings new` (rules in METRICS_REFERENCE, Weekly Rankings):

| Field | Engine source | Status |
|---|---|---|
| record_to_date, ppg_to_date, last_score, streak | `games` (regular season, before the week) | DERIVED every build, exact on every published week |
| prev_rank, rank_change, avg_rank | the editorial ranks | DERIVED; avg_rank uses the 2026 rule everywhere (decision 7.13) |
| proj_ppg | `projected_team_weeks` | SNAPSHOT |
| proj_ppg_ros, sos_avg_opp_ppg, sos_rank | `projected_sos` (ESPN's current schedule) | SNAPSHOT; the published 2026 values used an early draft of the schedule |
| draft_grade, draft_surplus_total, draft_picks[].surplus_value | `draft_season_grades`, `draft_surplus` | SNAPSHOT |
| draft_picks[] draft-day fields (team, ADP, deviation) | `draft_picks`, `adp`, written in week 1 and copied | SNAPSHOT; checked against 2026 week 1 (exact apart from name suffixes; ADP INFO: the engine has FantasyPros for 2026, the file ESPN's draft-day ADP) |
| adp_value, position_spend (week 1) | the week 1 picks | SNAPSHOT; rules recovered exactly (capital halves every three rounds) |
| draft_archetype (week 1) | `draft_archetype_matches` (new in A8b: nearest finished drafts and center margins in the model's space), names from `archetypes.yaml` | SNAPSHOT; the published one came from the retired archetype model |
| player_season_totals, undrafted_players | `player_stats`, `projections` (rosters), `draft_picks` | SNAPSHOT; engine rule sized to the page's pools (top 20 free agents per position) |
| matchup_of_the_week starters and projections | `projected_lineups`, `pro_games` (new in A8b: NFL opponents) | SNAPSHOT (every team's lineup); the pair and blurb EDITORIAL |
| rank, synopsis, blurb, screenshots, label, hide_archetype_link | editorial | EDITORIAL |

### 4.5 trade-value.html

| Element | Where | Shape | Producer | Golden / check | Status |
|---|---|---|---|---|---|
| `LEADERBOARD` (avg QUAD, n), career + per season, visible managers | global `page_data.js` | {filter: {name: {quad, n}}} | `trade_metrics` | none (metrics_final checked upstream) | NO GOLDEN |
| `QUAD_SCALE`, `TG_SCALE`, `RG_SCALE`, `FIT_SCALE`, `NEC_SCALE` (over all managers) | global `page_data.js` | {min, max} | `trade_metrics` | none | NO GOLDEN |
| `BEST_WORST` | global `page_data.js` | {filter: {name: {best, worst: {got[], gave[], quad}}}} | `trade_metrics` + names | none | NO GOLDEN |
| `TRADES` (All Trades table, visible managers, 328 sides) | global `page_data.js` | [{s, m, got[], gave[], tg, rg, fit, nec, quad, multi, wk}] | `trade_metrics` | none | NO GOLDEN; the shipped file has `wk`, the script in `_legacy` does not write it (a later version wrote the file) |
| `NETWORK_DATA` | global `network_data.js` | {nodes[{id, trades}], edges[{a, b, n, netDiff, positions{}, seasons[]}]} | `trade_metrics` + positions | none | NO GOLDEN |
| `WINPCT_DATA` | global `winpct_data.js` | [{m, winPct, games, trades, avgQuad}], win% over counted games | `lineup_efficiency` or `ms` + `trade_metrics` | none | NO GOLDEN |
| `TRADE_NODES` (trade explorer, all managers incl. hidden) | global `trade_explorer_data.js` | [{gid, season, sp, multi, managers[{m, got, gave, tg, rg, fit, nec, quad}], positions[]}] | `trade_explorer` + `trades.explorer_nodes` | `trades/trade_explorer_data.json`, PASS | COVERED |
| `TRADE_WEEK_DATA` (trades by week, all managers) | global `trade_week_data.js` | [{g, s, wk, m, multi, got, gave, tg, rg, fit, nec, quad}] (3-place rounding) | `trade_metrics` | none | NO GOLDEN |
| `MOST_TRADED` | global `most_traded_data.js` | [{player, count, seasons[], managers[], pos}] (283 players; includes hidden managers) | `trade_items` | none | NO PRODUCER |
| `LEADERBOARD_TOTALS` (total QUAD) | inline | {filter: {name: total}} | `trade_metrics` | none | NO GOLDEN |

All five `regenerate_data_files.py` outputs and `most_traded_data.js` become one `trade-value.json`.

### 4.6 position-impact.html

| Element | Where | Shape | Producer | Golden / check | Status |
|---|---|---|---|---|---|
| Whole page | file `position_impact_data.json` | {positions, nth_pick, total_games, flip_rates, net_impact, season_flip_rate, consistency, draft_vs_waiver, draft_capital, performance_correlation, acquisition_source, draft_order} | `position_*` tables; payload builder already exists as `legacy_position_impact.build_payloads` | `position_impact/position_impact_data.json`, 12 checks PASS | COVERED |

### 4.7 dst-impact.html

| Element | Where | Shape | Producer | Golden / check | Status |
|---|---|---|---|---|---|
| Whole page | file `dst_removed_data.json` | {league {total_games, total_flips, all_games[]}, managers {name: {games, actual_record, adj_record, flipped_count, flipped_games[], acquisition, dst_ppg}}, season_playoffs, position_flip_rates, draft_vs_waiver, position_consistency, dst_performance, draft_capital} | `dst_*` + `position_*` tables; same payload builder | `position_impact/dst_removed_data.json`, 8 checks PASS | COVERED |
| `MANAGER_COLOR_HEX` | inline | | | | CONFIG |

### 4.8 schedule_release.html

| Element | Where | Shape | Producer | Golden / check | Status |
|---|---|---|---|---|---|
| Per-manager schedule with history | file `manager_schedule.json` | {name: [{week, week_type, opponent, interconference, my_wins, opp_wins, total_games, most_recent, closest, blowout {season, week, score_a, score_b, winner, margin}, game_log[], rematch (null), trade_count (null), games[{season, label, score_a, score_b, winner, mvp_name, mvp_pos, mvp_pts}]}]} | pairs from the season's `matchups` + `future_matchups`; history from `games` + `box_scores`; trade counts from `trade_sides`; themes and what they highlight from editorial `schedule_themes.yaml` | `schedule_release/manager_schedule.json`, PASS (A8a; 2 scores from before an ESPN stat correction) | COVERED (A8a) |
| League schedule by week | file `schedule_by_week.json` | [{week, week_type, matchups[{team_a, team_b, interconference}]}] | pairs from ESPN; week_type from editorial `schedule_themes.yaml` ("Standard" when absent) | `schedule_release/schedule_by_week.json`, PASS (A8a; pairs compared regardless of order and orientation) | COVERED (A8a) |
| Week themes | `data/schedule_2026.csv` (no page reads it directly) | Week, Week_Type, Team_A, Team_B, confs, Interconference | league-authored | `sos/schedule_2026.csv` is an older draft | LEAGUE-AUTHORED |
| `CONF` (conference per manager), `MANAGER_COLOR`, `THEME_*` maps, og meta "2026 Schedule Release" | inline / head | | `ms.conference` of the live season; config; theme vocabulary is league-authored | | CONFIG / LEAGUE-AUTHORED |

### 4.9 champions.html

| Element | Where | Shape | Producer | Golden / check | Status |
|---|---|---|---|---|---|
| Champion cards | inline `CHAMPS` (6) | [{year, manager, team, record, rs_ppg, po_ppg, runner_up, rounds[{label, week, total_score, roster[{pos, name, week_score, ppg}]}]}] | `ms` (champion, record, PF/G), `games` + `box_scores` (rounds), player PPG (definition to recover: D/ST values suggest PPG while on that roster) | `champions/champions_inline.json` (A8a), PASS: rules recovered (player PPG = points per game on this roster before the champion's first playoff game, IR and benched zeros left out); excused: older cards typed PF/G to 1 place, hand-typed name suffixes, one team name capitalized by hand; starter order changes to the shared box-score order | COVERED (A8a) |
| Finals chart and timeline | inline `FINALS` (6) | [{year, champ, champ_score, runner, runner_score}] | `games` (championship game) | same, PASS | COVERED (A8a) |
| Trophy photo, page copy | HTML | image path | | | EDITORIAL |
| `LOGO_MAP`, `TINT_HEX` | inline | | | | CONFIG |

### 4.10 surplus-value.html

| Element | Where | Shape | Producer | Golden / check | Status |
|---|---|---|---|---|---|
| `CAREER_GRADES` | inline | [{rank, manager, avg_surplus, total_surplus, total_picks, seasons}] | `draft_career_grades` | `draft/surplus_value_data.json`, PASS | COVERED |
| `SEASON_GRADES` | inline | {season: {name: grade}} | `draft_season_grades` | same, PASS | COVERED |
| `HEATMAP_TIPS` | inline (83) | {"season|name": {best, worst}} as text "Player RdN (+x.xx)" | `draft_surplus` (weighted surplus) | `draft/surplus_value_page.json` | COVERED (A5) |
| `MANAGER_BW` | inline (14) | [{manager, best, bestPos, bestSeason, bestRd, bestSurplus, worst...}] | `draft_surplus` (weighted surplus) | same | COVERED (A5) |
| `ALL_BEST_PICKS` (15), `SEASON_BEST` (10 per season), `ALL_WORST_PICKS` (15), `SEASON_WORST` (5 per season) | inline | [{rank, player, pos, round, pick, season, actual, expected, surplus, manager}] | `draft_surplus` (by weighted surplus; actual = PRV) | same | COVERED (A5) |
| `POP_SURPLUS_MIN`, `POP_SURPLUS_MAX` | inline constants | numbers | `draft_surplus` (unweighted surplus, 2 places) | same | COVERED (A5) |
| `SEASONS` [2020-2025] | inline | | config (finished seasons) | | CONFIG |

### 4.11 draft-analysis.html

| Element | Where | Shape | Producer | Golden / check | Status |
|---|---|---|---|---|---|
| Slot table (14 rows: seasons, playoff %, champ %, PF/G, dominance, expected, over/under) | HTML | table | `draft_slot_results` (`manager_seasons.draft_slots`) | `manager_seasons/draft_slots_page.json`, PASS (Champ % and PF/G contradicted the source; engine uses real values) | COVERED |
| `PLAYOFF_RATES`, `OVERPERFS` (slot charts) | inline | [num] x14 | `draft_slot_results` | same | COVERED |
| `SLOT_DATA` (who drafted from each slot, through 2026) | inline | {slot: [[name, season]]} | `draft_slot_managers` | same, PASS | COVERED |
| `HR_BY_ROUND`, `HR_BY_POS`, tier cards (76.9%, 38.8%, 9.9% in HTML) | inline + HTML | [{round, tier, hit_rate, total_picks, hits, rb..dst}], {pos: [early, middle, late]} | `draft_hits`, `draft_hit_thresholds` | `draft/draft_analysis_page.json` (A5; the page's own blocks) and `draft/hit_rate_data.json` | COVERED |
| `ALL_TIME_STEALS` (10), `SEASON_STEALS` (10 per season) | inline | [{rank, player, pos, round, slot, season, ppg, above, games, manager}] | `draft.steals` | same; the page's season lists contradict their script on 89 values (retyped from another file), excused by that pattern | COVERED |
| `CAREER_PREVIEW` | inline | [{manager, avg, rank, seasons}] | `draft_career_grades` | `draft/surplus_value_data.json`, PASS | COVERED |
| `ABOVE_AVG_CEIL` 14.03 ("confirmed all-time high") | inline constant | number | the highest points above average on the all-time steals list | `draft/draft_analysis_page.json` | COVERED (A5) |
| Slot 15 (2020 only) | not shown today | | exists in `draft_slot_results` (seasons 1, over/under 0 by construction) | | decision 7.4: in `SLOT_DATA` from A5; the results need 2 seasons |

### 4.12 draft-fingerprints.html

| Element | Where | Shape | Producer | Golden / check | Status |
|---|---|---|---|---|---|
| `DATA` (~245 KB): FINGERPRINTS (16 managers incl. hidden, per season + career: raw, normalized, posdev, all, cluster, archetype, outcomes), RADAR/POSDEV dims and labels, EXPLORER_GROUPS, METRIC_META, GLOBAL_RANGES, CAREER_RANGES, ARCHETYPES {cluster_summary[4], assignments[85], k, n_*, stats}, MGR_COLORS, MANAGERS_ORDERED, SEASON_YEARS | inline | as listed | `draft_profile_seasons`, `draft_profile_career`, `draft_archetypes`, `draft_archetype_stats`, `draft_profiles.ranges` | `draft/draft_fingerprints_page.json`, 8 page checks PASS; A5: the data keys of `DATA` replaced, template and config keys kept | COVERED (data); labels, groups, METRIC_META are TEMPLATE; archetype names and descriptions EDITORIAL (`leagues/preach/editorial/archetypes.yaml`, decision 7.6) |
| `GROUP_DESCRIPTIONS`, methodology prose with numbers (p=0.232, p=0.568, 85% variance, k=4, "7 and 2 of 85" imputed) | inline + HTML | text | numbers from `draft_archetype_stats` (incl. `fill_notes`) | covered by the stats check | TEMPLATE text + data fields |

### 4.13 draft-history.html

| Element | Where | Shape | Producer | Golden / check | Status |
|---|---|---|---|---|---|
| `DRAFT` (every pick 2020-2026 with PPG, games) | inline (~83 KB) | {season: {round: [{p, pos, ppg, g}]}} | `draft_board` + `draft.board_data` | `draft/draft_board_page.json`, PASS | COVERED (A5 replaces it) |
| `SLOT_ORDER` (round-1 order per season, 15 in 2020) | inline | {season: [name]} | `draft.board_data` | same, PASS | COVERED (A5 replaces it) |
| `MANAGERS` | inline | [{name, logo, short}] | config | | CONFIG |

### 4.14 lineup-efficiency.html

Golden: `lineups/lineup_efficiency_page.json` (every inline block, A6b). Rules in METRICS_REFERENCE, Lineup Efficiency.

| Element | Where | Shape | Producer | Golden / check | Status |
|---|---|---|---|---|---|
| `EFFICIENCY_BY_FILTER` | inline | {filter: [{m, g (avg gap), w}]} | `lineup_efficiency` (averaged games: no forfeits, no neglected lineups) | page golden, PASS | COVERED (A6b) |
| `MISSED_WINS_BY_FILTER` | inline | {filter: [{manager, weeks, losses, n, rate, reg, po}]} | `lineup_efficiency` | same (order of tied rates not reproducible; values checked by manager) | COVERED (A6b) |
| `BLUNDERS_BY_FILTER` (top 10 career and per season) | inline | {filter: [{season, week, manager, actual, optimal, gap, outcome, missed}]} | `lineup_efficiency` | same | COVERED (A6b) |
| `ROSTERS_BY_FILTER` (box score of each blunder) | inline (~93 KB) | {filter: [{season, week, manager, starters[], bench[]}]} | `lineups` (ESPN's roster order) | same | COVERED (A6b) |
| `DEPTH_BY_FILTER`, `DEPTH_ADJUSTED_BY_FILTER`, `DEPTH_VS_WINS_DATA` | inline | {filter: [{m, d}]}, {filter: [{m, raw, depth, adj}]}, [{m, s, d, wr}] | `lineups.bench_depth`, `lineups.depth_adjusted` (ported in A6b, legacy mode first) | same | COVERED (A6b) |
| `SEASON_TREND_DATA` | inline | [{s, g}] | `lineup_efficiency` | same | COVERED (A6b) |
| `HEATMAP_DATA`, `CAREER_AVG_DATA`, `HEATMAP_MANAGERS` | inline | [[season, week, manager index, gap, flag]] x1222, [[manager index, column, avg, n]] | `lineup_efficiency` | same | COVERED (A6b); playoff columns by role in engine mode (decision 7.11) |
| `EFFICIENCY_GLOBAL_MIN/MAX`, `HEATMAP_GAP_MIN/MAX` | inline constants | numbers | derived | same | COVERED (A6b) |
| Prose "r about 0.30", "2-12 playoff games" | HTML | text | derived | | TEMPLATE + data field |

### 4.15 waiver-value.html

| Element | Where | Shape | Producer | Golden / check | Status |
|---|---|---|---|---|---|
| `LEADERBOARD_FULL` | inline | {filter: {pos: [{m, ppw, z, n}]}} | `waiver_leaderboard` | `waivers/waiver_page.json`, PASS | COVERED |
| `BEST_BY_MANAGER` | inline | {filter: {pos: {name: {p, tz, wk}}}} | `waiver_best` | same, PASS | COVERED |
| `BEST_PICKUPS_BY_FILTER` | inline | {filter: {pos: [{s, m, p, pos, wk, ppw, totalz, avgz, type}]}} | `waiver_best` | same, PASS | COVERED |
| `CONTESTED_SPLIT` | inline | [{m, faPpw, faZ, faN, wvPpw, wvZ, wvN, careerPpw, careerZ}] | `waiver_leaderboard` | same, PASS | COVERED |
| `WAIVER_STINTS` (1,757) | inline (~186 KB) | [{s, m, t, sw, wk, z, ppw, p, pos}] | `waiver_stints` | `waivers/waiver_stints_full.csv`, PASS | COVERED |
| `POSITION_SCALE`, `WAIVER_Z_GLOBAL_*`, `UPSIDE_MIN/MAX`, `BEST_TOTALZ_*`, `BEST_AVGZ_*` | inline constants | numbers | derived (rules in METRICS_REFERENCE, Waiver Value) | `waivers/waiver_value_page.json` | COVERED (A6a) |

### 4.16 extra-analytics.html

A7a replaces the matchup sections (head-to-head, closest games, luck chart, schedule swap, the conference markup) from `matchup_history/extra_analytics_inline.json` (every block, the typed conference markup included); A7b the model sections (quarterly model, positional production, win% attribution, championship gauntlet), checked against the same golden refrozen with the model literals. The data file carries the model sections by manager key (`quarterly`, `positional`, `attribution`, `gauntlet`).

| Element | Where | Shape | Producer | Golden / check | Status |
|---|---|---|---|---|---|
| Head-to-head matrix | inline `managers`, `h2h` | {name: {name: {w, l, pct}}} | `head_to_head` | `matchup_history/extra_analytics_matchups.json`, PASS | COVERED |
| Closest games | inline `CLOSEST` | {all, regular, playoff: [{w, ws, l, ls, m, po, when}]} | `matchup_history.closest` | same, 3 checks PASS | COVERED |
| Championship gauntlet | inline `CHAMPIONS`, `CHAMPION_RANKS`, `HARDEST`, `EASIEST` | cards with games; {"season_name": {rank, total}}; lists | `gauntlet_champions`, `gauntlet_window_games`, `gauntlet.extremes` | `gauntlet/extra_analytics_gauntlet.json`, 7 checks PASS; legacy view A7b: lists exact, ranks exact up to legacy ties (three champions sit in 2-way ties on the rounded score, whose order depends on the pandas version; excused inside the tied group as analyze does), `sameLength` for a 4-week champion window; cards rebuilt with the raw-dominance variant the page used, surges and raw points excused as analyze does; team names from ESPN, with the page's shortened names in editorial `team_names.yaml` (case and emoji differences excused) | COVERED (A7b) |
| Conference analysis (cards, manager table, season table, rivalries, prose) | HTML | tables | `conference_summary`, `conference_managers`, `conference_seasons`, `rivalries` + `order_rivalries` | same, 4 checks PASS (avg PF/game was typed by hand) | COVERED; prose EDITORIAL |
| Career schedule luck chart | inline `luckData` | [{name, actual, predicted, luck}] | `schedule_luck` summed over finished seasons | `matchup_history/extra_analytics_inline.json` (A7a): equals `schedule_luck_season.csv` summed, except Gorman's typed 38 expected wins (file 39); Hancock and Bileydi follow the older matchup file, as analyze excuses | COVERED (A7a); a season filter is Stage B (Ethan, session 7) |
| Schedule swap | inline `SCHEDULE_SWAP_DATA` | {season: {name: {actual, alt {name: {w, l, games, pct}}, avg_pct, wins_gained}}} | `schedule_swap`, `schedule_swap_summary` | `schedule/schedule_swap.json`, 2 checks PASS | COVERED |
| `SS_CAVEATS` (2020 byes, 2024 forfeit) | inline | text | facts from data (odd team count, `exclude_games`) | | EDITORIAL |
| Quarterly model | inline `coefs`, `corrs`, `pvals` | [num] x4 | `quarterly_coefficients`, `quarterly_fit` | regressions golden (coefs replaced, Ethan); legacy view A7b: labels and corrs match, coefs and pvals excused (session 4 decision) | COVERED (A7b) |
| Positional production | inline `DATA`, `STD_COEF`, `COEF_PVAL`, `CORR_R` | [{mgr, winpct, avg{}, std{}}], {pos: num} | `position_career`, `position_coefficients`, `position_fit` | `regressions/extra_analytics_regressions.json`, 3 checks PASS; legacy view A7b: rows by manager, order by win % (three managers tie at 48.1 in the legacy script's order), coefficients within analyze's tolerances | COVERED (A7b) |
| Win% attribution | inline `DATA`, `COEF_VALS` | {name: {winpct, draft, waiver, lineup, trade, luck, predicted, residual}}, [std coef x5] | `attribution_managers`, `attribution_coefficients`, `attribution_fit` | `attribution/win_attribution_final.json`, 4 checks PASS; legacy view A7b exact (`DATA#1`, intercept, coefficient order and values) | COVERED (A7b) |
| R2 history (`R2_LABELS`, `R2_VALS`) | inline | model versions and their R2 | history of past model versions; only the last value is the current fit | legacy view A7b exact | EDITORIAL (A7b writes the last value from `attribution_fit`; the history moves to an editorial file in Stage B) |
| 14 logo paths | inline | | | | CONFIG |

### 4.17 transaction-analysis.html

Hub page with links to the three transaction pages. No data. Prose "six seasons (2020-2025)" and the excluded names come from config.

## 5. Findings that matter for publish

1. **Client-side analytics.** index.html and managers.html compute career totals, ranks, head-to-head, score distributions, weekly league averages and schedule luck in the browser (data-engine.js and managers.html). managers.html's luck is the legacy median method re-implemented in JS, so it will not match the engine's `schedule_luck` (half wins). Publish should emit these numbers so there is one definition.
2. **Scripts are not always the spec.** `page_data.js` on the site has a `wk` field that `regenerate_data_files.py` does not write; the shipped file came from a later version. For every Stage A check the shipped file is the golden and the script is only a guide.
3. **Page-layer code already exists in the verify modules.** `legacy_position_impact.build_payloads` builds both impact payloads and `compare_json` diffs nested JSON; `trades.explorer_nodes`, `draft.board_data`, `draft_profiles.ranges`, `matchup_history.closest`/`order_rivalries`, `gauntlet.extremes` are page helpers already. They move into `engine/publish/`.
4. **Derived scale constants are hardcoded** in five pages (`POP_SURPLUS_*`, `WAIVER_Z_GLOBAL_*`, `UPSIDE_*`, `BEST_*`, `EFFICIENCY_GLOBAL_*`, `HEATMAP_GAP_*`, `ABOVE_AVG_CEIL`). They become fields of each page's JSON, computed at publish.
5. **Hidden managers already appear on some pages**: as opponents in matchups.json, in the trade explorer, trades by week and most traded, in the 2020 draft board and slot order, in draft-fingerprints data (16 managers), in playoff odds (2020) and in one archetype comparison in `2026_week01.json`. "Drop hidden rows everywhere" would remove real games, trades and picks. See decision 7.3.
6. **Live season coverage differs by page.** index, managers, matchups, draft-history, weekly rankings, playoff odds show 2026; surplus-value, lineup-efficiency, waiver-value, trade-value and extra-analytics stop at 2025, while the engine tables include the live season's finished weeks. Stage A reproduces each page's current coverage; showing the live season elsewhere is decision 7.8.
7. **Past rankings files cannot be regenerated.** Their projections were snapshots and are not retained anywhere. They stay as frozen editorial files; only the live season's computed fields are generated.
8. **Headshots** use NFL.com image ids that cannot be derived from ESPN data, so the file cannot be produced for another league. See decision 7.5.
9. **Two metrics documented in METRICS_REFERENCE had no engine producer**: Bench Depth and Depth-Adjusted Efficiency (lineup-efficiency.html). Ported in A6b (`analytics/lineups.py`), legacy mode reproducing the page.
10. **Sizes.** The largest page payloads today: matchups.json 1.5 MB, managers.html (~1.8 MB across its data files plus ~280 KB inline), waiver-value ~284 KB, draft-fingerprints ~245 KB.

## 6. Target output

`engine build` writes `dist/`. Every page model file has a top-level `meta` block (schema, schema_version, build_id, generated_at), keys managers by `manager_key`, and is checked against its JSON schema in `engine/publish/schemas/`; names, colors and logos come from `config.json`. Page models live under `data/v1/` (the major schema version), so they never collide with the legacy files the current pages read, and a later breaking change can ship as `data/v2/` beside it.

```
dist/
  config.json                    league, seasons (first, finished, live), managers (key, name, short, colors,
                                 logos, hidden, seasons), theme, round names, features, page list
  build-manifest.json            every file, its sha256, and whether it was copied or generated
  data/v1/
    index.json                   leaderboard (career totals, visible-only ranks), current champion (A2)
    managers/<key>.json          one file per visible manager: career, seasons, head-to-head, rivals, weekly
                                 scores with league averages, schedule luck, franchise leaders, roster stints,
                                 best weeks (A2); draft profile and draft board map (A5)
    matchups.json                games with box scores (A2)
    headshots.json               player id -> image url (A8, decision 7.5)
    weekly-rankings/index.json   every ranked week and playoff preview
    weekly-rankings/<season>-wNN.json   editorial file merged with its snapshot and derived fields
    weekly-rankings/<season>-playoff-<round>.json   playoff previews
    trade-value.json             leaderboard, totals, scales, best/worst, trades, network, win%, explorer,
                                 by week, most traded
    position-impact.json, dst-impact.json, schedule-release.json, champions.json,
    surplus-value.json, draft-analysis.json, draft-fingerprints.json, draft-history.json,
    lineup-efficiency.json, waiver-value.json, extra-analytics.json
```

index.json's leaderboard also carries the pill stats managers.html shows, so there is no separate `managers/index.json`. Playoff odds are their own model, `data/v1/playoff-odds.json` (A4), which the weekly rankings page reads beside its weekly files.

**Page availability.** Each page in the template's page list (`engine/publish/site.py`) declares the page model files it needs. `config.json` lists a page only when its league feature is on and the build produced its data, so the nav (Stage B) adapts to each league: a league whose lineups never start a D/ST gets no Life Without Defense page. Position Impact and Life Without Defense are sub-pages of Extra Analytics (Ethan, session 6).

Stage A (decision 7.1) additionally writes the legacy files (`data/matchups.json`, `data/preach_manager_stats.csv`, and so on) at their current paths, so the current pages run from `dist/` unchanged, and so each output can be checked against its golden. Data inline in a page is replaced in `dist/`'s copy of that page (the live page is untouched); `tools/freeze_golden.py` freezes the current inline block or `.js` file as its golden first. A legacy view uses the manager spelling of the file it replaces ("Carmine Pittelli Jr." on matchups.html). Its Stage A check builds it from legacy-mode analysis, reads it back the way the golden is read, and runs the same comparison (with the same excuses) `analyze --verify` runs on the engine tables.

CI: build `dist/` from fixtures, validate every file against its schema, run `tools/check_paths.py dist`, and the style checks. The full build with real data runs in the Codespace (as `--verify` does now).

## 7. Decisions (Ethan, session 6)

| # | Decision | Outcome |
|---|---|---|
| 7.1 | Parity strategy | Two stages. Stage A: publish builds one page model per page (keyed by manager key) plus a thin legacy view that reshapes it into today's files; the legacy view, fed legacy-mode analysis, must reproduce every current file and inline block (value-level diff at the page's rounding), then engine mode writes the new numbers and the differences are listed for review. Stage B: pages move into `web/` and read the page model directly; each page's legacy view is deleted when it moves. Rollout follows section 8. |
| 7.2 | Output location during phase 4 | `dist/`, gitignored, built in the Codespace and in CI; published as a preview under `/next/` once Pages deploys from Actions (section 8). The live root is served byte-for-byte unchanged until cutover. |
| 7.3 | Hidden managers at publish | Dropped from manager-level outputs (leaderboards, ranks, selectors, per-manager files, chart series). Kept, labelled, on event rows involving real games, trades or picks: matchups, trade explorer, trades by week, most traded, the 2020 draft board and slot order, archetype comparisons. A5 reads lists of picks (late-round steals, best and worst picks) as real picks: they keep excluded managers' picks, as the steals list on the page already does; grades, draft tips, highs and lows and the board map drop them. |
| 7.4 | Slot 15 on draft-analysis.html | Not in the slot results table or charts (one season, over/under 0 by construction); kept in the "who drafted from each slot" list. Generic rule: a slot needs at least 2 seasons to appear in results. |
| 7.5 | Headshots | Generated from ESPN player ids (ESPN image URL pattern), for any league; the NFL.com file is retired. Pages keep their missing-image fallback. |
| 7.6 | Archetype names | Editorial file keyed by stable cluster id; leagues without one get a generated label from the cluster's defining traits. |
| 7.7 | schedule_release data | Matchups from ESPN (the season's played games and `future_matchups`), history from `games` + `box_scores`; week themes league-authored and optional (page hides them when absent). Correction (A8a): `rematch` and `trade_count` are not unused; the page shows them on its Big Game Week and Trade Partner Week cards. The engine computes both for every pair (rematch = the pair's deepest playoff meeting, most recent on ties; trades = trades between them, one per trade) and the league's `schedule_themes.yaml` says which theme highlights which. |
| 7.8 | Live season | Stage A keeps each page's current coverage. After that every page shows data through the most recent finished week or season where it makes sense: season-filterable pages add the live season (marked live, finished weeks only); model fits (attribution, regressions, gauntlet ranks, draft surplus comparisons) stay on finished seasons. Page by page list in each Stage A PR. |
| 7.9 | JSON granularity | One file per page plus `config.json` and `headshots.json`; managers split per manager; rankings one file per week. Editorial rankings are stored separately from computed fields with their own schema, because a commissioner-facing editor will later write them (phase 5/8). |
| 7.10 | Weekly update flow | Now: one command (`engine update`: pull, normalize, analyze, build, verify). At cutover: a scheduled GitHub Action (during the season, after Monday night and Tuesday waivers, plus a manual "Run workflow" button) that deploys only when the build and checks pass. Later (phase 8): an on-page refresh button through a small authenticated relay, or server-side in a hosted product (section 8.4). |
| 7.11 | Lineup career grid playoff columns (A6b) | The page labels columns 15-18 as playoff rounds but its data used the raw week number, mixing 2020-2021 playoff round 1 into week 14. The engine places playoff weeks by round, counted back from the championship (after the league's longest regular season, so any season length works). Legacy mode keeps the raw week for the Stage A check. |
| 7.12 | Excluded managers' benches in the bench average (A6b) | Counted, as in every other calculation (they are only hidden). The page left them out (2020 only); legacy mode reproduces that. |
| 7.13 | Weekly rankings layout and avg_rank (A8b, 2026-10-05) | Each ranked week = an editorial file (`leagues/<league>/editorial/rankings/`), a frozen snapshot of the computed fields (`leagues/<league>/snapshots/rankings/`, written once by `engine rankings new`, never rewritten), and fields derived every build (record, PPG, last score, streak, prev_rank, rank_change, avg_rank, manifest). avg_rank uses the 2026 rule in every season (running average including the week, 1 place, blank in the first week); files before 2026 averaged the prior weeks. SOS and rest-of-season projections use ESPN's current schedule. Until M1, `tools/split_rankings.py` imports the PC's weekly files. |

## 8. Rollout plan

The goal is a transition nobody in the league notices except where numbers change on purpose.

### 8.1 Principles

- The live site never shows a half-built state: a deploy happens only after every check passes; otherwise the last good site stays up and the run fails loudly.
- Every step can be undone in one move (re-run the previous deploy, or revert one commit).
- Numbers change only on purpose, with a reviewed list of what changed (the INFO lines from `--verify`).
- One pipeline: the same `engine update` runs in the Codespace, in CI previews and in the scheduled job.

### 8.2 Milestones

| Milestone | What happens | Live site |
|---|---|---|
| M0 Preview | Pages switches from "deploy from branch" to a GitHub Actions deploy that publishes the current root files unchanged (checked file by file against `git ls-files`), plus `dist/` at `/next/`. The Action runs `engine update` with the ESPN cookies as repository secrets (Actions secrets, separate from the Codespace ones), caching finished seasons. | unchanged, same files |
| M1 Engine powers the live site | After Stage A: `/next/` (current pages, engine data in legacy shapes) matches the live site in legacy mode with zero unexplained differences. Then the deploy serves engine-mode data under the current pages. The legacy weekly process on the PC stops. | same pages, engine numbers (reviewed list of changes) |
| M2 New frontend | Stage B pages are built at `/next/` and checked side by side. Cutover (phase 6) swaps `/next/` to the root in one deploy; old root files are removed in a later PR once the new site has run a week or two. | new pages, same numbers as M1 |

### 8.3 Safety checks on every deploy

- `engine build --verify`: legacy-mode outputs against the goldens (while they exist), JSON schema validation, path check on `dist/`, style checks.
- Sanity checks on the fresh data: game and week counts never go down, every visible manager present, no NaN or empty required fields, the live week not ahead of ESPN's.
- Page smoke test: headless Chromium opens every page, fails on console errors or missing data, and saves screenshots so a run can be compared with the last one.
- Cache safety: `config.json` carries a build id and pages fetch data with it, so nobody sees a mix of old and new files; data and pages deploy together.
- Rollback: re-run the last good deploy (its `dist/` is kept as a workflow artifact) or revert the commit.
- Failure alerts: a failed scheduled run emails the repo owner; expired ESPN cookies are reported by name.

### 8.4 Refresh button

A static site cannot run the pipeline itself, and the page cannot hold the GitHub token or ESPN cookies. An on-page refresh button therefore needs a small server piece: the button calls a relay (for example a free-tier serverless function) that holds the token, checks a commissioner passcode and a rate limit (for example once per 30 minutes), and starts the same GitHub Action; the page then shows "updating, back in about 5 minutes". Hosted as a product (ARCHITECTURE section 10), the backend runs the job directly. Plan: the scheduled Action plus GitHub's "Run workflow" button at M1; the on-page button in phase 8, or earlier if wanted, once the scheduled job has run reliably.

## 9. PR split

Stage A (publish, current pages unchanged or minimally changed), then Stage B (frontend).

| PR | Scope | Retires |
|---|---|---|
| A0 | this document | |
| A1 | publish skeleton: `engine/publish/` (writer, schema_version and build id, rounding helpers, legacy view, JSON diff moved from `legacy_position_impact`), `engine build` (dist/ = current site + generated data + config.json), `engine update`, `engine build --verify`, CI build + schema + path checks on `dist/` | |
| A1b | M0: Actions deploy of the unchanged root plus `/next/`, secrets, season cache, sanity checks, smoke test, failure alerts | "deploy from branch" |
| A2 | games and manager files: matchups.json, matchup_data.csv, preach_manager_stats.csv, franchise_leaders, best_single_week, roster_stints; index and managers client math into `index.json` / `managers/*.json` | `update_2026.py` |
| A3 | trade-value: the five `regenerate_data_files.py` outputs, most traded, total QUAD | `regenerate_data_files.py` |
| A4 | impact and odds: position-impact, dst-impact, playoff odds | |
| A5 | draft pages: draft-history, draft-fingerprints, draft-analysis, surplus-value (new goldens for tips and best/worst lists), managers heatmap summaries | |
| A6 | transaction pages, in two PRs: A6a waiver-value; A6b lineup-efficiency (port bench depth and depth-adjusted efficiency, new page goldens) | |
| A7 | extra-analytics, in two PRs: A7a matchup sections (luck chart golden), A7b model sections (editorial `team_names.yaml`) | |
| A8 | in three PRs: A8a champions and schedule_release (editorial `schedule_themes.yaml`; `team_names.yaml` split into `shown` and `short` names), A8b weekly rankings (editorial files, frozen snapshots, derived fields, `engine rankings new`, `pro_games`), A8c headshots | the PC rankings builder (at M1) |
| F1a | foundations, part 1: the synthetic league (`engine/testing/synthetic.py`, `leagues/synthetic/league.yaml`), a CI job running normalize, analyze and `build --verify` on it, and the generic fixes it surfaced (positions from the league's lineups, conference-free leagues, champion runs of any length, sparse draft-profile features, page models only for a league without the legacy template: `league.yaml` `legacy` block) | |
| F1b | foundations, part 2: build provenance in `build-manifest.json` (engine version, commit, league config and editorial digests, input table digests), a page data size budget in `build --verify` (fail above 5 MB per file, INFO above 1.5 MB), headless page tests in CI (`tools/smoke_pages.py`, screenshots kept 14 days), CI actions on Node 24 and the runner pinned to Ubuntu 24.04 | |
| M1 | switch the live deploy to engine-mode data under the current pages; release notes from the engine change list | legacy weekly process |
| B1 | `web/` core: tokens.css, base and component CSS, `core/config.js`, `data.js`, `managers.js`, `nav.js`, `format.js`; CI check for manager names and hex colors outside `leagues/` | |
| B2+ | pages moved into `web/` in batches, each reading its JSON and `config.json`; legacy views deleted as each page moves | the legacy view per page |

Improvements folded into Stage B (requested, tracked here): schedule luck by season on the extra-analytics luck chart, a Career / season toggle per manager reading `schedule_luck.seasons` from `extra-analytics.json` (Ethan, session 7). Schedule release for any league (Ethan, session 7): every league gets a card for every ESPN matchup with no setup (managers, all-time head-to-head record, every past result with its MVP, closest, blowout, most recent, plus playoff rematch and trade count whenever the pair has them); week themes are an optional extra from the league's `schedule_themes.yaml`, never required. The Stage B page reads the season, conferences, colors and logos from `config.json` instead of today's hardcoded 2026, `CONF` and theme maps. Stage B foundations recorded at F1 (2026-10-06): reference docs for the page data generated from the JSON schemas; one shared data loader in `web/core/data.js` with loading, empty and error states, so every page handles a missing or failed file the same way; the headless page test pointed at `dist/` once pages read `data/v1/` (today it covers the live root). Stage B housekeeping from A7b: the R2 history (`R2_LABELS`, `R2_VALS` minus the current fit) and the schedule-swap caveats move to editorial files.
| M2 | cutover (phase 6) | old root files (a later PR) |
