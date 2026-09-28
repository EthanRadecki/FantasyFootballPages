# Golden files

Frozen copies of the legacy pipeline's outputs, taken 2026-09-28. `engine normalize --verify` must reproduce them before anything builds on the canonical tables.

| File | Source | Covers |
|---|---|---|
| `matchup_data.csv.gz` | `data/matchup_data.csv` | 2020-2025, every non-bye game, both teams |
| `weekly_rosters_bracket_only.csv.gz` | `GitHubRepoData/weekly_rosters_bracket_only.csv` (local pipeline) | 2020-2025 lineups; playoff weeks keep only winners-bracket teams |

Never edit these to make a check pass. If a legacy file is wrong, record the fix in the check (`engine/legacy.py`) with a comment explaining the legacy bug.
