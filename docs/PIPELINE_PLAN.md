# Pipeline consolidation plan

Status: draft, 2026-09-28. How the 58 legacy scripts in `engine/_legacy/` collapse into about 15 engine modules.

This first version is built from script names and the files each script reads and writes. Each group is confirmed by reading its scripts in full before porting, and a legacy script is deleted only when its replacement reproduces its output (golden tests).

| New module | Replaces | Main simplification |
|---|---|---|
| `providers/espn.py` (done) | `pull_espn_inseason_data`, `pull_espn_stats`, `pull_espn_2026`, `pull_espn_stats_2026`, `pull_current_season_data`, `test_espn_*`, `test_kona_playercard` | One pull path for every season |
| `normalize/espn.py` | `parse_draft_history`, `match_players`, `rename_players` | ESPN player and member ids replace name matching; draft picks come from ESPN |
| `analytics/stints.py` (trade stints built) | `compute_stints`, `rebuild_player_stints`, `generate_roster_stints`, `generate_waiver_stint_data` | One stint builder with the forfeit fix built in |
| `analytics/trades.py` (built and verified, PR #6; trade explorer JSON pending) | `detect_trade_reversals`, `build_trade_universe`, `compute_metrics`, `compute_quad`, `build_trade_explorer_data`, trade parts of `regenerate_data_files` | A five-file relay becomes function calls |
| `analytics/weeks.py` (built) | `playoff_weights`, position baseline (builder lost) | Bracket weeks, forfeits, playoff weights, position z-scores defined once |
| `analytics/draft.py` (built and verified) | `surplus_value_index`, `surplus_value_index_2026_live`, `hit_rate_by_round`, `generate_draft_heatmap`, `match_players` (draft board data still to port: `generate_draft_board_data`) | Career and live are one function; stats by player id from the full player pool |
| `analytics/draft_profiles.py` | `draft_fingerprint`, `generate_fingerprints`, `generate_archetypes` | Three overlapping scripts become one |
| `analytics/schedule.py` (luck and swap built and verified; projected SOS next) | `build_schedule_luck`, `build_schedule_swap`, `build_projected_sos` | Luck and swap share one set of regular-season games; forfeits come from the data, not a hardcoded list |
| `analytics/playoff_odds.py` | `generate_playoff_odds`, `generate_playoff_odds_2026_live`, `playoff_weights` | Historical and live become one simulation |
| `analytics/position_impact.py` | `generate_position_impact`, `generate_dst_impact` | D/ST handled as a position |
| `analytics/records.py`, `analytics/lineups.py` (built and verified) | `generate_franchise_leaders`, `generate_best_single_week`, `generate_blunder_rosters`, `generate_lineup_efficiency`, `build_matchups_json`, their parts of `update_2026` | One code path for every season; finished weeks only; blunders and forfeits derived, not hardcoded |
| `analytics/attribution.py`, `analytics/similarity.py` | `build_attribution_model_final`, `build_win_attribution_final`, `recompute_weights2`, `export_quarterly_regression`, `historical_similarity`, `export_similarity_grid` | |
| `publish/` | remaining `regenerate_data_files`, all `export_*` output code, `update_2026` | One JSON writer; no in-place patching |
| (deleted) | `player_ppr_pullscript.R`, `build_cards.py` (confirm) | |
| (retired, not ported) | `export_luck_analysis`, `export_h2h_matrix`, `export_draft_analysis` (one-off portfolio PNGs); `pull_nfl_schedule`, `pull_player_opponents`, `build_position_sos_index` (a different project) | |

## Shared rules, defined once

- Regular season and playoff weeks: from `league.yaml` (`regular_season_weeks`, `playoff_rounds`).
- Replacement level: only players with games > 0.
- D/ST scores: ESPN's raw points, negatives kept. A floor at 0 was considered and never adopted.
- Position baseline (weekly mean and SD per position): starters and bench, IR excluded.
- Finished weeks only: a week counts once every regular-season and winners-bracket game has a result.
- Realized value counts started weeks only (bench and IR excluded); stints span every later week the acquiring manager rosters the player, gaps included.
- Manager identity: hashed member keys (`engine/identity.py`); names only for display.
- Exclusions: `analysis.exclude_managers` from config are included in every calculation and hidden from view (`hidden` flag, visible-only ranks); `analysis.exclude_games` from config.
