# Inventory: current state

Snapshot taken 2026-09-28 from the GitHub Pages repo (`FantasyFootballPages`) and the local pipeline folder. This is the input to the migration in `ARCHITECTURE.md`; it describes what exists, not what should exist.

## 1. Summary

| Area | State | Main problems |
|---|---|---|
| Site repo | 16 pages + index, ~21.7k lines, 180 files | Monolithic pages, data inlined in HTML, hardcoded manager names and colors in every page |
| Data | 25 files in 3 formats (JSON, CSV, JS globals) | No grouping, several files with no reproducible producer |
| Images | ~100 PNG screenshots, 2.2 MB champions photo | Screenshot paths have no season (2027 will overwrite 2026), uncompressed |
| Pipeline | 67 Python scripts in one flat folder, not in git | 12 scripts use Claude sandbox paths and cannot run locally as written; versioning by filename suffix; legacy app mixed in |

## 2. Page -> data -> producer map

"Inline" means the data is pasted into the HTML. "(likely)" means the producer was inferred from file names and should be confirmed.

| Page | Data it loads | Producer script(s) |
|---|---|---|
| `index.html` | `preach_manager_stats.csv` | **none found** (manual) |
| `managers.html` | `preach_manager_stats.csv`, `matchup_data.csv`, `franchise_leaders.json`, `roster_stints.json`, `best_single_week.json`, `player_headshots.json`, rankings manifest + weeks | `generate_franchise_leaders.py`, `generate_roster_stints.py`, `generate_best_single_week.py`, `update_2026.py` (patches 2026 into all three); `matchup_data.csv` and `player_headshots.json`: **none found** |
| `matchups.html` | `matchups.json` | `build_matchups_json.py`, `update_2026.py` |
| `weekly-rankings.html` | `rankings/*.json`, `rankings/manifest.json`, `rankings/playoff_odds.json`, `player_headshots.json` | Rankings: editorial (hand-built). Odds: `generate_playoff_odds.py`, `generate_playoff_odds_2026_live.py` |
| `trade-value.html` | `page_data.js`, `network_data.js`, `winpct_data.js`, `trade_explorer_data.js`, `trade_week_data.js`, `most_traded_data.js` | `regenerate_data_files.py` (five files); `build_trade_explorer_data.py` also writes `trade_explorer_data.js` (two producers, one file); `most_traded_data.js`: **none found** |
| `position-impact.html` | `position_impact_data.json` | `generate_position_impact.py` |
| `dst-impact.html` | `dst_removed_data.json` | `generate_dst_impact.py` |
| `schedule_release.html` | `manager_schedule.json`, `schedule_by_week.json` | **none found** (`build_schedule_swap.py` writes `schedule_swap.json`, a different file) |
| `champions.html` | `player_headshots.json`, champions photo | editorial + **none found** for headshots |
| `surplus-value.html` | inline | `surplus_value_index.py`, `surplus_value_index_2026_live.py` |
| `draft-analysis.html` | inline | `hit_rate_by_round.py`, `generate_draft_heatmap.py`, `export_draft_analysis.py` (likely) |
| `draft-fingerprints.html` | inline | `draft_fingerprint.py`, `generate_fingerprints.py`, `generate_archetypes.py` (three overlapping) |
| `draft-history.html` | inline | `parse_draft_history.py` -> `generate_draft_board_data.py` (prints output for pasting) |
| `lineup-efficiency.html` | inline | `generate_lineup_efficiency.py` |
| `waiver-value.html` | inline | `generate_waiver_stint_data.py` (prints output for pasting) |
| `extra-analytics.html` | inline, plus 14 hardcoded logo paths | `build_win_attribution_final.py`, `historical_similarity.py`, `build_schedule_luck.py`, `build_schedule_swap.py` (likely) |
| `transaction-analysis.html` | inline | unknown |

Unreferenced by any page scan: `data/schedule_2026.csv`, `data-engine.js` (loaded by script tag; role to confirm in phase 4).

## 3. Hardcoded league references (site)

Count of lines per file matching a manager surname or a hex color:

| File | Refs | File | Refs |
|---|---|---|---|
| `surplus-value.html` | 241 | `trade-value.html` | 32 |
| `extra-analytics.html` | 187 | `dst-impact.html` | 30 |
| `draft-analysis.html` | 131 | `draft-fingerprints.html` | 29 |
| `managers.html` | 126 | `matchups.html` | 27 |
| `weekly-rankings.html` | 79 | `waiver-value.html` | 22 |
| `schedule_release.html` | 47 | `data-engine.js` | 20 |
| `draft-history.html` | 45 | `index.html` | 17 |
| `lineup-efficiency.html` | 44 | `position-impact.html` | 16 |
| `champions.html` | 44 | `transaction-analysis.html` | 7 |

Every page also hardcodes `preach_logo_2026.png` in its head. Hex counts include legitimate design colors, so these numbers overstate league-specific references somewhat; phase 4 separates the two.

## 4. Pipeline folder

### Composition

| Group | Count | Notes |
|---|---|---|
| Root Python scripts | 67 | Flat, no package, no entry point, no run order recorded |
| `GitHubRepoData/` | 56 files | Intermediate and final data; partial copies of site files |
| `.conda/` | ~4,400 files | Python environment inside the project folder; must never be committed |
| `static/manager_charts/` | 51 HTML files, ~3.5 MB each (~180 MB) | Plotly output from the legacy app |
| `app.py`, `templates/`, `render.yaml`, `static/` | | Legacy Flask site (Render deploy), includes basketball and dynasty hubs |

### Script roles

| Role | Scripts |
|---|---|
| Extract from ESPN | `pull_espn_inseason_data.py`, `pull_espn_stats.py`, `pull_espn_2026.py`, `pull_espn_stats_2026.py`, `pull_current_season_data.py`, `pull_player_opponents.py`, `pull_nfl_schedule.py` |
| Clean / reshape | `parse_draft_history.py` (4,790 lines; draft data likely embedded in code), `match_players.py`, `rename_players.py`, `detect_trade_reversals.py`, `compute_stints.py`, `rebuild_player_stints.py` |
| Analytics | `compute_metrics.py`, `compute_quad.py`, `build_trade_universe.py`, `surplus_value_index*.py`, `draft_fingerprint.py`, `generate_*` (15 scripts), `build_*` (9 scripts), `hit_rate_by_round.py`, `historical_similarity.py`, `playoff_weights.py`, `recompute_weights2.py` |
| Export for site | `regenerate_data_files.py`, `build_matchups_json.py`, `export_*` (5 scripts), `update_2026.py` |
| Debug / scratch | `debug_*` (4), `test_*` (4), `check.py`, `audit_picks.py`, `get_heatmap_tips.py`, `extract_manager_picks.py` |
| Other | `player_ppr_pullscript.R` |

### Problems to fix during the port

1. **Sandbox paths.** 12 scripts read or write `/mnt/user-data/uploads/`, `/home/claude/work/`, or `/home/claude/trade_pipeline/`: `build_attribution_model_final`, `build_schedule_luck`, `build_trade_universe`, `build_win_attribution_final`, `compute_metrics`, `compute_quad`, `compute_stints`, `generate_franchise_leaders`, `generate_playoff_odds`, `generate_roster_stints`, `playoff_weights`, `regenerate_data_files`. Outputs were moved into the repo by hand.
2. **No lineage.** Several site files (`matchup_data.csv`, `preach_manager_stats.csv`, `player_headshots.json`, `manager_schedule.json`, `schedule_by_week.json`, `most_traded_data.js`) have no script that writes them.
3. **Versioning by filename.** `draft_surplus` / `_v2`, `player_stints` / `_fixed`, `transactions` / `_clean` / `_namefixed`, `weekly_rosters` / `_clean` / `_bracket_only`, `*_final`, `recompute_weights2`. Git history replaces all of these.
4. **Two update paths.** Full-history scripts vs `*_2026_live.py` and `update_2026.py`, which patches 2026 rows into existing JSON in place.
5. **Copy-paste hand-off.** Some scripts print JSON to paste into HTML instead of writing files.
6. **Duplicate producers.** `trade_explorer_data.js` has two; draft fingerprints have three overlapping scripts.
7. **Credentials.** `espn_auth.json` exists in two locations; must be gitignored before anything is committed.

## 5. Assets

- Rankings screenshots: `images/rankings/week_NN/` with no season. PNG, typically 350 KB to 1 MB each.
- Manager logos: 21 files with year variants encoded in file names (`Kelly2022.png`), selected by code.
- League logos: one per season, plus an empty placeholder file `images/logos/league/blank`.
- `preach_logo.png` at repo root duplicates the league logos.
- Champions photo: 2.2 MB JPEG (also a copy in the local `static/` folder).
- Local-only: `static/rankings/rankings_week1-3.docx` (blurb drafts).

## 6. Legacy to archive, not migrate

- Flask app: `app.py`, `templates/`, `render.yaml`, `static/manager_charts/`, `generate_manager_visualizations.py`.
- Duplicate rankings JSON in `static/data/data/rankings/` (2021-2025, older copies).
- Debug and test scripts once their checks are covered by real tests.

The Flask app was never in this repo, so it is not committed at all: keep one local zip backup of it and delete it from the working folder. `tools/bundle_legacy.ps1` already leaves it (and the debug scripts) out of the legacy bundle.
