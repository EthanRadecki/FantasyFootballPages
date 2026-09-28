# 0001: One engine, league as configuration

Date: 2026-09-28. Status: accepted.

## Context
The site is being restructured so it can be rebuilt for any league, not just Preach Fantasy. Today league facts (manager names, colors, season lengths, exclusions) are hardcoded across every page and script.

## Decision
Split the repo into three layers: a league-agnostic engine (pipeline plus web template), a per-league `league.yaml`, and an optional per-league editorial folder. Engine and template code may not contain league-specific values; CI enforces this.

## Consequences
Preach Fantasy becomes the first instance of the engine. Every hardcoded value found in `docs/INVENTORY.md` must move to config during the migration.
