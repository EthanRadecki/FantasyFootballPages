# 0004: ADP comes from a draft-day provider copy, else a shared library

Date: 2026-09-30. Status: accepted (Ethan, session 5).

## Context
Draft profiles compare every pick with average draft position (ADP). The legacy pipeline read FantasyPros exports by hand for each season and joined them to the draft by player name. The product has to work for any imported league and any season it has, including seasons before 2020.

ESPN's API does carry an ADP for every player (`ownership.averageDraftPosition`), but only as a live value. Checked against Preach's raw cache in session 5: it keeps moving through the season as ESPN leagues keep drafting (Saquon Barkley 2020, hurt in week 2, shows 165.9), it resets once the season is over (all of 2025 reads 170), and it matches the FantasyPros ESPN column poorly for past seasons (r = 0.64). ESPN's PPR draft rank moves the same way. So the API cannot supply past ADP.

## Decision
ADP for a season comes from, in order:

1. **The provider's draft-day copy.** `engine pull` saves ESPN's ADP for every pool player (`adp_snapshot.json`) the first time it runs after the league's draft finished in a live season, with the draft date, and never overwrites it. Normalize uses it only if it was taken within `analysis.adp.snapshot_max_days` (default 3) of the draft.
2. **The engine's shared ADP library,** `engine/data/adp/<library>/<season>.txt|.csv`: one FantasyPros export per season and scoring type, the same for every league, read in both layouts FantasyPros has used. The provider's column is read (ESPN for ESPN leagues). v1 ships PPR only (`fantasypros_ppr`, 2018-2026).
3. **Nothing.** The season gets no ADP rows and ADP-based metrics stay blank; metrics that need no ADP still work.

Library rows are joined to the league's player ids by season, position and a loose name key (no periods, no Jr/Sr/II-V, defenses by nickname). A key that fits two players stays unmatched. Unmatched rows are kept, since they still count when ranking players within a position.

## Consequences
- New seasons of any league get ADP with no files, provided `engine pull` runs within a few days of the draft. The weekly runbook needs that step.
- Past seasons depend on the library, maintained once a year for all leagues (FantasyPros has no free API; downloads stay manual). Standard and half-PPR leagues need those libraries added before their draft metrics use the right market.
- Preach's page used a 2026 ADP copy that no longer exists (not the export in the library, not today's API value). The engine uses the library for Preach 2026, and the page's 2026 draft profile values are excused by pattern at the draft-profiles check.
