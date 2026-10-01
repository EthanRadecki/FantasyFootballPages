# Legacy pipeline scripts (frozen)

These are the original pipeline scripts, committed as they were on 2026-09-28 so their history and logic are preserved in git.

- **Reference only.** Nothing new imports from here, and these are not edited.
- **Many will not run as-is.** Twelve use hardcoded sandbox paths (`/mnt/user-data/uploads/`, `/home/claude/...`); see `docs/INVENTORY.md`.
- **Deleted as they are ported.** Each script is removed once the engine module that replaces it reproduces its output exactly (golden tests in `engine/tests/golden/`).

Phase 3 (analytics) left only `regenerate_data_files.py` and `update_2026.py`, which write and patch the site's data files. `update_2026.py` was retired in phase 4 PR A2 (its five files are written by `engine/publish/pages/games.py` and `managers.py`) and `regenerate_data_files.py` in PR A3 (`engine/publish/pages/trades.py`). Every legacy script is now retired; all of them remain in git history.
