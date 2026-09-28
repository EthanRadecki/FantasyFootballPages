# 0002: ESPN is the only provider in v1

Date: 2026-09-28. Status: accepted.

## Context
Sleeper and Yahoo would widen the audience, but each needs its own extraction and mapping work, and the existing pipeline is ESPN-based.

## Decision
Support ESPN only in v1. All analytics read canonical tables, never provider output, so Sleeper and Yahoo can be added later as new providers without touching analytics or the site.

## Consequences
The provider interface is designed now, implemented once. Managers are keyed by provider member id, not name.
