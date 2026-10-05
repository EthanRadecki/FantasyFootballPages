# Golden files

Frozen copies of the legacy pipeline's outputs, taken 2026-09-28. `engine normalize --verify` must reproduce them before anything builds on the canonical tables.

| File | Source | Covers |
|---|---|---|
| `matchup_data.csv.gz` | `data/matchup_data.csv` | 2020-2025, every non-bye game, both teams |
| `weekly_rosters_bracket_only.csv.gz` | `GitHubRepoData/weekly_rosters_bracket_only.csv` (local pipeline) | 2020-2025 lineups; playoff weeks keep only winners-bracket teams |
| `draft_history_all_positions.csv.gz` | `GitHubRepoData/draft_history_all_positions.csv` | 2020-2026 drafts, K and D/ST included |
| `transactions_clean.csv.gz` | `GitHubRepoData/transactions_clean.csv` | 2020-2025 transaction items. Its `Player` column is scrambled (one id, several names) and is never compared |

## trades/

Legacy trade pipeline outputs (`GitHubRepoData/`, local pipeline), added 2026-09-29. Checked by `engine analyze --verify` and by `engine/tests/test_trades.py`, which rebuilds canonical-shaped tables from the legacy inputs so CI covers the whole port.

| File | Legacy script | Covers |
|---|---|---|
| `trades/trades_mapped.csv.gz` | (builder lost) | 2020-2025, one row per player moved in a trade, 871 rows |
| `trades/trades_mapped_clean.csv.gz` | `detect_trade_reversals.py` | after mirror-pair removal, 741 rows |
| `trades/trade_universe.csv.gz` | `build_trade_universe.py` (earlier version, see `engine/legacy_trades.py`) | 150 groups, 333 sides |
| `trades/position_baseline.csv.gz` | (builder lost) | weekly position mean and sample SD over all rostered players |
| `trades/player_stints_fixed.csv.gz` | `rebuild_player_stints.py` | 639 received-player stints |
| `trades/metrics_final.csv.gz` | `compute_metrics.py`, `compute_quad.py` | per-side metrics and QUAD |
| `trades/trade_explorer_data.json.gz` | `data/trade_explorer_data.js` (`build_trade_explorer_data.py`, a version rounding necessity to 3 places) | 150 trade nodes, 333 sides, for the trade explorer on trade-value.html |
| `trades/lineup_efficiency.csv.gz` | `generate_lineup_efficiency.py` | used for the forfeit flag now; the lineups module later |

### trades/ page goldens (phase 4, PR A3)

Frozen 2026-10-01 from the live site with `tools/freeze_golden.py`. Checked by `engine build --verify` (the trade-value legacy views built from legacy-mode analysis) and by `engine/tests/test_publish_pages.py` (the same views built from the legacy pipeline's own outputs above, so CI covers them).

| File | Source | Covers |
|---|---|---|
| `trades/page_data.json.gz` | `data/page_data.js` (`regenerate_data_files.py`, a later version that also wrote `wk`) | LEADERBOARD, the five scales, BEST_WORST, TRADES (328 visible sides) |
| `trades/network_data.json.gz` | `data/network_data.js` | NETWORK_DATA, visible managers |
| `trades/winpct_data.json.gz` | `data/winpct_data.js` | WINPCT_DATA (win % from `lineup_efficiency.csv`) |
| `trades/trade_week_data.json.gz` | `data/trade_week_data.js` | TRADE_WEEK_DATA, every manager, 333 sides |
| `trades/most_traded_data.json.gz` | `data/most_traded_data.js` (no script; rule recovered: one entry per received player in `player_stints_fixed.csv`, receiving managers in order, position from the rosters file, sorted by count) | MOST_TRADED, 283 players |
| `trades/trade_value_inline.json.gz` | the inline `LEADERBOARD_TOTALS` of `pages/trade-value.html` | summed QUAD per manager, career and by season |

## records/

Legacy site files for the records and lineups module, added 2026-09-29. Checked by `engine analyze --verify`.

| File | Source | Covers |
|---|---|---|
| `records/matchups.json.gz` | `data/matchups.json` (`build_matchups_json.py`, `update_2026.py`) | 638 games, 2020 through 2026 week 2 |
| `records/franchise_leaders.json.gz` | `data/franchise_leaders.json` | manager x player x season, 2020 through 2026 week 2 |
| `records/best_single_week.json.gz` | `data/best_single_week.json` | top 25 started weeks per manager, position, season |
| `records/lineup_blunders.csv.gz` | the `BLUNDERS` list in `generate_blunder_rosters.py` | the 10 biggest efficiency gaps, in order |

## draft/

| File | Source | Covers |
|---|---|---|
| `draft/espn_player_stats_season.csv.gz` | `pull_espn_stats.py`, rerun 2026-09-29 for 2020-2025 (reproduces every PPG, games, and position baseline in `draft_surplus_v2.csv`) | 3,814 player-seasons: every rostered player plus 500 free agents, skill positions |
| `draft/espn_player_stats_2026.csv.gz` | `pull_espn_stats_2026.py`, at the last 2026 site update (weeks 1-2) | 2026 player universe used by the live grades |
| `draft/draft_surplus_v2.csv.gz` | `surplus_value_index.py` | per-pick PRV, expected PRV, surplus, 2020-2025 |
| `draft/surplus_value_data.json.gz` | `surplus_value_index.py` | career and season draft grades |
| `draft/surplus_value_2026_live.csv.gz`, `.json.gz` | `surplus_value_index_2026_live.py` | 2026 live per-pick surplus and grades |
| `draft/draft_heatmap.json.gz` | `generate_draft_heatmap.py` | per-manager board by round and slot |
| `draft/hit_rate_data.json.gz` | `hit_rate_by_round.py` | hit rate by round and tier, steals |
| `draft/draft_with_stats.csv.gz` | `match_players.py` | legacy pick-to-stats name matches, including the hand-kept `manual_zero` list |
| `draft/draft_fingerprint_manager_season.csv.gz` | `draft_fingerprint.py`, rerun 2026-09-30 on its own inputs (its career and history outputs match Ethan's copies exactly) | 85 manager-seasons, 2020-2025, 33 metrics. Checked by `engine analyze --verify` and `engine/tests/test_draft_profiles.py` |
| `draft/draft_board_page.json.gz` | the inline `DRAFT` and `SLOT_ORDER` of `pages/draft-history.html` (`generate_draft_board_data.py`, run on a draft file already in the corrected 2021 order with ESPN's names) | every pick 2020-2026 with PPG and games; round-1 slot order. Checked by `engine analyze --verify` |
| `draft/draft_fingerprints_page.json.gz` | the inline `DATA` of `pages/draft-fingerprints.html` (builder lost) | fingerprints, radar scaling, archetypes, stats and scales per manager, 2020-2026. 2026 was built from an ADP copy that no longer exists. Checked by `engine analyze --verify` and `engine/tests/test_draft_profiles.py` |
| `draft/draft_fingerprint_career.csv.gz` | `draft_fingerprint.py` (Ethan's copy) | 16 managers, season means plus draft_adaptability |
| `draft/draft_history_with_adp.csv.gz` | `draft_fingerprint.py`, rerun 2026-09-30 on its own inputs (reproduces this file exactly) | 2020-2025 picks with the FantasyPros ESPN ADP and position order, 1,186 of 1,360 matched. Checked by `engine normalize --verify` and by `engine/tests/test_adp.py` |

### draft/ page goldens (phase 4, PR A5)

Frozen 2026-10-01 from the live site with `tools/freeze_golden.py`. Checked by `engine build --verify` (the draft page legacy views built from legacy-mode analysis) and by `engine/tests/test_publish_draft.py` (the same views built from the legacy pipeline's own outputs, so CI covers them). `draft_board_page`, `draft_fingerprints_page` and `draft_heatmap` (identical to managers.html's inline `HEATMAP_DATA`) above are the goldens of draft-history.html, draft-fingerprints.html and the managers.html board map.

| File | Source | Covers |
|---|---|---|
| `draft/surplus_value_page.json.gz` | the inline blocks of `pages/surplus-value.html` (`--vars CAREER_GRADES SEASON_GRADES SEASONS HEATMAP_TIPS MANAGER_BW ALL_BEST_PICKS SEASON_BEST ALL_WORST_PICKS SEASON_WORST POP_SURPLUS_MIN POP_SURPLUS_MAX`); page step lost, rules recovered (every value reproduces from `draft_surplus_v2.csv`) | grades, draft tips, highs and lows, best and worst picks, color scale, 2020-2025 |
| `draft/draft_analysis_page.json.gz` | the inline blocks of `pages/draft-analysis.html` (`--vars PLAYOFF_RATES OVERPERFS SLOT_DATA HR_BY_ROUND HR_BY_POS ALL_TIME_STEALS SEASON_STEALS CAREER_PREVIEW ABOVE_AVG_CEIL`) and its typed HTML (`--html 'slot_table::<table class="da-table">::<tbody>' 'tier_cards::<div class="hr-stat-row">'`) | slot table with its cell colors, slot charts, who drafted from each slot, hit rate, steals, surplus preview. The per-season steals contradict `hit_rate_data.json` on 89 values (retyped from another file); excused by that pattern |

## schedule/

Added 2026-09-29. Checked by `engine analyze --verify` and by `engine/tests/test_schedule.py`, which rebuilds matchups from `matchup_data.csv.gz` so CI covers the port.

| File | Source | Covers |
|---|---|---|
| `schedule/schedule_luck_season.csv.gz` | `build_schedule_luck.py` output | per manager and season, 2020-2025. Built from an older `matchup_data.csv`: two 2025 rows (Hancock, Bileydi) trade one expected win, excused by rerunning the legacy logic on the current file |
| `schedule/schedule_swap.json.gz` | `build_schedule_swap.py` output | identical to `SCHEDULE_SWAP_DATA` inline in `extra-analytics.html` |

## sos/

Added 2026-09-29. Checked by `engine analyze --verify` and by `engine/tests/test_projected_sos.py`. ESPN projections change daily, so only the averaging and ranking step is checked, fed the legacy weekly totals.

| File | Source | Covers |
|---|---|---|
| `sos/projected_sos_weekly_detail.csv.gz` | `build_projected_sos.py` weekly detail, `START_WEEK` 3 | each team's projected total, weeks 3-14 |
| `sos/projected_sos_2026.csv.gz` | `build_projected_sos.py` output from those totals | own and opponent averages, rank |
| `sos/schedule_2026.csv.gz` | the `schedule_2026.csv` next to the legacy script on the local pipeline | an early draft of the 2026 schedule; differs from ESPN's and from `data/schedule_2026.csv` from week 2 on, so the published week 1-3 SOS used the wrong opponents |
| `sos/rankings_2026_week03.json.gz` | `data/rankings/2026_week03.json` | the SOS values copied onto the rankings page |

## playoff_odds/

Added 2026-09-29. `playoff_odds/playoff_odds.json.gz` is `data/rankings/playoff_odds.json`: 2020-2025 from `generate_playoff_odds.py` (reproduced exactly from `matchup_data.csv.gz`), 2026 weeks 1-3 from `generate_playoff_odds_2026_live.py` (week 3 reproduced exactly from the `sos/` goldens and 2026 results in `records/matchups.json.gz`; week 2's projection input no longer exists). CI checks 2020 and 2026 week 3; `engine analyze --verify` checks every season.

## waivers/

Added 2026-09-29. Checked by `engine analyze --verify`.

| File | Source | Covers |
|---|---|---|
| `waivers/waiver_stints_full.csv.gz` | `GitHubRepoData/waiver_stints_full.csv` (builder lost; identical to `WAIVER_STINTS` inline in waiver-value.html) | 1,757 pickups, 2020-2025 |
| `waivers/waiver_page.json.gz` | `LEADERBOARD_FULL`, `CONTESTED_SPLIT`, `BEST_BY_MANAGER`, `BEST_PICKUPS_BY_FILTER` from waiver-value.html | the page's aggregates (computed from the file's rounded values) |
| `waivers/roster_stints.json.gz` | `data/roster_stints.json` (managers page) | runs of counted game weeks per manager and player, 2020 through 2026 week 2 |
| `waivers/waiver_value_page.json.gz` | every inline data block of `pages/waiver-value.html`, frozen 2026-10-01 with `tools/freeze_golden.py` (PR A6a); its four aggregates equal `waiver_page.json.gz` and its `WAIVER_STINTS` the stint file | checked by `engine build --verify` (the legacy view built from legacy-mode stints) and `engine/tests/test_publish_transactions.py` (built from `waiver_stints_full.csv.gz`). 33 player names differ from ESPN's (Gabriel Davis, Gardner Minshew II): the same pickups, excused by that pattern |

## lineups/

Added 2026-10-01 (PR A6b). Checked by `engine build --verify` (the legacy view built from legacy-mode lineup efficiency) and `engine/tests/test_publish_transactions.py` (built from `trades/lineup_efficiency.csv.gz` and `weekly_rosters_bracket_only.csv.gz`).

| File | Source | Covers |
|---|---|---|
| `lineups/lineup_efficiency_page.json.gz` | every inline data block of `pages/lineup-efficiency.html`, frozen with `tools/freeze_golden.py` (builders: `generate_lineup_efficiency.py`, `generate_blunder_rosters.py`, lost page steps) | efficiency, missed wins, blunders and their rosters, bench depth, depth-adjusted efficiency, season trend, depth vs win %, heatmap and career grid, 2020-2025. Means at a rounding tie (float noise; 8 values) excused by nudging every gap 1e-9 |

## position_impact/

Added 2026-09-29. Checked by `engine analyze --verify`, which rebuilds the scripts' inputs from the legacy files (games from `matchup_data.csv.gz` in file order, picks from `draft_history_all_positions.csv.gz`, players keyed by name) and compares every section of both pages.

| File | Source | Covers |
|---|---|---|
| `position_impact/position_impact_data.json.gz` | `data/position_impact_data.json` (`generate_position_impact.py`) | 598 games, 2020-2025 |
| `position_impact/dst_removed_data.json.gz` | `data/dst_removed_data.json` (`generate_dst_impact.py`) | built from an older `matchup_data.csv` (McQuaid 84.46 in 2025 week 14) |
| `position_impact/player_stints.csv.gz` | `GitHubRepoData/player_stints.csv`, the trade stints both scripts read | differs from `trades/player_stints_fixed.csv.gz` on 56 stint lengths |

## manager_seasons/

Added 2026-09-30. Checked by `engine analyze --verify` (finished seasons, and the 2026 rows against the engine run on weeks 1-2) and by `engine/tests/test_manager_seasons.py`, which rebuilds matchups from `matchup_data.csv.gz` so CI covers the computed columns.

| File | Source | Covers |
|---|---|---|
| `manager_seasons/preach_manager_stats.csv.gz` | `data/preach_manager_stats.csv`, maintained by hand (no script wrote it) | one row per manager and season, 2020-2025 plus a 2026 snapshot after week 2. 2021-2024 values typed rounded; one hand-entered PA (Maney 2025, 1609.20 vs 1608.20 in its own source); a few hand-entered ranks. All excused by pattern in `engine/legacy_manager_seasons.py` |
| `manager_seasons/draft_slots_page.json.gz` | `pages/draft-analysis.html` (Detailed Breakdown table, `OVERPERFS`, `SLOT_DATA`); builder lost | results by draft slot 1-14 for 2020-2025 and who drafted from each slot through 2026. Champ % and Avg PF/G contradict the manager season file and are excused by that pattern |

## attribution/

Added 2026-09-30. Checked by `engine analyze --verify` and `engine/tests/test_attribution.py` (legacy files only, so CI runs the whole check).

| File | Source | Covers |
|---|---|---|
| `attribution/win_attribution_final.json.gz` | `build_win_attribution_final.py` output (`win_attribution_final.json`); its `DATA` is identical to the inline `DATA` on extra-analytics.html | the fit, standardized coefficients, p-values, and each manager's waterfall |
| `attribution/attribution_season_data_final.csv.gz` | the factor table it fit | 83 manager-seasons, 2020-2025. Its luck column is newer than `schedule/schedule_luck_season.csv.gz` on two 2025 rows (Hancock, Bileydi), excused by rerunning the legacy luck logic |

## gauntlet/

Added 2026-09-30. Checked by `engine analyze --verify` and `engine/tests/test_gauntlet.py` (legacy files only, so CI runs the whole check).

| File | Source | Covers |
|---|---|---|
| `gauntlet/extra_analytics_gauntlet.json.gz` | the inline `CHAMPION_RANKS`, `CHAMPIONS`, `HARDEST`, `EASIEST` blocks of extra-analytics.html, parsed to JSON | champions' ranks and the hardest and easiest lists reproduce exactly from `recompute_weights2.py` logic on `matchup_data.csv.gz` and the stats file, cut at 2025. The champion cards came from an earlier, lost variant (raw dominance, older league averages, different surges); their games and internal math are checked, their surges are not |

## matchup_history/

Added 2026-09-30. Checked by `engine analyze --verify` (needs the canonical tables).

| File | Source | Covers |
|---|---|---|
| `matchup_history/extra_analytics_matchups.json.gz` | extra-analytics.html: the inline `managers`/`h2h` matrix and `CLOSEST` lists, and the Conference Analysis cards and tables parsed from the HTML | 2020-2025. The closest regular-season and playoff lists skip some games the all-games list includes; the conference average PF/game (111.9, 110.9) was typed by hand |
| `matchup_history/extra_analytics_inline.json.gz` | the inline `managers`, `h2h`, `CLOSEST`, `luckData`, `SCHEDULE_SWAP_DATA` and the typed conference markup (`--html` blocks: teams grid, totals, manager, season and rivalry tables) of extra-analytics.html, frozen 2026-10-01 (PR A7a); refrozen the same day with the model literals (`labels`, `coefs`, `corrs`, `pvals`, `POSITIONS`, `DATA`, `STD_COEF`, `COEF_PVAL`, `CORR_R`, `DATA#1`, `LEAGUE_INTERCEPT`, `COEF_LABELS`, `COEF_VALS`, `R2_VALS`, `CHAMPION_RANKS`, `CHAMPIONS`, `HARDEST`, `EASIEST`; PR A7b), the A7a blocks unchanged | checked by `engine build --verify` and `engine/tests/test_publish_transactions.py`; the markup parses back to exactly the conference tables above. `luckData` is the luck file summed, except Gorman's typed 38 expected wins |
| `champions/champions_inline.json.gz` | the inline `CHAMPS` and `FINALS` of champions.html, frozen 2026-10-05 (PR A8a) | checked by `engine build --verify` and `engine/tests/test_publish_season_pages.py`; the cards' builder is lost, the rules are in METRICS_REFERENCE (Champions) |
| `schedule_release/manager_schedule.json.gz`, `schedule_release/schedule_by_week.json.gz` | `data/manager_schedule.json` and `data/schedule_by_week.json` (the 2026 schedule release), frozen 2026-10-05 (PR A8a) | checked by `engine build --verify` and `engine/tests/test_publish_season_pages.py`; two scores predate an ESPN stat correction |

## regressions/

Added 2026-09-30. Checked by `engine analyze --verify` and `engine/tests/test_regressions.py` (legacy files only, so CI runs the whole check).

| File | Source | Covers |
|---|---|---|
| `regressions/extra_analytics_regressions.json.gz` | extra-analytics.html: positional `DATA`, `STD_COEF`, `COEF_PVAL`, `CORR_R`, the R2 in the methodology text, and the quarterly `coefs`, `corrs`, `pvals` | the positional table reproduces exactly from `weekly_rosters_bracket_only.csv.gz` (game weeks) and `matchup_data.csv.gz`; its regression is within 0.005 (0.012 for p-values) of that fit; the quarterly correlations reproduce exactly, its coefficients and p-values do not (replaced, Ethan's decision) |

Never edit these to make a check pass. If a legacy file is wrong, record the fix in the check (`engine/legacy.py`) with a comment explaining the legacy bug.
