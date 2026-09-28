# Legacy pipeline scripts (frozen)

These are the original pipeline scripts, committed as they were on 2026-09-28 so their history and logic are preserved in git.

- **Reference only.** Nothing new imports from here, and these are not edited.
- **Many will not run as-is.** Twelve use hardcoded sandbox paths (`/mnt/user-data/uploads/`, `/home/claude/...`); see `docs/INVENTORY.md`.
- **Deleted as they are ported.** Each script is removed once the engine module that replaces it reproduces its output exactly (golden tests in `engine/tests/golden/`).

When this folder is empty, phase 3 is done.
