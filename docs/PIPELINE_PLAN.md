# Pipeline consolidation plan

Status: draft, 2026-09-28. How the 58 legacy scripts in `engine/_legacy/` collapse into about 15 engine modules.

This first version is built from script names and the files each script reads and writes. Each group is confirmed by reading its scripts in full before porting, and a legacy script is deleted only when its replacement reproduces its output (golden tests).

| New module | Replaces | Main simplification |
|---|---|---|
| `providers/espn.py` (done; legacy pulls and API tests deleted, PR #27) | `pull_espn_inseason_data`, `pull_espn_stats`, `pull_espn_2026`, `pull_espn_stats_2026`, `pull_current_season_data`, `test_espn_*`, `test_kona_playercard` | One pull path for every season |
| `normalize/espn.py` (done; legacy scripts deleted, PR #27) | `parse_draft_history`, `match_players`, `rename_players` | ESPN player and member ids replace name matching; draft picks come from ESPN |
| `analytics/stints.py` (trade stints built) | `compute_stints`, `rebuild_player_stints` | One stint builder with the forfeit fix built in |
| `analytics/waivers.py` (built and verified) | `generate_roster_stints`, `generate_waiver_stint_data`, the lost `waiver_stints_full.csv` builder | Waiver stint rules recovered from the legacy file and written down; roster stints from counted games |
| `analytics/trades.py` (built and verified, PR #6; trade explorer PR #26) | `detect_trade_reversals`, `build_trade_universe`, `compute_metrics`, `compute_quad`, `build_trade_explorer_data`, trade parts of `regenerate_data_files` | A five-file relay becomes function calls |
| `analytics/weeks.py` (built) | `playoff_weights`, position baseline (builder lost) | Bracket weeks, forfeits, playoff weights, position z-scores defined once |
| `analytics/draft.py` (built and verified) | `surplus_value_index`, `surplus_value_index_2026_live`, `hit_rate_by_round`, `generate_draft_heatmap`, `match_players`, `generate_draft_board_data` (draft board, PR #26) | Career and live are one function; stats by player id from the full player pool |
| `normalize/adp.py` (built and verified, PR #23) | the ADP load and name join in `draft_fingerprint` | ADP from a draft-day provider copy or the shared library in `engine/data/adp/`, joined by player id (decision 0004) |
| `analytics/draft_profiles.py` (built and verified, PRs #24-#25) | `draft_fingerprint`, the lost draft-fingerprints.html builder, `generate_fingerprints` (managers.html radar; replaced by the 10-dim fingerprint at publish) | Three overlapping scripts become one; `generate_archetypes` retired (feeds no page; Ethan, session 5) |
| `analytics/schedule.py` (built and verified) | `build_schedule_luck`, `build_schedule_swap` | Luck and swap share one set of regular-season games; forfeits come from the data, not a hardcoded list |
| `analytics/projected_sos.py` (built and verified) | `build_projected_sos` | Start week, schedule, byes, and team names come from ESPN; best projected lineup from the whole roster |
| `analytics/playoff_odds.py` (built and verified) | `generate_playoff_odds`, `generate_playoff_odds_2026_live` | Historical and live are one simulation; cutoff, divisions, and season length from the league; live blends projections |
| `analytics/position_impact.py` (built and verified) | `generate_position_impact`, `generate_dst_impact` | D/ST handled as a position; one calculation feeds both pages; Nth pick and playoff field from the league |
| `analytics/records.py`, `analytics/lineups.py` (built and verified) | `generate_franchise_leaders`, `generate_best_single_week`, `generate_blunder_rosters`, `generate_lineup_efficiency`, `build_matchups_json`, their parts of `update_2026` | One code path for every season; finished weeks only; blunders and forfeits derived, not hardcoded |
| `analytics/manager_seasons.py` (built and verified; draft slot results PR #28) | `data/preach_manager_stats.csv` (maintained by hand, no script); draft-analysis.html's slot table (builder lost) | Every column derived from the canonical tables; formulas recovered from the file |
| `analytics/attribution.py` (built and verified) | `build_win_attribution_final` | Five factors from engine tables, not five hand-copied CSVs |
| `analytics/gauntlet.py` (built and verified) | `recompute_weights2` | Champion runs found from the bracket, not a hardcoded list; one calculation for the cards, ranks, and lists |
| `analytics/matchup_history.py` (built and verified) | extra-analytics.html blocks with no script: head-to-head matrix (`export_h2h_matrix` logic), closest games, conference analysis | Every number from counted games; conference from ESPN's division id |
| `analytics/regressions.py` (built and verified) | `export_quarterly_regression` (numbers only), and the positional production table and regression on extra-analytics.html (no script) | One fit for each model, from counted games; the page's unreproducible quarterly numbers replaced |
| `publish/` (skeleton PR A1; games and managers PR A2; trade-value PR A3; position impact, D/ST impact, playoff odds PR A4; draft pages and the managers.html draft board map PR A5; waiver-value PR A6a; lineup-efficiency PR A6b (bench depth, depth-adjusted efficiency and the neglected-lineup flag ported into `analytics/lineups.py`); extra-analytics matchup sections PR A7a and model sections PR A7b; see PUBLISH_PLAN.md) | `update_2026` (retired, A2), `regenerate_data_files` (retired, A3), all `export_*` output code | One JSON writer; no in-place patching |
| (deleted, PR #27) | `player_ppr_pullscript.R` (old nflfastR stats pull); `build_cards.py` (schedule-reveal PNG experiment; Ethan, session 5. schedule_release.html stays and never read its output) | |
| (retired, not ported) | `export_luck_analysis`, `export_h2h_matrix`, `export_draft_analysis`, `export_similarity_grid` (one-off portfolio PNGs; `export_quarterly_regression`'s numbers are ported, its PNG retired); `historical_similarity` (never on the site; Ethan, session 4); `build_attribution_model_final` (an earlier attribution model, superseded); `generate_archetypes` (fed no page; Ethan, session 5); `generate_fingerprints` (managers.html's 7-measure radar, reproduced in session 5 with the weighted surplus, then replaced by the 10-measure profile; Ethan, session 5); `pull_nfl_schedule`, `pull_player_opponents`, `build_position_sos_index` (a different project) | |

## Shared rules, defined once

- Regular season and playoff weeks: from `league.yaml` (`regular_season_weeks`, `playoff_rounds`).
- Replacement level: only players with games > 0.
- D/ST scores: ESPN's raw points, negatives kept. A floor at 0 was considered and never adopted.
- Position baseline (weekly mean and SD per position): starters and bench, IR excluded.
- Finished weeks only: a week counts once every regular-season and winners-bracket game has a result.
- Consolation weeks never count. Counted games: regular season plus winners bracket, no byes. Bracket weeks: every finished regular-season week (byes included) plus a team's winners-bracket playoff weeks.
- Realized value counts started weeks only (bench and IR excluded); stints span every later week the acquiring manager rosters the player, gaps included.
- Manager identity: hashed member keys (`engine/identity.py`); names only for display.
- Exclusions: `analysis.exclude_managers` from config are included in every calculation and hidden from view (`hidden` flag, visible-only ranks); `analysis.exclude_games` from config (`from: [ppg]` leaves a game out of points per game; first used by manager season stats).
