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
| `trades/lineup_efficiency.csv.gz` | `generate_lineup_efficiency.py` | used for the forfeit flag now; the lineups module later |

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

## schedule/

Added 2026-09-29. Checked by `engine analyze --verify` and by `engine/tests/test_schedule.py`, which rebuilds matchups from `matchup_data.csv.gz` so CI covers the port.

| File | Source | Covers |
|---|---|---|
| `schedule/schedule_luck_season.csv.gz` | `build_schedule_luck.py` output | per manager and season, 2020-2025. Built from an older `matchup_data.csv`: two 2025 rows (Hancock, Bileydi) trade one expected win, excused by rerunning the legacy logic on the current file |
| `schedule/schedule_swap.json.gz` | `build_schedule_swap.py` output | identical to `SCHEDULE_SWAP_DATA` inline in `extra-analytics.html` |

Never edit these to make a check pass. If a legacy file is wrong, record the fix in the check (`engine/legacy.py`) with a comment explaining the legacy bug.
